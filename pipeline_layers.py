from collections.abc import Mapping, Sequence
from dataclasses import asdict

from pipeline_contracts import (
    ActionEvent,
    AdvicePresentation,
    CapturedFrame,
    DecisionRequest,
    HandStateSnapshot,
    RecognitionValue,
)


def capture_layer(state: Mapping) -> CapturedFrame | None:
    sequence = state.get("frameSequence")
    captured_at = state.get("frameCapturedAt")
    bbox = state.get("captureBbox") or state.get("bbox")
    if not isinstance(sequence, int) or not isinstance(captured_at, (int, float)):
        return None
    if not isinstance(bbox, Sequence) or len(bbox) != 4:
        bbox = (0, 0, 0, 0)
    return CapturedFrame(sequence, float(captured_at), tuple(int(value) for value in bbox))


def recognition_layer(state: Mapping) -> tuple[RecognitionValue, ...]:
    values = []
    for field, evidence in (state.get("fieldStatus") or {}).items():
        if not isinstance(evidence, Mapping) or evidence.get("stale"):
            continue
        sequence = evidence.get("frameSequence", state.get("frameSequence"))
        observed_at = evidence.get("observedAt", evidence.get("updatedAt"))
        confidence = evidence.get("confidence")
        source = evidence.get("source")
        if not isinstance(sequence, int) or not isinstance(observed_at, (int, float)):
            continue
        if not isinstance(confidence, (int, float)) or not source:
            continue
        values.append(RecognitionValue(field, evidence.get("value"), float(confidence),
                                       str(source), sequence, float(observed_at)))
    return tuple(values)


def state_layer(state: Mapping) -> HandStateSnapshot:
    actions = tuple(ActionEvent.from_mapping(item) for item in state.get("actionLog") or [])
    dealer = state.get("dealerSeat")
    if not isinstance(dealer, int):
        dealer_index = state.get("dealerIndex")
        dealer = dealer_index + 1 if isinstance(dealer_index, int) else None
    return HandStateSnapshot(
        int(state.get("tableSession") or 0),
        int(state.get("handId") or 0),
        str(state.get("street") or "waiting"),
        dealer,
        tuple(state.get("heroCards") or ()),
        tuple(state.get("boardCards") or ()),
        actions,
        bool(state.get("reliable")),
    )


def decision_layer(state: Mapping, legal_actions: Sequence[str]) -> DecisionRequest | None:
    hand = state_layer(state)
    pot = state.get("pot")
    call = state.get("callAmount")
    sequence = state.get("actionButtonSequence")
    if hand.hand_id <= 0 or not isinstance(pot, (int, float)) or not isinstance(call, (int, float)):
        return None
    if not isinstance(sequence, int) or sequence <= 0:
        return None
    key = f"{hand.table_session}:{hand.hand_id}:{hand.street}:{sequence}"
    minimum = state.get("minRaiseTo")
    seats = state.get("seats") or ()
    hero_index = 3 if state.get("layout") == "6max" else 4
    hero = next((seat for seat in seats if seat.get("index") == hero_index), {})
    stacks = {int(seat["index"]) + 1: float(seat["chips"]) for seat in seats
              if seat.get("index") != hero_index and isinstance(seat.get("chips"), (int, float))}
    profiles = state.get("opponentProfiles") or {}
    ranges = {int(index) + 1: str(profile.get("rangeType")) for index, profile in profiles.items()
              if isinstance(profile, Mapping) and profile.get("rangeType")}
    play = state.get("tablePlay")
    play_type = play.get("type") if isinstance(play, Mapping) else play
    side_pot_contract = state.get("sidePotContract")
    return DecisionRequest(
        key, hand, float(pot), float(call),
        float(minimum) if isinstance(minimum, (int, float)) else None,
        tuple(legal_actions),
        float(hero["chips"]) if isinstance(hero.get("chips"), (int, float)) else None,
        stacks, ranges, str(play_type) if play_type else None,
        float(state["rakeRate"]) if isinstance(state.get("rakeRate"), (int, float)) else None,
        float(state["rakeCap"]) if isinstance(state.get("rakeCap"), (int, float)) else None,
        side_pot_contract if isinstance(side_pot_contract, Mapping) else None,
    )


def presentation_layer(decision_key: str, decision: Mapping) -> AdvicePresentation | None:
    primary = decision.get("primary")
    confidence = decision.get("confidence")
    reasons = decision.get("reasons") or decision.get("decisionReasons") or ()
    if not primary or not isinstance(confidence, (int, float)):
        return None
    amount = decision.get("recommended")
    return AdvicePresentation(
        decision_key,
        str(primary),
        float(amount) if isinstance(amount, (int, float)) else None,
        tuple(str(reason) for reason in reasons),
        float(confidence),
    )


def pipeline_snapshot(state: Mapping) -> dict:
    buttons = state.get("visualButtons") or state.get("buttons") or ()
    legal = tuple(str(button.get("kind")) for button in buttons
                  if isinstance(button, Mapping) and button.get("kind"))
    frame = capture_layer(state)
    hand = state_layer(state)
    decision = decision_layer(state, legal)
    return {
        "capture": asdict(frame) if frame else None,
        "recognition": [asdict(item) for item in recognition_layer(state)],
        "state": asdict(hand),
        "decision": asdict(decision) if decision else None,
        "presentation": None,
    }
