from functools import lru_cache

from v4.preflop_baseline_rules import decide
from v4.preflop_enumeration import hand_classes
from v4.preflop_scene_recognizer import (
    action_family as recognized_action_family,
    effective_stack_bb as recognized_effective_stack_bb,
    hand_class as recognized_hand_class,
    pressure_bucket as recognized_pressure_bucket,
    rake_policy as recognized_rake_policy,
    recognize_preflop,
    seat_positions as recognized_seat_positions,
    stack_bucket as recognized_stack_bucket,
    strategy_actors_and_role as recognized_strategy_actors_and_role,
)


@lru_cache(maxsize=256)
def _cached_baseline_range(active_players, hero_position, effective_stack_bucket,
                           rake_policy_name, prior_action_pattern,
                           pressure_bucket_name, actors, hero_role):
    state = {
        "activePlayers": active_players,
        "heroPosition": hero_position,
        "effectiveStackBucket": effective_stack_bucket,
        "rakePolicy": rake_policy_name,
        "priorActionPattern": prior_action_pattern,
        "pressureBucket": pressure_bucket_name,
        "actors": tuple(actors),
        "heroRole": hero_role,
    }
    hands = hand_classes()
    entries = []
    for hand in hands:
        decision = decide(hand, state, hands)
        entries.append((hand, decision.action, decision.reason_code,
                        decision.requires_realtime_math, decision.evidence_level,
                        decision.evidence_source))
    return tuple(entries)


def baseline_range(normalized):
    entries = _cached_baseline_range(
        normalized["activePlayers"], normalized["heroPosition"],
        normalized["effectiveStackBucket"], normalized["rakePolicy"],
        normalized["priorActionPattern"], normalized["pressureBucket"],
        tuple(normalized.get("actors") or ()), normalized["heroRole"])
    return {
        "actions": {entry[0]: entry[1] for entry in entries},
        "reasons": {entry[0]: entry[2] for entry in entries},
        "requiresRealtimeMath": {entry[0]: entry[3] for entry in entries},
        "evidenceLevels": {entry[0]: entry[4] for entry in entries},
        "evidenceSources": {entry[0]: entry[5] for entry in entries},
        "classes": len(entries),
        "source": "场景基础策略静态范围",
    }


hand_class = recognized_hand_class
stack_bucket = recognized_stack_bucket
rake_policy = recognized_rake_policy
effective_stack_bb = recognized_effective_stack_bb
action_family = recognized_action_family
seat_positions = recognized_seat_positions
strategy_actors_and_role = recognized_strategy_actors_and_role
pressure_bucket = recognized_pressure_bucket


def evaluate_shadow(state, hero_index, include_range=False, require_actionable=True):
    recognized = recognize_preflop(
        state, hero_index, require_actionable=require_actionable)
    if not recognized.get("eligible"):
        return recognized
    hand = recognized["handClass"]
    normalized = recognized["normalizedState"]
    stack_bb_value = recognized["effectiveStackBb"]
    family = normalized["priorActionPattern"]
    decision = decide(hand, normalized, hand_classes())
    result = {
        "eligible": True, "mode": "只读旁路", "handClass": hand,
        "effectiveStackBb": stack_bb_value, "normalizedState": normalized,
        "scene": recognized["scene"], "pressure": recognized["pressure"],
        "baselineAction": decision.action, "reason": decision.reason_code,
        "requiresRealtimeMath": decision.requires_realtime_math,
        "evidenceLevel": decision.evidence_level,
        "evidenceSource": decision.evidence_source,
        "formalAdviceChanged": False,
    }
    if include_range:
        static_range = baseline_range(normalized)
        result.update(
            rangeActions=static_range["actions"],
            rangeReasons=static_range["reasons"],
            rangeRequiresRealtimeMath=static_range["requiresRealtimeMath"],
            rangeEvidenceLevels=static_range["evidenceLevels"],
            rangeEvidenceSources=static_range["evidenceSources"],
            rangeClasses=static_range["classes"],
            rangeSource=static_range["source"],
        )
    return result
