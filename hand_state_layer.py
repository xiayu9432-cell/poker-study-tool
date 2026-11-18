from collections.abc import Mapping

from action_chain_rules import provable_prior_street_action


class HandStateLayer:
    @staticmethod
    def eligible_indices(hand_id, participants, seat_trackers):
        snapshot = participants.get(hand_id)
        if snapshot:
            return {index for index in snapshot
                    if seat_trackers.get(index, {}).get("excludedDuringHandId") != hand_id}
        return {index for index, tracker in seat_trackers.items()
                if tracker.get("occupancy") == "occupied" and
                tracker.get("handEligible", True) and
                tracker.get("excludedDuringHandId") != hand_id}

    @staticmethod
    def next_actor(current, count, eligible, terminal=()):
        terminal = set(terminal)
        for offset in range(1, count + 1):
            candidate = (current + offset) % count
            if candidate in eligible and candidate not in terminal:
                return candidate
        return None

    @staticmethod
    def prior_street_proof(action_log, later_event: Mapping, prior: Mapping):
        previous = next((item for item in reversed(action_log)
                         if item.get("handId") == later_event.get("handId") and
                         item.get("street") == prior.get("street")), None)
        return provable_prior_street_action(previous or {}, later_event, prior.get("street"))
