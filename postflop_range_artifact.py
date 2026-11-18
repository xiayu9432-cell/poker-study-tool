import argparse
import gzip
import hashlib
import json
from itertools import combinations
from pathlib import Path


RANKS = "23456789TJQKA"
SUITS = "cdhs"
CARDS = tuple(rank + suit for rank in RANKS for suit in SUITS)
COMBOS = tuple("".join(combo) for combo in combinations(CARDS, 2))
FORMAT_VERSION = 1


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def checksum(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_release(root):
    root = Path(root)
    version = (root / "CURRENT").read_text(encoding="utf-8").strip()
    release = root / "releases" / version
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    records = []
    for shard in manifest["shards"]:
        with gzip.open(release / shard["path"], "rt", encoding="utf-8") as source:
            records.extend(json.load(source)["records"])
    return version, manifest, records


def combo_weights(strategies, action_id):
    weights = {item["hand"]: float(item["actions"].get(action_id, 0.0)) for item in strategies}
    if set(weights) != set(COMBOS):
        raise ValueError("source strategy does not contain all 1326 private-card combos")
    if any(weight < 0 or weight > 1 for weight in weights.values()):
        raise ValueError("source strategy contains an invalid combo weight")
    return weights


def hand_class(combo):
    cards = (combo[:2], combo[2:])
    first, second = sorted(cards, key=lambda card: RANKS.index(card[0]), reverse=True)
    if first[0] == second[0]:
        return first[0] * 2
    return first[0] + second[0] + ("s" if first[1] == second[1] else "o")


def response_combo_weights(profile, facing_action, response):
    by_class = {
        item["hand_class"]: float(item["actions"].get(response, 0.0))
        for item in profile if item.get("facing_action") == facing_action
    }
    weights = {combo: by_class[hand_class(combo)] for combo in COMBOS}
    if len(by_class) != 169 or any(weight < 0 or weight > 1 for weight in weights.values()):
        raise ValueError("source response profile is incomplete or invalid")
    return weights


def weighted_range(role, weights, source, confidence, limitations):
    return {
        "role": role,
        "combo_count": len(weights),
        "weights": weights,
        "normalization": "independent combo inclusion weights in [0,1]",
        "source": source,
        "confidence": confidence,
        "limitations": limitations,
    }


def neutral_limited_range(role, reason):
    return weighted_range(
        role,
        {combo: 1.0 for combo in COMBOS},
        {"kind": "restricted_neutral_baseline", "reason": reason},
        "insufficient_for_formal_solving",
        ["not inferred from an observed or solved conditional action node",
         "must not be substituted for a missing call, 3bet, or call-3bet range"],
    )


def derive_open_ranges(records, preflop_version, manifest):
    ranges = {}
    for record in records:
        result = record["result"]
        scene = result["scene_key"]
        if (scene["positions"] != {"hero": "BTN", "villain": "BB", "actor": "hero",
                                    "facing": "unopened"}
                or scene["action"]["prior_chain"] != []):
            continue
        stack_id = scene["effective_stack"]["id"]
        weights = combo_weights(result["nodes"][0]["strategies"], "raise_2_5")
        source = {
                "kind": "published_preflop_action_marginal",
                "release": preflop_version,
                "release_manifest_checksum": checksum(manifest),
                "scene_hash": record["scene_hash"],
                "result_checksum": record["checksum"],
                "node_id": "root",
                "action_id": "raise_2_5",
            }
        ip = weighted_range(
            "BTN_after_raise_2_5bb",
            weights,
            source,
            "validated_within_published_single-response-abstraction",
            ["marginal BTN opening action only",
             "valid only for the published single-response abstraction"],
        )
        oop = weighted_range(
            "BB_after_call_2_5bb",
            response_combo_weights(result["opponent_response_profile"], "raise_2_5", "continue"),
            {
                "kind": "published_preflop_response_marginal",
                "release": preflop_version,
                "release_manifest_checksum": checksum(manifest),
                "scene_hash": record["scene_hash"],
                "result_checksum": record["checksum"],
                "facing_action": "raise_2_5",
                "response": "continue",
                "response_semantics": "call_then_showdown",
            },
            "validated_within_published-single-response-call-abstraction",
            ["continue is a call because the source abstraction has only fold/continue and uses call/showdown payoff",
             "does not provide a separate BB 3bet range or model a full preflop response tree"],
        )
        ranges[stack_id] = {"ip": ip, "oop": oop}
    return ranges


def build_artifact(postflop_config, preflop_root):
    config = json.loads(Path(postflop_config).read_text(encoding="utf-8"))
    preflop_version, manifest, records = load_release(preflop_root)
    open_ranges = derive_open_ranges(records, preflop_version, manifest)
    scenarios = []
    for pot in config["scenario_generator"]["pot_types"]:
        for stack in config["scenario_generator"]["stack_buckets"]:
            key = f'{pot["id"]}:{stack["id"]}'
            if pot["id"] == "single-raised":
                derived = open_ranges.get(stack["id"])
                ip = (derived or {}).get("ip") or neutral_limited_range(
                    "BTN_after_raise_2_5bb", "no matching published preflop stack bucket")
                oop = (derived or {}).get("oop") or neutral_limited_range(
                    "BB_after_call_2_5bb", "no matching published preflop response profile")
            elif pot["id"] == "3bet":
                ip = neutral_limited_range(
                    "BTN_after_call_10bb", "published preflop library has no facing-3bet node")
                oop = neutral_limited_range(
                    "BB_after_raise_10bb", "published preflop library has no BB 3bet action node")
            else:
                ip = neutral_limited_range("IP", "unsupported postflop pot type")
                oop = neutral_limited_range("OOP", "unsupported postflop pot type")
            blockers = [item for item in (ip, oop)
                        if item["confidence"] == "insufficient_for_formal_solving"]
            scenarios.append({
                "scenario_id": key,
                "pot_type": pot["id"],
                "stack_id": stack["id"],
                "positions": {"ip": "BTN", "oop": "BB"},
                "ranges": {"ip": ip, "oop": oop},
                "solve_allowed": not blockers,
                "publish_allowed": not blockers,
                "block_reasons": [item["source"]["reason"] for item in blockers],
            })
    artifact = {
        "format_version": FORMAT_VERSION,
        "artifact_kind": "postflop_combo_weight_ranges",
        "range_version": "hu-btn-bb-postflop-ranges-v1-restricted",
        "source_preflop_release": preflop_version,
        "source_library_schema": manifest["library_schema_version"],
        "combo_universe": {"variant": "holdem", "count": len(COMBOS)},
        "scenarios": scenarios,
        "summary": {
            "total": len(scenarios),
            "solve_allowed": sum(item["solve_allowed"] for item in scenarios),
            "publish_allowed": sum(item["publish_allowed"] for item in scenarios),
            "partially_traceable": sum(
                item["ranges"]["ip"]["source"]["kind"] == "published_preflop_action_marginal"
                for item in scenarios),
        },
    }
    artifact["artifact_checksum"] = checksum(artifact)
    return artifact


def validate_artifact(artifact, expected_version=None):
    errors = []
    if artifact.get("artifact_kind") != "postflop_combo_weight_ranges":
        errors.append("range artifact kind is invalid")
    if expected_version and artifact.get("range_version") != expected_version:
        errors.append("range version does not match postflop config")
    unsigned = {key: value for key, value in artifact.items() if key != "artifact_checksum"}
    if artifact.get("artifact_checksum") != checksum(unsigned):
        errors.append("range artifact checksum is invalid")
    scenarios = artifact.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        errors.append("range artifact has no scenarios")
        return errors
    for scenario in scenarios:
        scenario_id = scenario.get("scenario_id", "unknown")
        ranges = scenario.get("ranges", {})
        for role in ("ip", "oop"):
            weighted = ranges.get(role, {})
            weights = weighted.get("weights", {})
            if weighted.get("combo_count") != len(COMBOS) or set(weights) != set(COMBOS):
                errors.append(f"{scenario_id}/{role} does not cover all 1326 combos")
            elif any(not isinstance(weight, (int, float)) or weight < 0 or weight > 1
                     for weight in weights.values()):
                errors.append(f"{scenario_id}/{role} has invalid combo weights")
        limited = any(ranges.get(role, {}).get("confidence") == "insufficient_for_formal_solving"
                      for role in ("ip", "oop"))
        if limited and (scenario.get("solve_allowed") or scenario.get("publish_allowed")):
            errors.append(f"{scenario_id} enables formal use with a restricted baseline")
    return errors


def load_configured_artifact(config_path):
    config_path = Path(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    artifact_path = Path(config["range_artifact"])
    if not artifact_path.is_absolute():
        artifact_path = config_path.parent / artifact_path
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    errors = validate_artifact(artifact, config["range_version"])
    if errors:
        raise ValueError("; ".join(errors))
    return artifact


def main():
    parser = argparse.ArgumentParser(description="Build auditable postflop combo-weight ranges")
    parser.add_argument("--config", default="strategy_library_builder.json")
    parser.add_argument("--preflop-root", default="strategy_library_preflop_v3_data")
    parser.add_argument("--output", default="postflop_ranges_v1.json")
    args = parser.parse_args()
    artifact = build_artifact(args.config, args.preflop_root)
    Path(args.output).write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(canonical_json(artifact["summary"]))


if __name__ == "__main__":
    main()
