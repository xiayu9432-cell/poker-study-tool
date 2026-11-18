from dataclasses import dataclass, field
from typing import Any, Mapping


STREETS = ("preflop", "flop", "turn", "river")
FORCED_ACTIONS = frozenset(("blind", "post_blind", "straddle"))
VOLUNTARY_ACTIONS = frozenset(("fold", "check", "call", "bet", "raise", "reraise", "allin"))


@dataclass(frozen=True)
class CapturedFrame:
    sequence: int
    captured_at: float
    bbox: tuple[int, int, int, int]


@dataclass(frozen=True)
class RecognitionValue:
    field: str
    value: Any
    confidence: float
    source: str
    frame_sequence: int
    observed_at: float


@dataclass(frozen=True)
class HandStateSnapshot:
    table_session: int
    hand_id: int
    street: str
    dealer_seat: int | None
    hero_cards: tuple[str, ...]
    board_cards: tuple[str, ...]
    actions: tuple["ActionEvent", ...]
    reliable: bool


@dataclass(frozen=True)
class DecisionRequest:
    decision_key: str
    state: HandStateSnapshot
    pot: float
    call_amount: float
    min_raise_to: float | None
    legal_actions: tuple[str, ...]
    hero_stack: float | None = None
    opponent_stacks: Mapping[int, float] = field(default_factory=dict)
    opponent_ranges: Mapping[int, str] = field(default_factory=dict)
    table_play: str | None = None
    rake_rate: float | None = None
    rake_cap: float | None = None
    side_pot_contract: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class AdvicePresentation:
    decision_key: str
    primary: str
    amount: float | None
    reasons: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class ActionEvent:
    hand_id: int
    street: str
    seat: int
    action: str
    amount: float | None = None
    increase: float | None = None
    observed_at: float | None = None
    frame_sequence: int | None = None
    confidence: float | None = None
    source: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ActionEvent":
        return cls(
            hand_id=int(value.get("handId") or 0),
            street=str(value.get("street") or "preflop"),
            seat=int(value.get("seat") or 0),
            action=str(value.get("action") or ""),
            amount=_number(value.get("amount")),
            increase=_number(value.get("increase")),
            observed_at=_number(value.get("observedAt") or value.get("videoSecond")),
            frame_sequence=_integer(value.get("frameSequence")),
            confidence=_number(value.get("confidence")),
            source=value.get("source") or value.get("evidence"),
        )

    def validate(self, seat_count: int) -> list[str]:
        errors = []
        if self.hand_id <= 0:
            errors.append("hand_id_missing")
        if self.street not in STREETS:
            errors.append("street_invalid")
        if not 1 <= self.seat <= seat_count:
            errors.append("seat_invalid")
        if self.action not in FORCED_ACTIONS | VOLUNTARY_ACTIONS:
            errors.append("action_invalid")
        if self.amount is not None and self.amount < 0:
            errors.append("amount_negative")
        return errors


@dataclass(frozen=True)
class RuleSnapshot:
    valid: bool
    first_error_index: int | None
    reason: str | None
    expected_seat: int | None
    observed_seat: int | None
    legal_actions: tuple[str, ...] = ()
    call_amount: float | None = None
    min_raise_to: float | None = None
    street: str | None = None
    checked_events: int = 0
    details: Mapping[str, Any] = field(default_factory=dict)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)
