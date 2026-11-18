from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EvidenceEvent:
    runtime_id: str
    table_session: int
    frame_sequence: int | None
    captured_at: float | None
    seat: int
    street_hint: str
    evidence_type: str
    raw_value: Any
    normalized_value: Any
    confidence: float
    crop_path: str | None = None
    frame_reference: str | None = None
    source: str = ""

    def __post_init__(self):
        if not self.runtime_id:
            raise ValueError("runtime_id is required")
        if self.seat < 1:
            raise ValueError("seat must be one-based")
        if self.street_hint not in ("preflop", "flop", "turn", "river"):
            raise ValueError("invalid street_hint")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")

    def as_record(self):
        return asdict(self)

    @classmethod
    def from_confirmed_action(cls, event, runtime_id, table_session):
        frame_sequence = event.get("frameSequence")
        return cls(
            runtime_id=runtime_id,
            table_session=int(table_session),
            frame_sequence=frame_sequence,
            captured_at=event.get("capturedAt", event.get("observedAt")),
            seat=int(event["seat"]),
            street_hint=event.get("street", "preflop"),
            evidence_type="confirmed_action",
            raw_value={key: event.get(key) for key in (
                "action", "amount", "increase", "investmentText", "evidence"
            ) if key in event},
            normalized_value={key: event.get(key) for key in (
                "handId", "action", "amount", "increase", "observedAt",
                "videoSecond", "frameSequence", "confidence", "inferred",
                "visualCandidate", "orderConflict", "chainStatus",
            ) if key in event},
            confidence=max(0.0, min(1.0, float(event.get("confidence") or 0))),
            frame_reference=(None if frame_sequence is None else
                             f"frame:{frame_sequence}"),
            source=str(event.get("evidence") or "confirmed_action"),
        )
