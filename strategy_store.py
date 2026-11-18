import json
import itertools
import math
import shutil
import subprocess
import threading
import time
from pathlib import Path

from strategy_library_builder import build_scene_key, load_config
from strategy_library_runtime import RuntimeStrategyLibrary


class StrategyStore:
    def __init__(self, data_dir, formal_library_root=None, formal_config_path=None,
                 preflop_library_root=None, preflop_config_path=None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        bundled_library = Path(__file__).with_name("strategy_library.json")
        self.library_file = self.data_dir / "strategy_library.json"
        if not self.library_file.exists() and bundled_library.exists():
            self.library_file.write_text(bundled_library.read_text(encoding="utf-8"), encoding="utf-8")
        self.queue_file = self.data_dir / "solver_queue.jsonl"
        self.cache_file = self.data_dir / "solver_cache.json"
        self.library = self._load(self.library_file, [])
        self.cache = self._load(self.cache_file, {})
        config_path = Path(formal_config_path or
                           Path(__file__).with_name("strategy_library_builder.json"))
        try:
            self.formal_config = load_config(config_path)
        except (OSError, ValueError, KeyError):
            self.formal_config = None
        root = (formal_library_root or
                (self.formal_config or {}).get("_root") or
                Path(__file__).with_name("strategy_library_data"))
        self.formal_library = RuntimeStrategyLibrary(root)
        preflop_path = Path(preflop_config_path or
                            Path(__file__).with_name("strategy_library_preflop.json"))
        try:
            self.preflop_config = load_config(preflop_path)
        except (OSError, ValueError, KeyError):
            self.preflop_config = None
        preflop_root = (preflop_library_root or
                        (self.preflop_config or {}).get("_root") or
                        Path(__file__).with_name("strategy_library_preflop_data"))
        self.preflop_library = RuntimeStrategyLibrary(preflop_root)

    def match(self, state):
        best = None
        for item in self.library:
            score = sum(item.get(key) == state.get(key) for key in ("street", "players", "texture", "position", "facing")) / 5
            if best is None or score > best[0]:
                best = (score, item)
        if best and best[0] >= .8:
            return {**best[1]["strategy"], "source": "预计算策略", "match": best[0]}
        return None

    def match_formal(self, request):
        if not isinstance(request, dict):
            return self._formal_miss("invalid_request")
        scene_key = request.get("sceneKey")
        if scene_key is None:
            scene_key, reason = self._scene_key(request)
            if scene_key is None:
                return self._formal_miss(reason)
        street = request.get("street") or scene_key.get("board", {}).get("street")
        library = (self.preflop_library if street == "preflop"
                   else self.formal_library)
        lookup = library.lookup(scene_key)
        if not lookup.get("hit"):
            miss = self._formal_miss(
                lookup.get("reason", "library_lookup_failed"), library=library)
            miss["sceneKey"] = scene_key
            return miss
        hand = "".join(request.get("heroCards") or ())
        if street != "preflop":
            hand = self._canonical_postflop_hand(
                request.get("boardCards") or scene_key.get("board", {}).get("representative"),
                scene_key.get("board", {}).get("representative"),
                request.get("heroCards"),
            )
            if hand is None:
                return self._formal_miss(
                    "board_suit_mapping_failed", lookup.get("release_version"), library)
        strategy = self._hand_strategy(lookup["result"], hand)
        if strategy is None:
            return self._formal_miss("hand_not_found", lookup.get("release_version"), library)
        action_definitions = {
            item.get("id"): item for item in scene_key.get("legal_actions", [])
            if isinstance(item, dict) and item.get("id")}
        evs = strategy.get("ev") if isinstance(strategy.get("ev"), dict) else {}
        candidates = []
        for action_id, frequency in (strategy.get("actions") or {}).items():
            definition = action_definitions.get(action_id)
            if (not isinstance(definition, dict) or
                    not isinstance(frequency, (int, float)) or frequency <= 0):
                continue
            candidates.append({
                "id": action_id,
                "kind": definition.get("kind"),
                "amount": definition.get("amount"),
                "frequency": float(frequency),
                "ev": evs.get(action_id),
            })
        if not candidates:
            return self._formal_miss("hand_has_no_positive_frequency_actions",
                                     lookup.get("release_version"), library)
        return {
            "hit": True,
            "source": lookup["source"],
            "releaseVersion": lookup["release_version"],
            "sceneHash": lookup["scene_hash"],
            "sceneKey": scene_key,
            "candidates": sorted(candidates, key=lambda item: item["frequency"],
                                 reverse=True),
            "missReason": None,
            "baselineOnly": True,
        }

    def _formal_miss(self, reason, version=None, library=None):
        if version is None:
            try:
                version = ((library or self.formal_library).root / "CURRENT").read_text(
                    encoding="utf-8").strip() or None
            except OSError:
                version = None
        return {"hit": False, "source": "formal_strategy_library",
                "releaseVersion": version, "candidates": [],
                "missReason": reason, "baselineOnly": True}

    @staticmethod
    def _hand_strategy(result, hand):
        if len(hand) != 4:
            return None
        reverse = hand[2:] + hand[:2]
        for node in result.get("nodes", []):
            if not isinstance(node, dict):
                continue
            for strategy in node.get("strategies", []):
                if (isinstance(strategy, dict) and
                        strategy.get("hand") in {hand, reverse}):
                    return strategy
        return None

    @staticmethod
    def _canonical_postflop_hand(board, representative, hand):
        if (not isinstance(board, list) or not isinstance(representative, list) or
                not isinstance(hand, list) or len(board) != len(representative) or
                len(hand) != 2):
            return None
        suits = "cdhs"
        target = set(representative)
        for mapped_suits in itertools.permutations(suits):
            mapping = dict(zip(suits, mapped_suits))
            mapped_board = {card[0] + mapping[card[1]] for card in board}
            if mapped_board == target:
                return "".join(card[0] + mapping[card[1]] for card in hand)
        return None

    def _scene_key(self, request):
        config = (self.preflop_config if request.get("street") == "preflop"
                  else self.formal_config)
        if not config:
            return None, "formal_config_invalid"
        generator = config.get("scenario_generator", {})
        stack_bb = request.get("effectiveStackBb")
        configured_scenes = generator.get("scenes")
        declared = ([item for item in configured_scenes if item.get("enabled", True)]
                    if configured_scenes is not None else [
                        {"position": position, "pot": pot}
                        for position in generator.get("positions", [])
                        for pot in generator.get("pot_types", [])
                    ])
        matching = [item for item in declared
                    if item.get("position") == request.get("positions") and
                    self._pot_matches(item.get("pot", {}), request)]
        if not matching:
            return None, "preflop_action_chain_not_configured"
        if len(matching) != 1:
            return None, "ambiguous_scene_mapping"
        position, pot = matching[0]["position"], matching[0]["pot"]
        allowed_stacks = pot.get("stack_bucket_ids")
        stacks = [item for item in generator.get("stack_buckets", [])
                  if isinstance(stack_bb, (int, float)) and
                  item.get("min_bb") <= stack_bb <= item.get("max_bb") and
                  (not allowed_stacks or item.get("id") in allowed_stacks)]
        if not stacks:
            return None, "effective_stack_out_of_range"
        stack = max(stacks, key=lambda item: (item.get("min_bb"), -item.get("max_bb")))
        board = self._board_class(generator.get("board_classes", []),
                                  request.get("boardCards"), request.get("street"))
        if board is None or board.get("street") != request.get("street"):
            return None, "board_class_not_configured"
        rake = None
        if request.get("street") != "preflop":
            from table_info_parser import rake_strategy_policies
            actual_rate = request.get("rakePercent")
            actual_cap = request.get("rakeCapBb")
            if not isinstance(actual_rate, (int, float)) or not isinstance(actual_cap, (int, float)):
                return None, "game_parameters_mismatch"
            rake = next((item for item in rake_strategy_policies()
                         if math.isclose(float(actual_rate), item["percent"],
                                         rel_tol=0, abs_tol=1e-12) and
                         math.isclose(float(actual_cap), item["cap_bb"],
                                         rel_tol=0, abs_tol=1e-9)), None)
            if rake is None:
                return None, "game_parameters_mismatch"
        scene = build_scene_key(config, position, stack, pot, board, rake)
        if request.get("players") != scene["game"]["players"]:
            return None, "player_count_not_configured"
        if not self._matches_game(request, scene):
            return None, "game_parameters_mismatch"
        return scene, None

    @staticmethod
    def _matches_game(request, scene):
        forced = scene.get("forced_bets", {})
        rake = scene.get("rake", {})
        checks = (
            (request.get("smallBlindBb"), forced.get("small_blind_bb")),
            (request.get("bigBlindBb"), forced.get("big_blind_bb")),
            (request.get("straddleBb"), forced.get("straddle_bb")),
            (request.get("rakePercent"), rake.get("percent")),
            (request.get("rakeCapBb"), rake.get("cap_bb")),
        )
        return all(isinstance(actual, (int, float)) and
                   isinstance(expected, (int, float)) and
                   math.isclose(float(actual), float(expected), rel_tol=0, abs_tol=1e-9)
                   for actual, expected in checks)

    @staticmethod
    def _pot_matches(item, request):
        chain = request.get("preflopActionChain")
        if not isinstance(chain, list) or not all(isinstance(item, str) for item in chain):
            return False
        if chain != item.get("prior_chain"):
            return False
        mapping = {
            "pot_bb": "potBb",
            "hero_contributed_bb": "heroContributedBb",
            "opponent_contributed_bb": "opponentContributedBb",
            "current_price_bb": "currentPriceBb",
            "call_amount_bb": "callAmountBb",
        }
        for configured, requested in mapping.items():
            if configured not in item:
                continue
            value = request.get(requested)
            if (not isinstance(value, (int, float)) or
                    not math.isclose(float(value), float(item[configured]),
                                     rel_tol=0, abs_tol=1e-9)):
                return False
        return True

    @staticmethod
    def _board_class(board_classes, cards, street=None):
        if street == "preflop" and cards == []:
            return next((item for item in board_classes
                         if item.get("street") == "preflop" and
                         item.get("representative") == []), None)
        if not isinstance(cards, list) or len(cards) != 3:
            return None
        values = "23456789TJQKA"
        try:
            ranks = sorted(values.index(card[0]) + 2 for card in cards)
            suits = [card[1] for card in cards]
        except (IndexError, ValueError, TypeError):
            return None
        rainbow = len(set(suits)) == 3
        two_tone = len(set(suits)) == 2
        unpaired = len(set(ranks)) == 3
        connected = max(ranks) - min(ranks) <= 4
        for item in board_classes:
            name = item.get("class", "")
            representative = item.get("representative", [])
            representative_ranks = sorted(
                values.index(card[0]) + 2 for card in representative)
            if ranks != representative_ranks:
                continue
            if (name == "ace-high-rainbow-dry" and max(ranks) == 14 and
                    rainbow and unpaired and not connected):
                return item
            if (name == "king-high-rainbow-dry" and max(ranks) == 13 and
                    rainbow and unpaired and not connected):
                return item
            if name == "connected-two-tone" and two_tone and unpaired and connected:
                return item
        return None

    def enqueue(self, hand):
        record = {"createdAt": time.time(), "status": "pending", "hand": hand}
        with self.queue_file.open("a", encoding="utf-8") as target:
            target.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def solver_status(self):
        executable = shutil.which("TexasSolverConsole.exe") or shutil.which("TexasSolver.exe")
        return {"available": bool(executable), "path": executable, "queued": sum(1 for _ in self.queue_file.open(encoding="utf-8")) if self.queue_file.exists() else 0}

    @staticmethod
    def _load(path, fallback):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return fallback
