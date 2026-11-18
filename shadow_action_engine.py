from action_chain_engine import ActionChainEngine
from action_evidence import EvidenceEvent


COMPARISON_FIELDS = (
    "reliable", "nextActorSeat", "awaitingSeats", "currentPrice",
    "investments", "round", "roundClosed", "activeSeats", "canActSeats",
)
BATCH_A_ACTIONS = frozenset((
    "blind", "post_blind", "fold", "check", "call", "bet", "raise", "reraise",
))


class ShadowActionEngine:
    """Read-only action ledger used to compare a future engine with production."""

    def __init__(self):
        self.scope = None
        self.evidence_events = []
        self.action_events = []
        self.signatures = set()

    def reset(self, runtime_id=None, table_session=None, hand_id=None):
        self.scope = (runtime_id, table_session, hand_id)
        self.evidence_events.clear()
        self.action_events.clear()
        self.signatures.clear()

    @staticmethod
    def _signature(event):
        return tuple(event.get(key) for key in (
            "handId", "street", "seat", "action", "amount", "increase",
            "frameSequence", "observedAt",
        ))

    def accept_confirmed_action(self, event, runtime_id, table_session):
        scope = (runtime_id, table_session, event.get("handId"))
        if self.scope != scope:
            self.reset(*scope)
        evidence = EvidenceEvent.from_confirmed_action(
            event, runtime_id, table_session)
        signature = self._signature(event)
        if signature in self.signatures:
            return evidence, False
        self.signatures.add(signature)
        self.evidence_events.append(evidence)
        normalized = dict(evidence.normalized_value)
        normalized.update(
            handId=event.get("handId"), street=evidence.street_hint,
            seat=evidence.seat, action=event.get("action"),
        )
        self.action_events.append(normalized)
        return evidence, True

    def replace_confirmed_actions(self, events, runtime_id, table_session, hand_id):
        self.reset(runtime_id, table_session, hand_id)
        for event in events:
            if event.get("action") in ("blind", "post_blind") or self.batch_a_exclusion(event) is None:
                self.accept_confirmed_action(event, runtime_id, table_session)

    @staticmethod
    def batch_a_exclusion(event):
        if event.get("action") in ("blind", "post_blind"):
            return None
        if event.get("action") not in BATCH_A_ACTIONS:
            return "action_outside_batch_a"
        if event.get("visualCandidate") or str(event.get("action") or "").endswith("_unresolved"):
            return "unconfirmed_candidate"
        if event.get("inferred") or event.get("chainStatus") == "rule_confirmed":
            return "rule_inference_outside_batch_a"
        if event.get("orderConflict"):
            return "legacy_order_conflict"
        return None

    @classmethod
    def prior_batch_a_exclusion(cls, events):
        return next((reason for item in events
                     if (reason := cls.batch_a_exclusion(item))), None)

    def snapshot(self, dealer_index, participants, seat_count, hand_id, street):
        return ActionChainEngine.rebuild(
            self.action_events, dealer_index, participants, seat_count,
            hand_id=hand_id, street=street)

    @staticmethod
    def compare(production, shadow):
        differences = {
            field: {"production": production.get(field), "shadow": shadow.get(field)}
            for field in COMPARISON_FIELDS
            if production.get(field) != shadow.get(field)
        }
        production_conflicts = [item.get("reason") for item in production.get("conflicts", ())]
        shadow_conflicts = [item.get("reason") for item in shadow.get("conflicts", ())]
        if production_conflicts != shadow_conflicts:
            differences["conflicts"] = {
                "production": production_conflicts, "shadow": shadow_conflicts}
        return {"matched": not differences, "differences": differences}
