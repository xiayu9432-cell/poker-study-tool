import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path


class HistoryStore:
    STATISTICS_VERSION = 2
    REACTION_MODEL_VERSION = 3
    REACTION_SAMPLE_LIMIT = 1000
    EVENT_LOG_MAX_BYTES = 50 * 1024 * 1024
    EVENT_LOG_BACKUP_COUNT = 10
    REACTION_WEIGHTS = ((60, .8, "60+"), (30, .6, "30-59"),
                        (15, .35, "15-29"), (5, .15, "5-14"),
                        (0, 0.0, "0-4"))
    COUNT_FIELDS = (
        "hands", "preflopOpportunities", "vpipHands", "pfrHands", "actions",
        "calls", "raises", "bets", "folds", "checks", "reraises",
        "facingBetOpportunities", "foldsFacingBet", "postflopCalls",
        "postflopBets", "postflopRaises", "preflopFacingRaiseOpportunities",
        "preflopFoldsFacingRaise", "preflopCallsFacingRaise", "preflopReraisesFacingRaise",
        "flopFacingBetOpportunities", "flopFoldsFacingBet",
        "turnFacingBetOpportunities", "turnFoldsFacingBet",
        "riverFacingBetOpportunities", "riverFoldsFacingBet",
    )

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.events_file = self.data_dir / "hand_history.jsonl"
        self.profiles_file = self.data_dir / "opponent_profiles.json"
        self.profile_calibration_file = (self.data_dir / "profile-calibration" /
                                         "profile-calibration.json")
        self.profiles = self._load_profiles()
        self.profile_calibrations = self._load_profile_calibrations()
        self.session_id = uuid.uuid4().hex[:12]
        self.lock = threading.RLock()
        self.last_signature = None
        self.boundary_hands = set()
        self.hand_profiles = set()
        self.counted_hand_profiles = set()
        self.counted_action_events = set()
        self.counted_decision_samples = set()
        self.session_identities = {}
        self.session_avatar_identities = {}
        self.session_hands_by_seat = {}
        self.hand_dealers = {}
        self.hand_action_contexts = {}
        self._event_count = self._count_existing_events()
        self._reaction_pool_version = 0
        self._reaction_pool_cache = None
        self._migrate_profiles()
        self._remove_invalid_revealed_samples()

    def observe_boundary(self, hand_id, dealer_index, seats=()):
        hand_key = f"{self.session_id}-{hand_id}"
        self.hand_dealers[hand_key] = dealer_index
        if hand_key in self.boundary_hands:
            return
        self._append({
            "type": "hand_boundary", "time": time.time(), "handKey": hand_key,
            "newHand": True, "street": "preflop", "dealerIndex": dealer_index,
            "board": [], "heroCards": [],
            "seats": [{key: seat.get(key) for key in
                       ("index", "name", "chips", "empty", "avatarHash")}
                      for seat in seats],
        })
        self.boundary_hands.add(hand_key)

    def observe(self, hand, seats, events, pot, board, hero_cards):
        hand_key = f"{self.session_id}-{hand['id']}"
        if isinstance(hand.get("dealerIndex"), int):
            self.hand_dealers[hand_key] = hand["dealerIndex"]
        self._enrich_action_context(hand, seats, events, pot, board)
        current_events = [event for event in events
                          if event.get("handId", hand["id"]) == hand["id"]]
        late_events = {}
        for event in events:
            event_hand_id = event.get("handId", hand["id"])
            if event_hand_id != hand["id"]:
                late_events.setdefault(event_hand_id, []).append(event)
        for event_hand_id, grouped_events in late_events.items():
            self._append({
                "type": "late_actions", "time": time.time(),
                "handKey": f"{self.session_id}-{event_hand_id}",
                "events": grouped_events,
            })
        snapshot = {
            "type": "snapshot", "time": time.time(), "handKey": hand_key,
            "newHand": hand["newHand"], "street": hand["street"], "pot": pot,
            "heroPosition": hand.get("heroPosition", "unknown"),
            "board": board, "heroCards": hero_cards,
            "seats": [{key: seat.get(key) for key in ("index", "name", "chips", "streetBet", "action", "empty", "avatarHash")} for seat in seats],
            "events": current_events,
        }
        signature = json.dumps({key: snapshot[key] for key in ("handKey", "street", "pot", "board", "heroCards", "seats", "events")}, ensure_ascii=False, sort_keys=True)
        if signature != self.last_signature:
            self._append(snapshot)
            self.last_signature = signature
        counted = False
        for seat in seats if hand.get("id", 0) > 0 else []:
            if seat.get("occupancy") == "occupied":
                self.session_hands_by_seat.setdefault(seat.get("index"), set()).add(hand_key)
            key = self._profile_key(seat, seats)
            if not key:
                continue
            profile = self._profile(key, seat)
            for observed_hand_key in self.session_hands_by_seat.get(seat.get("index"), {hand_key}):
                count_key = (observed_hand_key, key)
                if count_key not in self.counted_hand_profiles:
                    profile["hands"] += 1
                    profile["preflopOpportunities"] += 1
                    self.counted_hand_profiles.add(count_key)
                    counted = True
        changed = False
        for event in events:
            current_seat = next((item for item in seats if item["index"] + 1 == event["seat"]), None)
            seat = dict(current_seat or {"index": event["seat"] - 1})
            if event.get("name"):
                seat["name"] = event["name"]
            if event.get("avatarHash"):
                seat["avatarHash"] = event["avatarHash"]
            key = self._profile_key(seat, seats) if seat else None
            if not key:
                continue
            profile = self._profile(key, seat)
            action = event["action"]
            event_street = event.get("street", hand["street"])
            event_hand_key = f"{self.session_id}-{event.get('handId', hand['id'])}"
            count_key = (event_hand_key, key)
            if count_key not in self.counted_hand_profiles:
                profile["hands"] += 1
                profile["preflopOpportunities"] += 1
                self.counted_hand_profiles.add(count_key)
                counted = True
            event_key = (event_hand_key, event_street, event.get("sequence"), event.get("seat"),
                         action, event.get("amount"), event.get("increase"))
            if event_key in self.counted_action_events:
                continue
            self.counted_action_events.add(event_key)
            profile["actions"] += 1
            profile[action + "s"] = profile.get(action + "s", 0) + 1
            if event_street == "preflop" and action in ("call", "raise", "bet"):
                flag = (event_hand_key, key, "vpip")
                if flag not in self.hand_profiles:
                    profile["vpipHands"] += 1; self.hand_profiles.add(flag)
            if event_street == "preflop" and action in ("raise", "bet"):
                flag = (event_hand_key, key, "pfr")
                if flag not in self.hand_profiles:
                    profile["pfrHands"] += 1; self.hand_profiles.add(flag)
            if event_street != "preflop":
                if action == "call": profile["postflopCalls"] += 1
                if action == "bet": profile["postflopBets"] += 1
                if action in ("raise", "reraise"): profile["postflopRaises"] += 1
            prior_bet = any(item.get("sequence", 0) < event.get("sequence", 0) and item.get("street") == event.get("street") and item.get("action") in ("bet", "raise", "reraise") for item in events)
            if prior_bet and action in ("call", "raise", "reraise", "fold"):
                profile["facingBetOpportunities"] += 1
                if action == "fold": profile["foldsFacingBet"] += 1
                if event_street == "preflop":
                    profile["preflopFacingRaiseOpportunities"] += 1
                    if action == "fold": profile["preflopFoldsFacingRaise"] += 1
                    if action == "call": profile["preflopCallsFacingRaise"] += 1
                    if action in ("raise", "reraise"): profile["preflopReraisesFacingRaise"] += 1
                elif event_street in ("flop", "turn", "river"):
                    prefix = event_street
                    profile[f"{prefix}FacingBetOpportunities"] += 1
                    if action == "fold": profile[f"{prefix}FoldsFacingBet"] += 1
            changed = True
        if self._observe_decision_samples(hand, seats, events, pot, board):
            changed = True
        if hand["newHand"] or counted or changed:
            self._save_profiles()

    def summaries(self, seats):
        result = {}
        with self.lock:
            for seat in seats:
                key = self._readonly_profile_key(seat)
                profile = self.profiles.get(key)
                if profile:
                    result[str(seat["index"])] = self._profile_summary(
                        profile, self._calibration_for_profile(key, profile))
        return result

    @classmethod
    def _is_abbreviated_name(cls, observed, canonical):
        raw = str(observed or "").strip()
        if not re.search(r"(?:\.{2,}|…)$", raw):
            return False
        short = cls._normalized_name(raw)
        full = cls._normalized_name(canonical)
        return len(short) >= 2 and len(full) > len(short) and full.startswith(short)

    def observe_platform_statistics(self, seat, statistics, source="manual_profile_popup"):
        name = str(statistics.get("name") or seat.get("name") or "").strip()
        level_hands = int(statistics.get("levelHands", -1))
        total_hands = int(statistics.get("totalHands", -1))
        vpip_rate = float(statistics.get("vpipRate", -1))
        pfr_rate = float(statistics.get("pfrRate", -1))
        if (not name or level_hands < 0 or total_hands < level_hands or
                not 0 <= vpip_rate <= 1 or not 0 <= pfr_rate <= vpip_rate):
            raise ValueError("invalid platform player statistics")
        identified_seat = dict(seat, name=name)
        canonical_key = f"name:{self._normalized_name(name)}"
        current = self.session_identities.get(seat.get("index"))
        manual = bool(seat.get("profileManualConfirmed"))
        observed_name = self._normalized_name(seat.get("name"))
        confirmed_prefix = bool(seat.get("profilePrefixConfirmed")) and (
            len(observed_name) >= 2 and len(name) > len(observed_name) and
            self._normalized_name(name).startswith(observed_name))
        abbreviated = self._is_abbreviated_name(seat.get("name"), name) or confirmed_prefix
        if current and (manual or abbreviated or (
                seat.get("avatarHash") and current.get("avatarHash") == seat.get("avatarHash"))):
            self._promote_profile(current["key"], canonical_key, identified_seat)
            current.update(key=canonical_key, name=name,
                           avatarHash=seat.get("avatarHash") or current.get("avatarHash", ""))
            key = canonical_key
        else:
            abbreviated_key = f"name:{self._normalized_name(seat.get('name'))}"
            if abbreviated and abbreviated_key in self.profiles:
                self._promote_profile(abbreviated_key, canonical_key, identified_seat)
            key = self._profile_key(identified_seat)
        if not key:
            raise ValueError("platform statistics cannot be bound to this player")
        captured_at = float(statistics.get("capturedAt") or time.time())
        snapshot = {
            "levelHands": level_hands,
            "totalHands": total_hands,
            "vpipRate": vpip_rate,
            "pfrRate": pfr_rate,
            "capturedAt": captured_at,
            "source": source,
            "rateDenominatorAssumption": statistics.get(
                "rateDenominatorAssumption", "levelHands"),
        }
        with self.lock:
            profile = self._profile(key, identified_seat)
            if confirmed_prefix:
                aliases = profile.setdefault("confirmedNameAliases", [])
                if observed_name not in aliases:
                    aliases.append(observed_name)
            profile["platformStatistics"] = snapshot
            history = profile.setdefault("platformStatisticsHistory", [])
            if not history or any(history[-1].get(field) != snapshot[field]
                                  for field in ("levelHands", "totalHands",
                                                "vpipRate", "pfrRate")):
                history.append(snapshot)
                del history[:-20]
            self._append({"type": "platform_player_statistics", "time": captured_at,
                          "profileKey": key, "name": name, **snapshot})
            self._save_profiles()
        return {"profileKey": key, "name": name, **snapshot}

    def status(self):
        with self.lock:
            return {"events": self._event_count, "profiles": len(self.profiles)}

    def observe_revealed_cards(self, hand_id, revealed_cards, source):
        hand_key = f"{self.session_id}-{hand_id}"
        accepted = []
        for item in revealed_cards:
            seat = {"index": int(item.get("seat", 0)) - 1, "name": item.get("name", "")}
            cards = list(item.get("cards") or [])
            key = self._profile_key(seat)
            if not key or len(cards) != 2 or len(set(cards)) != 2:
                continue
            profile = self._profile(key, seat)
            samples = profile.setdefault("revealedCardSamples", [])
            if not any(sample.get("handKey") == hand_key for sample in samples):
                samples.append({"handKey": hand_key, "cards": cards, "source": source})
                del samples[:-200]
            profile["revealedHands"] = len(samples)
            for sample in profile.get("decisionSamples", []):
                if sample.get("handKey") == hand_key:
                    sample["verifiedHoleCards"] = cards
                    sample["revealSource"] = source
            accepted.append({"seat": item.get("seat"), "name": item.get("name", ""),
                             "cards": cards})
        if accepted:
            self._append({"type": "revealed_cards", "time": time.time(), "handKey": hand_key,
                          "source": source, "players": accepted})
            self._save_profiles()
        return bool(accepted)

    def record_decision_opportunity(self, hand_id, seat, action, *, street,
                                    player_count=None, position=None, prior_actions=(),
                                    board=(), effective_stack=None, big_blind=None,
                                    bet_pot_ratio=None, verified_cards=None,
                                    reveal_source=None, seats=(), facing_action=None,
                                    facing_amount=None, facing_increase=None,
                                    facing_pot=None, action_sequence=None):
        """Record one confirmed choice. Unknown context stays null; it is never guessed."""
        key = self._profile_key(seat, seats)
        if not key or action not in ("fold", "check", "call", "bet", "raise", "reraise", "allin"):
            return False
        hand_key = f"{self.session_id}-{hand_id}"
        context = self._decision_context(
            street=street, player_count=player_count, position=position,
            prior_actions=prior_actions, board=board, effective_stack=effective_stack,
            big_blind=big_blind, bet_pot_ratio=bet_pot_ratio,
            facing_action=facing_action, facing_amount=facing_amount,
            facing_increase=facing_increase, facing_pot=facing_pot,
            action_sequence=action_sequence,
        )
        signature = (hand_key, int(seat.get("index", -1)), action,
                     json.dumps(context, ensure_ascii=False, sort_keys=True))
        if signature in self.counted_decision_samples:
            return False
        self.counted_decision_samples.add(signature)
        sample = {"handKey": hand_key, **context, "action": action,
                  "recordedAt": time.time()}
        cards = list(verified_cards or [])
        if len(cards) == 2 and len(set(cards)) == 2 and reveal_source:
            sample.update(verifiedHoleCards=cards, revealSource=reveal_source)
        profile = self._profile(key, seat)
        samples = profile.setdefault("decisionSamples", [])
        samples.append(sample)
        del samples[:-self.REACTION_SAMPLE_LIMIT]
        profile["reactionModelVersion"] = self.REACTION_MODEL_VERSION
        self._append({"type": "decision_opportunity", "time": time.time(),
                      "profileKey": key, **sample})
        self._save_profiles()
        return True

    def estimate_reaction(self, seat_or_key, context, seats=()):
        """Return a population-shrunk action distribution for a comparable context."""
        del seats
        key = (self._readonly_profile_key(seat_or_key) if isinstance(seat_or_key, dict)
               else str(seat_or_key or ""))
        normalized = self._normalize_reaction_context(context)
        personal_pool, population_pool = self._reaction_pools(key, normalized)
        personal, population, match_tier, fallback_level = self._matched_reaction_samples(
            personal_pool, population_pool, normalized)
        broad_population = [sample for sample in population_pool
                            if self._population_prior_matches(sample, normalized)]
        if len(population) < 5 and broad_population:
            population = broad_population
            match_tier, fallback_level = "street_facing_population", 4
        estimate = self._reaction_estimate(personal, population, normalized)
        estimate.update(matchTier=match_tier, fallbackLevel=fallback_level,
                        evidenceAvailable=bool(population))
        return estimate

    @classmethod
    def _reaction_index_key(cls, context):
        facing = cls._effective_facing_action(context)
        return (str(context.get("street") or "unknown"),
                None if facing in (None, "unknown") else facing)

    def _reaction_pools(self, key, normalized=None):
        with self.lock:
            cached = self._reaction_pool_cache
            if not cached or cached[0] != self._reaction_pool_version:
                by_key = {
                    profile_key: tuple(dict(sample) for sample in
                                       profile.get("decisionSamples", ()))
                    for profile_key, profile in self.profiles.items()
                }
                population = tuple(sample for samples in by_key.values()
                                   for sample in samples)
                by_key_index = {
                    profile_key: self._index_reaction_samples(samples)
                    for profile_key, samples in by_key.items()
                }
                population_index = self._index_reaction_samples(population)
                cached = (self._reaction_pool_version, by_key, population,
                          by_key_index, population_index)
                self._reaction_pool_cache = cached
            if normalized is None:
                return cached[1].get(key, ()), cached[2]
            index_key = self._reaction_index_key(normalized)
            return (cached[3].get(key, {}).get(index_key, ()),
                    cached[4].get(index_key, ()))

    @classmethod
    def _index_reaction_samples(cls, samples):
        index = {}
        for sample in samples:
            index.setdefault(cls._reaction_index_key(sample), []).append(sample)
        return {key: tuple(items) for key, items in index.items()}

    @classmethod
    def _matched_reaction_samples(cls, personal, population, target):
        tiers = ("exact", "near_amount", "same_position_pool", "table_population")
        personal_levels = [(sample, cls._reaction_match_level(sample, target))
                           for sample in personal]
        population_levels = [(sample, cls._reaction_match_level(sample, target))
                             for sample in population]
        selected = ([], [], "unavailable", None)
        for level, tier in enumerate(tiers):
            personal_matches = [sample for sample, match_level in personal_levels
                                if match_level <= level]
            population_matches = [sample for sample, match_level in population_levels
                                  if match_level <= level]
            selected = (personal_matches, population_matches, tier, level)
            if len(population_matches) >= 5:
                break
        return selected

    @classmethod
    def _reaction_match_level(cls, sample, target):
        if cls._context_matches(sample, target):
            return 0
        if sample.get("street") != target.get("street"):
            return 99
        if (target.get("boardClass") not in (None, "unknown") and
                sample.get("boardClass") != target.get("boardClass")):
            return 99
        target_facing = cls._effective_facing_action(target)
        sample_facing = cls._effective_facing_action(sample)
        if (target_facing not in (None, "unknown") and
                sample_facing != target_facing):
            return 99
        player_distance = cls._numeric_distance(sample.get("playerCount"),
                                                target.get("playerCount"))
        ratio_distance = cls._numeric_distance(sample.get("betPotRatio"),
                                               target.get("betPotRatio"))
        stack_distance = cls._numeric_distance(sample.get("effectiveStackBb"),
                                               target.get("effectiveStackBb"))
        same_position = (target.get("position") in (None, "unknown") or
                         sample.get("position") == target.get("position"))
        if (same_position and player_distance <= 1 and ratio_distance <= .35 and
                stack_distance <= 30):
            return 1
        if same_position and player_distance <= 1 and ratio_distance <= .5:
            return 2
        if player_distance <= 1 and (ratio_distance <= .5 or
                                     sample.get("betPotRatio") is None):
            return 3
        return 99

    @staticmethod
    def _effective_facing_action(context):
        explicit = context.get("facingAction")
        if explicit:
            return "raise" if explicit == "reraise" else explicit
        for action in reversed(context.get("priorActions") or []):
            if action in ("raise", "reraise"):
                return "raise"
            if action in ("bet", "allin"):
                return action
        return None

    @classmethod
    def _population_prior_matches(cls, sample, target):
        if sample.get("street") != target.get("street"):
            return False
        target_facing = cls._effective_facing_action(target)
        if target_facing not in (None, "unknown"):
            return cls._effective_facing_action(sample) == target_facing
        return cls._effective_facing_action(sample) in (None, "unknown")

    @staticmethod
    def _numeric_distance(actual, expected):
        if expected is None:
            return 0.0
        if not isinstance(actual, (int, float)):
            return float("inf")
        return abs(float(actual) - float(expected))

    def estimate_table_reactions(self, seats, context, acting_order=None):
        """Return compact reaction estimates for active opponents in acting order."""
        ordered = self._ordered_active_opponents(seats, acting_order)
        result = {}
        for seat in ordered:
            estimate = self.estimate_reaction(seat, context)
            result[str(seat["index"])] = {
                "seat": seat["index"] + 1,
                "name": seat.get("name", ""),
                **self._compact_reaction(estimate),
            }
        return result

    def estimate_ordered_reaction(self, seats, acting_order, context,
                                  aggressor_action, bet_pot_ratio,
                                  include_paths=False):
        """Aggregate sequential opponent responses without assuming independence."""
        ordered = self._ordered_active_opponents(seats, acting_order)
        base = dict(context or {})
        prior = list(base.get("prior_actions", base.get("priorActions", ())) or ())
        prior_types = [str(item.get("action")) if isinstance(item, dict)
                       else str(item) for item in prior]
        proposed_action = str(aggressor_action or "")
        if (proposed_action == "raise" and
                str(base.get("street") or "unknown") in ("flop", "turn", "river") and
                not any(action in ("bet", "raise", "reraise", "allin")
                        for action in prior_types)):
            proposed_action = "bet"
        if proposed_action:
            prior.append(proposed_action)
        base["bet_pot_ratio"] = bet_pot_ratio
        base.pop("betPotRatio", None)
        if proposed_action:
            base["facing_action"] = proposed_action
            base.pop("facingAction", None)
        paths = [(1.0, prior, "fold", 0, [])]
        min_personal = None
        min_population = None
        fallback_level = 0
        match_tiers = set()
        for seat in ordered:
            next_paths = []
            for path_probability, path_actions, outcome, call_count, responses in paths:
                if outcome == "raise":
                    next_paths.append((path_probability, path_actions,
                                       outcome, call_count, responses))
                    continue
                branch_context = dict(
                    base, prior_actions=path_actions,
                    position=seat.get("position") or base.get("position"),
                )
                estimate = self.estimate_reaction(seat, branch_context)
                fallback_level = max(fallback_level,
                                     int(estimate.get("fallbackLevel") or 0))
                if estimate.get("matchTier"):
                    match_tiers.add(estimate["matchTier"])
                min_personal = self._minimum(min_personal, estimate["sampleCount"])
                min_population = self._minimum(
                    min_population, estimate["populationSampleCount"])
                for action, probability in self._three_action_probabilities(estimate).items():
                    if probability <= 0:
                        continue
                    next_outcome = ("raise" if action == "raise" or outcome == "raise"
                                    else "call" if action == "call" or outcome == "call"
                                    else "fold")
                    next_paths.append((path_probability * probability,
                                        path_actions + [action], next_outcome,
                                        call_count + (1 if action == "call" else 0),
                                        responses + [{"seat": seat["index"] + 1,
                                                      "action": action}]))
            paths = next_paths
        probabilities = {action: 0.0 for action in ("fold", "call", "raise")}
        call_counts = {}
        for probability, _, outcome, call_count, _ in paths:
            probabilities[outcome] += probability
            if outcome == "call":
                call_counts[call_count] = call_counts.get(call_count, 0.0) + probability
        total = sum(probabilities.values())
        if total:
            probabilities = {action: round(value / total, 6)
                             for action, value in probabilities.items()}
        call_probability = sum(call_counts.values())
        call_count_distribution = (
            {str(count): round(probability / call_probability, 6)
             for count, probability in sorted(call_counts.items())}
            if call_probability else {}
        )
        expected_callers = (sum(count * probability
                                for count, probability in call_counts.items()) /
                            call_probability if call_probability else 0.0)
        minimum_population = min_population or 0
        result = {
            "probabilities": probabilities,
            "callCountDistribution": call_count_distribution,
            "expectedCallers": round(expected_callers, 6),
            "minPersonalSamples": min_personal or 0,
            "minPopulationSamples": minimum_population,
            "orderedSeats": [seat["index"] + 1 for seat in ordered],
            "sequential": True,
            "facingAction": proposed_action or None,
            "reliable": (bool(ordered) and minimum_population >= 30 and
                         fallback_level <= 1),
            "sampleTier": self._reaction_weight(
                max(min_personal or 0, minimum_population))[1],
        }
        if match_tiers:
            result.update(
                matchTier=(next(iter(match_tiers)) if len(match_tiers) == 1
                           else "mixed:" + ",".join(sorted(match_tiers))),
                fallbackLevel=fallback_level,
            )
        if include_paths:
            compact = sorted(paths, key=lambda item: item[0], reverse=True)[:64]
            retained = sum(item[0] for item in compact)
            result["paths"] = [
                {"probability": round(probability, 8), "outcome": outcome,
                 "callers": call_count, "responses": responses}
                for probability, _, outcome, call_count, responses in compact
            ]
            result["retainedPathProbability"] = round(retained, 8)
            result["prunedPathProbability"] = round(max(0.0, total - retained), 8)
        return result

    @classmethod
    def _reaction_estimate(cls, personal, population, normalized):
        actions = ("fold", "check", "call", "bet", "raise", "reraise", "allin")
        population_counts = {action: sum(item.get("action") == action for item in population)
                             for action in actions}
        personal_counts = {action: sum(item.get("action") == action for item in personal)
                           for action in actions}
        population_total = len(population)
        personal_total = len(personal)
        weight, tier = cls._reaction_weight(personal_total)
        fallback = 0.0
        probabilities = {}
        for action in actions:
            population_rate = (population_counts[action] / population_total
                               if population_total else fallback)
            personal_rate = (personal_counts[action] / personal_total
                             if personal_total else population_rate)
            probabilities[action] = round((1 - weight) * population_rate +
                                          weight * personal_rate, 4)
        return {"sampleCount": personal_total, "sampleTier": tier,
                "personalWeight": weight, "populationSampleCount": population_total,
                "probabilities": probabilities, "context": normalized,
                "verifiedShowdownSamples": sum(bool(item.get("verifiedHoleCards"))
                                                 for item in personal)}

    @staticmethod
    def _compact_reaction(estimate):
        return {key: estimate[key] for key in (
            "sampleCount", "sampleTier", "personalWeight",
            "populationSampleCount", "probabilities",
        )}

    @staticmethod
    def _three_action_probabilities(estimate):
        values = estimate["probabilities"]
        result = {
            "fold": values.get("fold", 0.0),
            "call": values.get("check", 0.0) + values.get("call", 0.0),
            "raise": sum(values.get(action, 0.0)
                         for action in ("bet", "raise", "reraise", "allin")),
        }
        total = sum(result.values())
        return ({action: value / total for action, value in result.items()}
                if total else {action: 0.0 for action in result})

    @staticmethod
    def _minimum(current, value):
        return value if current is None else min(current, value)

    @classmethod
    def _normalize_reaction_context(cls, context):
        context = dict(context or {})
        if any(key in context for key in ("playerCount", "priorActions",
                                           "effectiveStackBb", "betPotRatio")):
            return {
                "street": str(context.get("street") or "unknown"),
                "playerCount": context.get("playerCount"),
                "position": str(context.get("position") or "unknown"),
                "priorActions": list(context.get("priorActions") or ()),
                "board": list(context.get("board") or ()),
                "boardClass": context.get("boardClass") or cls._board_class(context.get("board")),
                "effectiveStackBb": context.get("effectiveStackBb"),
                "betPotRatio": context.get("betPotRatio"),
                "facingAction": context.get("facingAction"),
                "facingAmount": context.get("facingAmount"),
                "facingIncrease": context.get("facingIncrease"),
                "facingPot": context.get("facingPot"),
                "actionSequence": context.get("actionSequence"),
            }
        return cls._decision_context(**context)

    def _readonly_profile_key(self, seat):
        if not seat:
            return None
        name = self._normalized_name(seat.get("name"))
        if seat.get("isHero") or name == "zixia888":
            return None
        current = self.session_identities.get(seat.get("index"))
        if self._is_placeholder_name(name):
            if not current:
                key = f"session:{self.session_id}:seat{seat.get('index')}:placeholder"
                if key in self.profiles:
                    current = {"key": key, "name": "", "avatarHash": ""}
                    self.session_identities[seat.get("index")] = current
            return current.get("key") if current else None
        if current and (self._normalized_name(current.get("name")) == name or
                        self._is_abbreviated_name(seat.get("name"), current.get("name")) or
                        (seat.get("avatarHash") and
                         seat.get("avatarHash") == current.get("avatarHash"))):
            return current.get("key")
        aliases = [key for key, profile in self.profiles.items()
                   if name in (profile.get("confirmedNameAliases") or ())]
        if len(aliases) == 1:
            return aliases[0]
        if name and "mvp" not in name:
            return f"name:{name}"
        return current.get("key") if current else None

    @classmethod
    def _profile_summary(cls, profile, calibration=None):
        result = {
            "name": profile.get("name", ""),
            "avatarHash": profile.get("avatarHash", ""),
            "statisticsVersion": profile.get("statisticsVersion", cls.STATISTICS_VERSION),
            "reactionModelVersion": profile.get("reactionModelVersion", cls.REACTION_MODEL_VERSION),
            "revealedHands": int(profile.get("revealedHands", 0) or 0),
            "decisionSampleCount": len(profile.get("decisionSamples", ())),
            "verifiedDecisionSampleCount": sum(
                bool(sample.get("verifiedHoleCards"))
                for sample in profile.get("decisionSamples", ())
            ),
        }
        result.update({field: int(profile.get(field, 0) or 0)
                       for field in cls.COUNT_FIELDS})
        platform = profile.get("platformStatistics") or {}
        if platform:
            result["platformStatistics"] = {
                "levelHands": int(platform.get("levelHands", 0) or 0),
                "totalHands": int(platform.get("totalHands", 0) or 0),
                "vpipRate": float(platform.get("vpipRate", 0) or 0),
                "pfrRate": float(platform.get("pfrRate", 0) or 0),
                "capturedAt": platform.get("capturedAt"),
                "source": platform.get("source"),
                "rateDenominatorAssumption": platform.get(
                    "rateDenominatorAssumption", "levelHands"),
            }
        result["modelEvidence"] = cls._model_evidence(profile)
        result["modelCalibration"] = calibration or {
            "eligibleToAffectAdvice": False,
            "currentEvidence": False,
            "heldOutHands": 0,
            "heldOutDecisions": 0,
            "minimumHands": 30,
            "improved": False,
            "reason": "当前样本尚未完成整手留出校准",
        }
        return result

    @staticmethod
    def _sample_signature(profile):
        samples = list(profile.get("decisionSamples") or ())
        verified = [sample for sample in samples
                    if HistoryStore._combo_class(sample.get("verifiedHoleCards"))]
        unique_hands = len({str(sample.get("handKey") or "") for sample in verified
                            if sample.get("handKey")})
        recorded = [float(sample.get("recordedAt")) for sample in samples
                    if isinstance(sample.get("recordedAt"), (int, float))]
        latest_ms = int(max(recorded) * 1000 + .5) if recorded else 0
        return f"{len(samples)}:{len(verified)}:{unique_hands}:{latest_ms}"

    def _load_profile_calibrations(self):
        try:
            report = json.loads(self.profile_calibration_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return {str(player.get("profileKey")): player
                for player in report.get("players", ()) if player.get("profileKey")}

    def reload_profile_calibrations(self):
        with self.lock:
            self.profile_calibrations = self._load_profile_calibrations()

    def _calibration_for_profile(self, key, profile):
        calibration = dict(self.profile_calibrations.get(str(key)) or {})
        current = bool(calibration and calibration.get("sampleSignature") ==
                       self._sample_signature(profile))
        return {
            "eligibleToAffectAdvice": bool(
                current and calibration.get("eligibleToAffectAdvice") is True),
            "currentEvidence": current,
            "heldOutHands": int(calibration.get("heldOutHands", 0) or 0),
            "heldOutDecisions": int(calibration.get("heldOutDecisions", 0) or 0),
            "minimumHands": int(calibration.get("minimumHands", 30) or 30),
            "improved": bool(calibration.get("improved") is True),
            "reason": (calibration.get("reason") if current else
                       "样本已变化，旧校准自动失效" if calibration else
                       "当前样本尚未完成整手留出校准"),
            "sampleSignature": calibration.get("sampleSignature"),
            "generatedAt": calibration.get("generatedAt"),
        }

    def needs_profile_calibration(self):
        with self.lock:
            for key, profile in self.profiles.items():
                verified_hands = {sample.get("handKey")
                                  for sample in profile.get("decisionSamples", ())
                                  if sample.get("handKey") and
                                  self._combo_class(sample.get("verifiedHoleCards"))}
                if (len(verified_hands) >= 30 and
                        not self._calibration_for_profile(key, profile)["currentEvidence"]):
                    return True
        return False

    @classmethod
    def _model_evidence(cls, profile):
        buckets = {}
        samples = [sample for sample in profile.get("decisionSamples", ())
                   if cls._valid_decision_sample(sample)]
        for sample in samples:
            facing = cls._effective_facing_action(sample)
            ratio = sample.get("betPotRatio")
            stack = sample.get("effectiveStackBb")
            player_count = sample.get("playerCount")
            ratio_bucket = (None if not isinstance(ratio, (int, float)) else
                            int(float(ratio) / .25 + .5) * .25)
            stack_bucket = (None if not isinstance(stack, (int, float)) else
                            min(200, int(float(stack) / 50 + .5) * 50))
            player_bucket = (None if not isinstance(player_count, int) else
                             min(5, max(2, player_count)))
            key = (str(sample.get("street") or "unknown"),
                   facing, str(sample.get("position") or "unknown"),
                   str(sample.get("boardClass") or "unknown"),
                   ratio_bucket, stack_bucket, player_bucket)
            bucket = buckets.setdefault(key, {
                "street": key[0], "facingAction": key[1], "position": key[2],
                "boardClass": key[3], "ratioBucket": key[4],
                "stackBucketBb": key[5], "playerCountBucket": key[6],
                "sampleCount": 0, "verifiedCount": 0,
                "actionCounts": {}, "verifiedClasses": {},
                "matchTier": "personal_scene",
            })
            action = str(sample.get("action") or "")
            if not action:
                continue
            bucket["sampleCount"] += 1
            bucket["actionCounts"][action] = bucket["actionCounts"].get(action, 0) + 1
            cards = list(sample.get("verifiedHoleCards") or ())
            combo_class = cls._combo_class(cards)
            if combo_class:
                bucket["verifiedCount"] += 1
                by_action = bucket["verifiedClasses"].setdefault(action, {})
                by_action[combo_class] = by_action.get(combo_class, 0) + 1
        ordered = sorted(buckets.values(), key=lambda item: (
            -item["sampleCount"], item["street"], str(item["facingAction"]),
            item["position"], item["boardClass"]))[:64]
        verified = sum(bool(sample.get("verifiedHoleCards")) for sample in samples)
        return {
            "modelVersion": 2,
            "nAction": len(samples),
            "nShow": verified,
            "revealedHands": int(profile.get("revealedHands", 0) or 0),
            "buckets": ordered,
            "shadowOnly": True,
        }

    @staticmethod
    def _combo_class(cards):
        if not isinstance(cards, (list, tuple)) or len(cards) != 2:
            return None
        ranks = "23456789TJQKA"
        normalized = []
        for card in cards:
            text = str(card or "")
            if len(text) != 2 or text[0].upper() not in ranks or text[1].lower() not in "shdc":
                return None
            normalized.append(text[0].upper() + text[1].lower())
        if normalized[0] == normalized[1]:
            return None
        normalized.sort(key=lambda card: ranks.index(card[0]), reverse=True)
        if normalized[0][0] == normalized[1][0]:
            return normalized[0][0] + normalized[1][0]
        suffix = "s" if normalized[0][1] == normalized[1][1] else "o"
        return normalized[0][0] + normalized[1][0] + suffix

    def _ordered_active_opponents(self, seats, acting_order):
        active = [seat for seat in seats
                  if not seat.get("isHero")
                  and self._normalized_name(seat.get("name")) != "zixia888"
                  and not seat.get("empty")
                  and seat.get("occupancy", "occupied") == "occupied"
                  and seat.get("action") not in ("fold", "allin", "empty")]
        by_index = {seat.get("index"): seat for seat in active}
        ordered = []
        for index in acting_order or ():
            seat = by_index.pop(index, None)
            if seat is not None:
                ordered.append(seat)
        ordered.extend(sorted(by_index.values(), key=lambda seat: seat.get("index", -1)))
        return ordered

    def _remove_invalid_revealed_samples(self):
        changed = False
        for profile in self.profiles.values():
            samples = profile.get("revealedCardSamples")
            if not isinstance(samples, list):
                continue
            valid = [sample for sample in samples
                     if len(sample.get("cards") or []) == 2 and
                     len(set(sample.get("cards") or [])) == 2]
            if valid != samples:
                profile["revealedCardSamples"] = valid
                profile["revealedHands"] = len(valid)
                changed = True
        if changed:
            self._save_profiles()

    def _observe_decision_samples(self, hand, seats, events, pot, board):
        changed = False
        ordered = sorted((event for event in events
                          if event.get("handId", hand.get("id")) == hand.get("id")),
                         key=lambda event: (event.get("sequence", 0), event.get("observedAt", 0)))
        by_street = {}
        for event in ordered:
            by_street.setdefault(event.get("street", hand.get("street")), []).append(event)
        for street, street_events in by_street.items():
            for index, event in enumerate(street_events):
                if event.get("action") in ("blind", "post_blind", "straddle"):
                    continue
                player = next((item for item in seats if item.get("index") + 1 == event.get("seat")), None)
                if not player:
                    continue
                prior = street_events[:index]
                faced = next((item for item in reversed(prior)
                              if item.get("action") in ("bet", "raise", "reraise", "allin")), None)
                ratio = None
                faced_pot = faced.get("potBefore") if faced else None
                if (faced and isinstance(faced.get("increase"), (int, float)) and
                        isinstance(faced_pot, (int, float)) and faced_pot > 0):
                    ratio = float(faced["increase"]) / float(faced_pot)
                effective_stack = event.get("effectiveStack")
                if not isinstance(effective_stack, (int, float)):
                    effective_stack = (player.get("chips")
                                       if isinstance(player.get("chips"), (int, float)) else None)
                position = event.get("position") or player.get("position")
                event_board = self._board_for_street(
                    event.get("boardAtAction"), street)
                if event_board is None:
                    continue
                changed = self.record_decision_opportunity(
                    hand.get("id"), player, event.get("action"), street=street,
                    player_count=(event.get("playerCount")
                                  if isinstance(event.get("playerCount"), int)
                                  else sum(not seat.get("empty") for seat in seats)),
                    position=position, prior_actions=prior, board=event_board,
                    effective_stack=effective_stack, big_blind=event.get("bigBlind"),
                    bet_pot_ratio=event.get("betPotRatio", ratio), seats=seats,
                    facing_action=faced.get("action") if faced else None,
                    facing_amount=faced.get("amount") if faced else None,
                    facing_increase=faced.get("increase") if faced else None,
                    facing_pot=faced.get("potBefore") if faced else None,
                    action_sequence=event.get("sequence"),
                ) or changed
        return changed

    def _enrich_action_context(self, hand, seats, events, final_pot, board):
        hand_id = hand.get("id")
        if not isinstance(hand_id, int):
            return
        hand_key = f"{self.session_id}-{hand_id}"
        context = self.hand_action_contexts.setdefault(
            hand_key, {"pot": None, "folded": set(), "stacks": {}, "bigBlind": None,
                       "events": {}})
        ordered = sorted(
            (event for event in events if event.get("handId", hand_id) == hand_id),
            key=lambda event: (event.get("sequence", 0),
                               event.get("observedAt", event.get("videoSecond", 0))),
        )
        occupied = {seat.get("index") for seat in seats
                    if isinstance(seat.get("index"), int) and not seat.get("empty")}
        straddle_seats = {
            event.get("seat", 0) - 1 for event in ordered
            if event.get("street", hand.get("street")) == "preflop" and
            event.get("action") == "straddle"
        }
        increments = {}
        for event in ordered:
            seat_index = event.get("seat", 0) - 1
            increase = event.get("increase")
            if seat_index in occupied and isinstance(increase, (int, float)) and increase > 0:
                increments[seat_index] = increments.get(seat_index, 0.0) + float(increase)
            if (event.get("street", hand.get("street")) == "preflop" and
                    event.get("action") == "blind" and
                    isinstance(event.get("amount"), (int, float)) and event["amount"] > 0):
                context["bigBlind"] = max(float(event["amount"]),
                                          float(context.get("bigBlind") or 0))
        if not context["stacks"]:
            for seat in seats:
                index, chips = seat.get("index"), seat.get("chips")
                if index in occupied and isinstance(chips, (int, float)):
                    context["stacks"][index] = float(chips) + increments.get(index, 0.0)
        if not isinstance(context.get("pot"), (int, float)):
            known_increase = sum(float(event.get("increase") or 0) for event in ordered
                                 if isinstance(event.get("increase"), (int, float)))
            context["pot"] = (max(0.0, float(final_pot) - known_increase)
                              if isinstance(final_pot, (int, float)) else None)
        dealer = self.hand_dealers.get(hand_key)
        active = occupied - set(context["folded"])
        for event in ordered:
            event_key = (event.get("street"), event.get("sequence"), event.get("seat"),
                         event.get("action"), event.get("amount"), event.get("increase"),
                         event.get("observedAt", event.get("videoSecond")))
            frozen = context["events"].get(event_key)
            if frozen is not None:
                event.update(frozen)
                if event.get("seat", 0) - 1 in straddle_seats:
                    event["position"] = "straddle"
                    frozen["position"] = "straddle"
                if event.get("boardAtAction") is None:
                    event["boardAtAction"] = self._board_for_street(
                        board, event.get("street", hand.get("street")))
                    frozen["boardAtAction"] = event.get("boardAtAction")
                continue
            seat_index = event.get("seat", 0) - 1
            increase = event.get("increase")
            increase = float(increase) if isinstance(increase, (int, float)) and increase >= 0 else None
            pot_before = event.get("potBefore")
            if not isinstance(pot_before, (int, float)):
                pot_before = context.get("pot")
                if not isinstance(pot_before, (int, float)) and isinstance(event.get("potAfter"), (int, float)) and increase is not None:
                    pot_before = max(0.0, float(event["potAfter"]) - increase)
            event["potBefore"] = round(float(pot_before), 6) if isinstance(pot_before, (int, float)) else None
            event["playerCount"] = int(event.get("playerCount") or len(active)) if active else None
            event["position"] = ("straddle" if seat_index in straddle_seats else
                                 event.get("position") or
                                 self._seat_position(seat_index, occupied, dealer))
            event["bigBlind"] = (float(event["bigBlind"])
                                 if isinstance(event.get("bigBlind"), (int, float)) and event["bigBlind"] > 0
                                 else context.get("bigBlind"))
            actor_stack = context["stacks"].get(seat_index)
            opponents = [stack for index, stack in context["stacks"].items()
                         if index in active and index != seat_index and isinstance(stack, (int, float))]
            effective = (min(actor_stack, max(opponents))
                         if isinstance(actor_stack, (int, float)) and opponents else None)
            event["effectiveStack"] = (float(event["effectiveStack"])
                                       if isinstance(event.get("effectiveStack"), (int, float))
                                       else effective)
            big_blind = event.get("bigBlind")
            event["effectiveStackBb"] = (
                round(float(event["effectiveStack"]) / float(big_blind), 1)
                if isinstance(event.get("effectiveStack"), (int, float)) and
                isinstance(big_blind, (int, float)) and big_blind > 0 else None)
            event_board = self._board_for_street(
                event.get("boardAtAction"),
                event.get("street", hand.get("street")),
            )
            if event_board is None:
                event_board = self._board_for_street(
                    board, event.get("street", hand.get("street")))
            event["boardAtAction"] = event_board
            if isinstance(event.get("potAfter"), (int, float)):
                context["pot"] = float(event["potAfter"])
            elif isinstance(pot_before, (int, float)) and increase is not None:
                context["pot"] = float(pot_before) + increase
            if isinstance(event.get("chipsAfter"), (int, float)):
                context["stacks"][seat_index] = float(event["chipsAfter"])
            elif isinstance(actor_stack, (int, float)) and increase is not None:
                context["stacks"][seat_index] = max(0.0, actor_stack - increase)
            if event.get("action") == "fold":
                active.discard(seat_index)
                context["folded"].add(seat_index)
            context["events"][event_key] = {key: event.get(key) for key in (
                "potBefore", "position", "effectiveStack", "effectiveStackBb",
                "playerCount", "bigBlind", "boardAtAction")}
        if isinstance(final_pot, (int, float)):
            context["pot"] = float(final_pot)

    @staticmethod
    def _board_for_street(board, street):
        expected = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}.get(street)
        if expected is None:
            return None
        cards = list(board or [])
        if expected == 0:
            return []
        if len(cards) < expected:
            return None
        cards = cards[:expected]
        if len(set(cards)) != expected:
            return None
        return cards

    @staticmethod
    def _seat_position(seat_index, occupied, dealer_index):
        if not isinstance(dealer_index, int) or dealer_index not in occupied or seat_index not in occupied:
            return "unknown"
        ordered = sorted(occupied, key=lambda index: (index - dealer_index) % 8)
        labels = {
            2: ["dealer", "big_blind"],
            3: ["dealer", "small_blind", "big_blind"],
            4: ["dealer", "small_blind", "big_blind", "cutoff"],
            5: ["dealer", "small_blind", "big_blind", "under_the_gun", "cutoff"],
            6: ["dealer", "small_blind", "big_blind", "under_the_gun", "hijack", "cutoff"],
            7: ["dealer", "small_blind", "big_blind", "under_the_gun", "middle", "hijack", "cutoff"],
            8: ["dealer", "small_blind", "big_blind", "under_the_gun", "under_the_gun_plus_one", "middle", "hijack", "cutoff"],
        }
        if len(ordered) not in labels:
            return "unknown"
        return labels[len(ordered)][ordered.index(seat_index)]

    @staticmethod
    def _decision_context(street, player_count=None, position=None, prior_actions=(),
                          board=(), effective_stack=None, big_blind=None,
                          bet_pot_ratio=None, facing_action=None,
                          facing_amount=None, facing_increase=None,
                          facing_pot=None, action_sequence=None, **_):
        prior_types = [str(item.get("action")) for item in prior_actions
                       if isinstance(item, dict) and item.get("action")]
        if not prior_types and prior_actions:
            prior_types = [str(action) for action in prior_actions]
        stack_bb = (float(effective_stack) / float(big_blind)
                    if isinstance(effective_stack, (int, float)) and
                    isinstance(big_blind, (int, float)) and big_blind > 0 else None)
        return {
            "street": str(street or "unknown"),
            "playerCount": int(player_count) if isinstance(player_count, int) else None,
            "position": str(position or "unknown"),
            "priorActions": prior_types[-8:],
            "board": list(board or []),
            "boardClass": HistoryStore._board_class(board),
            "effectiveStackBb": None if stack_bb is None else round(stack_bb, 1),
            "betPotRatio": (round(float(bet_pot_ratio), 2)
                            if isinstance(bet_pot_ratio, (int, float)) and bet_pot_ratio >= 0 else None),
            "facingAction": (str(facing_action) if facing_action else None),
            "facingAmount": (round(float(facing_amount), 6)
                             if isinstance(facing_amount, (int, float)) else None),
            "facingIncrease": (round(float(facing_increase), 6)
                               if isinstance(facing_increase, (int, float)) else None),
            "facingPot": (round(float(facing_pot), 6)
                          if isinstance(facing_pot, (int, float)) else None),
            "actionSequence": (int(action_sequence)
                               if isinstance(action_sequence, int) else None),
        }

    @staticmethod
    def _board_class(board):
        cards = list(board or [])
        if not cards:
            return "preflop"
        ranks = [card[:-1] for card in cards if isinstance(card, str) and len(card) >= 2]
        suits = [card[-1] for card in cards if isinstance(card, str) and len(card) >= 2]
        paired = len(set(ranks)) < len(ranks)
        suit_count = max((suits.count(suit) for suit in set(suits)), default=0)
        return ("paired_" if paired else "unpaired_") + ("monotone" if suit_count >= 3 else
                                                           "two_tone" if suit_count == 2 else "rainbow")

    @classmethod
    def _reaction_weight(cls, count):
        for minimum, weight, tier in cls.REACTION_WEIGHTS:
            if count >= minimum:
                return weight, tier
        return 0.0, "0-4"

    @staticmethod
    def _context_matches(sample, target):
        for key in ("street", "playerCount", "position", "boardClass"):
            if target.get(key) not in (None, "unknown") and sample.get(key) != target.get(key):
                return False
        target_prior = target.get("priorActions") or []
        if target_prior and (sample.get("priorActions") or []) != target_prior:
            return False
        for key, tolerance in (("effectiveStackBb", 15.0), ("betPotRatio", .2)):
            expected, actual = target.get(key), sample.get(key)
            if expected is not None and (actual is None or abs(float(actual) - float(expected)) > tolerance):
                return False
        target_facing = HistoryStore._effective_facing_action(target)
        if target_facing not in (None, "unknown"):
            if HistoryStore._effective_facing_action(sample) != target_facing:
                return False
        for key, tolerance in (("facingAmount", .05), ("facingIncrease", .05), ("facingPot", .10)):
            expected, actual = target.get(key), sample.get(key)
            if expected is not None and (actual is None or abs(float(actual) - float(expected)) > tolerance):
                return False
        return True

    def _count_existing_events(self):
        try:
            with self.events_file.open("rb") as source:
                return sum(chunk.count(b"\n") for chunk in iter(
                    lambda: source.read(1024 * 1024), b""))
        except OSError:
            return 0

    def _profile_key(self, seat, seats=()):
        if not seat:
            return None
        seat_index = seat.get("index")
        name = self._normalized_name(seat.get("name"))
        avatar_hash = seat.get("avatarHash") or ""
        if seat.get("isHero") or name == "zixia888":
            return None
        current = self.session_identities.get(seat_index)
        if self._is_placeholder_name(name):
            if current:
                return current["key"]
            key = f"session:{self.session_id}:seat{seat_index}:placeholder"
            self.session_identities[seat_index] = {
                "key": key, "name": "", "avatarHash": "",
            }
            return key
        avatar_usable = avatar_hash and seat.get("action") not in ("fold", "empty") and not seat.get("empty")
        mvp_masked = not name or "mvp" in name
        current_name = self._normalized_name(current.get("name")) if current else ""
        alias_matches = [(key, profile) for key, profile in self.profiles.items()
                         if name in (profile.get("confirmedNameAliases") or ())]
        if len(alias_matches) == 1 and (not current or current.get("key") == alias_matches[0][0]):
            key, profile = alias_matches[0]
            identity = {"key": key, "name": profile.get("name", ""),
                        "avatarHash": avatar_hash}
            self.session_identities[seat_index] = identity
            if avatar_usable:
                self.session_avatar_identities[avatar_hash] = identity
            return key
        if not current and re.search(r"(?:\.{2,}|…)$", str(seat.get("name") or "").strip()):
            prefix_matches = [(key, profile) for key, profile in self.profiles.items()
                              if self._normalized_name(profile.get("name")).startswith(name)]
            if len(prefix_matches) == 1:
                key, profile = prefix_matches[0]
                identity = {"key": key, "name": profile.get("name", ""),
                            "avatarHash": avatar_hash}
                self.session_identities[seat_index] = identity
                if avatar_usable:
                    self.session_avatar_identities[avatar_hash] = identity
                return key
            return None
        if current and self._is_abbreviated_name(seat.get("name"), current.get("name")):
            if avatar_usable:
                current["avatarHash"] = avatar_hash
                self.session_avatar_identities[avatar_hash] = current
            return current["key"]
        close_name = bool(current_name and name and self._name_distance(current_name, name) <= 1)
        conflicting_real_name = bool(current_name and name and "mvp" not in name and current_name != name and not close_name)
        if name and "mvp" not in name:
            canonical_key = f"name:{name}"
            matched = self._session_identity_for_avatar(avatar_hash, name) if avatar_usable else None
            if matched and matched["key"] != canonical_key:
                self._promote_profile(matched["key"], canonical_key, seat)
            if current and (not conflicting_real_name or
                            (avatar_usable and current.get("avatarHash") == avatar_hash)):
                self._promote_profile(current["key"], canonical_key, seat)
            historical = self._matching_historical_profile(name, avatar_hash)
            if historical and self._is_abbreviated_name(
                    seat.get("name"), self.profiles.get(historical, {}).get("name")):
                identity = {"key": historical,
                            "name": self.profiles[historical].get("name", ""),
                            "avatarHash": avatar_hash}
                self.session_identities[seat_index] = identity
                if avatar_usable:
                    self.session_avatar_identities[avatar_hash] = identity
                return historical
            if historical and historical != canonical_key:
                self._promote_profile(historical, canonical_key, seat)
            identity = {"key": canonical_key, "name": name, "avatarHash": avatar_hash}
            self.session_identities[seat_index] = identity
            if avatar_usable:
                self.session_avatar_identities[avatar_hash] = identity
            return canonical_key
        if close_name:
            name = current_name
            return current["key"]
        if current and not avatar_usable and not conflicting_real_name:
            return current["key"]
        if current and current.get("avatarHash") == avatar_hash and not conflicting_real_name:
            if name and "mvp" not in name:
                current["name"] = name
                official_key = f"name:{name}"
                if current["key"] != official_key:
                    self._promote_profile(current["key"], official_key, seat)
                    current["key"] = official_key
            current["avatarHash"] = avatar_hash
            self.session_avatar_identities[avatar_hash] = current
            return current["key"]
        if avatar_usable:
            matched = self._session_identity_for_avatar(avatar_hash, name)
            if matched:
                self.session_identities[seat_index] = matched
                if name and "mvp" not in name:
                    matched["name"] = name
                    official_key = f"name:{name}"
                    if matched["key"] != official_key:
                        self._promote_profile(matched["key"], official_key, seat)
                        matched["key"] = official_key
                return matched["key"]
        if mvp_masked:
            if not avatar_usable:
                return current["key"] if current else None
            key = f"session:{self.session_id}:seat{seat_index}:avatar:{avatar_hash}"
            identity = {"key": key, "name": "", "avatarHash": avatar_hash}
            self.session_identities[seat_index] = identity
            self.session_avatar_identities[avatar_hash] = identity
            return key
        if not avatar_usable:
            return None if conflicting_real_name else current["key"] if current else None
        return None

    def _matching_historical_profile(self, name, avatar_hash):
        if not name or "mvp" in name:
            return None
        for key, profile in self.profiles.items():
            existing = self._normalized_name(profile.get("name"))
            if existing == name or self._name_distance(existing, name) <= 1:
                return key
        if avatar_hash:
            matches = [key for key, profile in self.profiles.items()
                       if avatar_hash == profile.get("avatarHash") or
                       avatar_hash in profile.get("avatarHashes", ())]
            if len(matches) == 1:
                return matches[0]
        return None

    def _session_identity_for_avatar(self, avatar_hash, name=""):
        direct = self.session_avatar_identities.get(avatar_hash)
        normalized = self._normalized_name(name)
        if direct and (not normalized or "mvp" in normalized or not direct.get("name") or
                       self._normalized_name(direct.get("name")) == normalized):
            return direct
        matches = [(self._hash_distance(candidate, avatar_hash), identity)
                   for candidate, identity in self.session_avatar_identities.items()]
        if normalized and "mvp" not in normalized:
            matches = [(distance, identity) for distance, identity in matches
                       if not identity.get("name") or self._normalized_name(identity.get("name")) == normalized]
        distance, identity = min(matches, default=(65, None), key=lambda item: item[0])
        return identity if distance <= 8 else None

    @staticmethod
    def _hash_distance(first, second):
        if first == second:
            return 0
        if not (str(first).startswith("ah1:") and str(second).startswith("ah1:")):
            return 65
        try:
            return (int(str(first)[4:], 16) ^ int(str(second)[4:], 16)).bit_count()
        except ValueError:
            return 65

    @staticmethod
    def _name_distance(first, second):
        if first == second:
            return 0
        if abs(len(first) - len(second)) > 1:
            return 99
        previous = list(range(len(second) + 1))
        for row, left in enumerate(first, 1):
            current = [row]
            for column, right in enumerate(second, 1):
                current.append(min(current[-1] + 1, previous[column] + 1,
                                   previous[column - 1] + (left != right)))
            previous = current
        return previous[-1]

    def _promote_profile(self, old_key, new_key, seat):
        if old_key == new_key:
            return
        old = self.profiles.pop(old_key, None)
        target = self.profiles.get(new_key)
        if old:
            if target is None:
                target = dict(old)
                self.profiles[new_key] = target
            else:
                for field in self.COUNT_FIELDS:
                    target[field] = int(target.get(field, 0) or 0) + int(old.get(field, 0) or 0)
                target.setdefault("decisionSamples", []).extend(old.get("decisionSamples", []))
                del target["decisionSamples"][:-self.REACTION_SAMPLE_LIMIT]
                current_platform = target.get("platformStatistics") or {}
                old_platform = old.get("platformStatistics") or {}
                if float(old_platform.get("capturedAt", 0) or 0) > float(
                        current_platform.get("capturedAt", 0) or 0):
                    target["platformStatistics"] = dict(old_platform)
                target.setdefault("platformStatisticsHistory", []).extend(
                    old.get("platformStatisticsHistory", []))
                target["platformStatisticsHistory"] = sorted(
                    target["platformStatisticsHistory"],
                    key=lambda item: float(item.get("capturedAt", 0) or 0))[-20:]
                aliases = target.setdefault("confirmedNameAliases", [])
                for alias in old.get("confirmedNameAliases", []):
                    if alias not in aliases:
                        aliases.append(alias)
        if target is not None:
            target["name"] = seat.get("name", target.get("name", ""))
            target["avatarHash"] = seat.get("avatarHash", target.get("avatarHash", ""))
        for identity in self.session_identities.values():
            if identity.get("key") == old_key:
                identity["key"] = new_key
        self.counted_hand_profiles = {
            (hand_key, new_key if key == old_key else key)
            for hand_key, key in self.counted_hand_profiles
        }
        self.hand_profiles = {
            (hand_key, new_key if key == old_key else key, metric)
            for hand_key, key, metric in self.hand_profiles
        }

    @staticmethod
    def _normalized_name(name):
        return re.sub(r"[\s.·…]+", "", (name or "").casefold())

    @staticmethod
    def _is_placeholder_name(name):
        return bool(re.fullmatch(r"seat\d+", str(name or "")))

    @staticmethod
    def _closest_existing_name(name, profiles):
        for existing in profiles:
            if len(name) >= 4 and len(name) == len(existing) and sum(a != b for a, b in zip(name, existing)) <= 1:
                return existing
        return name

    def _migrate_profiles(self):
        legacy_profiles = {
            key for key, profile in self.profiles.items()
            if int(profile.get("statisticsVersion", 0) or 0) < self.STATISTICS_VERSION
        }
        if legacy_profiles and self.profiles_file.is_file():
            backup = self.profiles_file.with_name(
                f"{self.profiles_file.stem}.pre-statistics-v{self.STATISTICS_VERSION}.backup.json"
            )
            if not backup.exists():
                shutil.copy2(self.profiles_file, backup)
        legacy_reactions = {
            key for key, profile in self.profiles.items()
            if int(profile.get("reactionModelVersion", 0) or 0) < self.REACTION_MODEL_VERSION
        }
        if legacy_reactions and self.profiles_file.is_file():
            backup = self.profiles_file.with_name(
                f"{self.profiles_file.stem}.pre-reaction-v{self.REACTION_MODEL_VERSION}.backup.json"
            )
            if not backup.exists():
                shutil.copy2(self.profiles_file, backup)
        merged = {}
        for existing_key, profile in self.profiles.items():
            name = self._normalized_name(profile.get("name"))
            avatar_hash = profile.get("avatarHash", "")
            if (re.fullmatch(r"session:[^:]+:seat\d+:placeholder", existing_key) and
                    int(profile.get("statisticsVersion", 0) or 0) >= self.STATISTICS_VERSION and
                    int(profile.get("reactionModelVersion", 0) or 0) >= self.REACTION_MODEL_VERSION):
                merged[existing_key] = profile
                continue
            if not name or name == "zixia888" or "mvp" in name:
                continue
            key = f"name:{name}"
            target = merged.setdefault(key, {
                "name": profile.get("name", ""), "avatarHash": avatar_hash,
                "avatarHashes": profile.get("avatarHashes") or ([avatar_hash] if avatar_hash else []),
                "confirmedNameAliases": [],
                "hands": 0, "preflopOpportunities": 0, "vpipHands": 0, "pfrHands": 0,
                "actions": 0, "calls": 0, "raises": 0, "bets": 0, "folds": 0, "checks": 0,
                "reraises": 0, "facingBetOpportunities": 0, "foldsFacingBet": 0,
                "postflopCalls": 0, "postflopBets": 0, "postflopRaises": 0,
                "preflopFacingRaiseOpportunities": 0, "preflopFoldsFacingRaise": 0,
                "preflopCallsFacingRaise": 0, "preflopReraisesFacingRaise": 0,
                "flopFacingBetOpportunities": 0, "flopFoldsFacingBet": 0,
                "turnFacingBetOpportunities": 0, "turnFoldsFacingBet": 0,
                "riverFacingBetOpportunities": 0, "riverFoldsFacingBet": 0,
                "statisticsVersion": self.STATISTICS_VERSION,
                "reactionModelVersion": self.REACTION_MODEL_VERSION,
                "decisionSamples": [], "revealedCardSamples": [], "revealedHands": 0,
            })
            if int(profile.get("statisticsVersion", 0) or 0) >= self.STATISTICS_VERSION:
                for field in self.COUNT_FIELDS:
                    target[field] += int(profile.get(field, 0) or 0)
                target["decisionSamples"].extend(
                    sample for sample in profile.get("decisionSamples", [])
                    if self._valid_decision_sample(sample)
                )
                del target["decisionSamples"][:-self.REACTION_SAMPLE_LIMIT]
                known_hands = {sample.get("handKey") for sample in target["revealedCardSamples"]}
                for sample in profile.get("revealedCardSamples", []):
                    cards = list(sample.get("cards") or [])
                    if (sample.get("handKey") not in known_hands and len(cards) == 2 and
                            len(set(cards)) == 2):
                        target["revealedCardSamples"].append(sample)
                        known_hands.add(sample.get("handKey"))
                del target["revealedCardSamples"][:-200]
                target["revealedHands"] = len(target["revealedCardSamples"])
                current_platform = target.get("platformStatistics") or {}
                incoming_platform = profile.get("platformStatistics") or {}
                if float(incoming_platform.get("capturedAt", 0) or 0) >= float(
                        current_platform.get("capturedAt", 0) or 0):
                    target["platformStatistics"] = dict(incoming_platform)
                target.setdefault("platformStatisticsHistory", []).extend(
                    profile.get("platformStatisticsHistory", []))
                target["platformStatisticsHistory"] = sorted(
                    target["platformStatisticsHistory"],
                    key=lambda item: float(item.get("capturedAt", 0) or 0))[-20:]
                for alias in profile.get("confirmedNameAliases", []):
                    alias = self._normalized_name(alias)
                    if alias and alias not in target["confirmedNameAliases"]:
                        target["confirmedNameAliases"].append(alias)
        if merged != self.profiles:
            self.profiles = merged
            self._save_profiles()
        type(self)._active_profiles = self.profiles

    @classmethod
    def _valid_decision_sample(cls, sample):
        if not isinstance(sample, dict):
            return False
        board = cls._board_for_street(sample.get("board"), sample.get("street"))
        return board is not None and board == list(sample.get("board") or [])

    def _profile(self, key, seat):
        profile = self.profiles.setdefault(key, {
            "name": seat.get("name", ""), "avatarHash": seat.get("avatarHash", ""),
            "avatarHashes": [],
            "hands": 0, "preflopOpportunities": 0, "vpipHands": 0, "pfrHands": 0,
            "actions": 0, "calls": 0, "raises": 0, "bets": 0, "folds": 0, "checks": 0,
            "reraises": 0, "facingBetOpportunities": 0, "foldsFacingBet": 0,
            "postflopCalls": 0, "postflopBets": 0, "postflopRaises": 0,
            "preflopFacingRaiseOpportunities": 0, "preflopFoldsFacingRaise": 0,
            "preflopCallsFacingRaise": 0, "preflopReraisesFacingRaise": 0,
            "flopFacingBetOpportunities": 0, "flopFoldsFacingBet": 0,
            "turnFacingBetOpportunities": 0, "turnFoldsFacingBet": 0,
            "riverFacingBetOpportunities": 0, "riverFoldsFacingBet": 0,
            "statisticsVersion": self.STATISTICS_VERSION,
            "reactionModelVersion": self.REACTION_MODEL_VERSION,
            "decisionSamples": [], "revealedCardSamples": [], "revealedHands": 0,
        })
        name = seat.get("name", "")
        if name and "mvp" not in name.casefold():
            profile["name"] = name
        if seat.get("avatarHash") and seat.get("action") not in ("fold", "empty"):
            profile["avatarHash"] = seat["avatarHash"]
            hashes = profile.setdefault("avatarHashes", [])
            if all(self._hash_distance(value, seat["avatarHash"]) > 8 for value in hashes):
                hashes.append(seat["avatarHash"])
                del hashes[:-5]
        return profile

    def _append(self, record):
        encoded = json.dumps(record, ensure_ascii=False) + "\n"
        with self.lock:
            self._rotate_event_log(len(encoded.encode("utf-8")))
            with self.events_file.open("a", encoding="utf-8") as target:
                target.write(encoded)
            self._event_count += 1

    def _rotate_event_log(self, incoming_bytes=0):
        try:
            if self.events_file.stat().st_size + max(0, int(incoming_bytes)) <= self.EVENT_LOG_MAX_BYTES:
                return
            stamp = time.strftime("%Y%m%d-%H%M%S")
            archive = self.events_file.with_name(f"{self.events_file.name}.{stamp}")
            suffix = 1
            while archive.exists():
                archive = self.events_file.with_name(
                    f"{self.events_file.name}.{stamp}.{suffix}")
                suffix += 1
            self.events_file.replace(archive)
            archives = sorted(
                self.events_file.parent.glob(f"{self.events_file.name}.*"),
                key=lambda item: item.stat().st_mtime, reverse=True)
            for expired in archives[self.EVENT_LOG_BACKUP_COUNT:]:
                expired.unlink()
        except OSError:
            pass

    def _save_profiles(self):
        temporary = self.profiles_file.with_suffix(".tmp")
        with self.lock:
            self._reaction_pool_version += 1
            self._reaction_pool_cache = None
            temporary.write_text(json.dumps(self.profiles, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.profiles_file)

    def _load_profiles(self):
        try:
            return json.loads(self.profiles_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
