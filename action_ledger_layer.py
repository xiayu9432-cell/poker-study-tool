from collections.abc import Mapping, MutableMapping, MutableSequence

from recognition_state import order_action_events


class ActionLedgerLayer:
    TERMINAL_ACTIONS = frozenset(("fold", "allin"))

    @staticmethod
    def signature(event: Mapping):
        return tuple(event.get(key) for key in (
            "handId", "street", "seat", "action", "amount", "increase"))

    @classmethod
    def has_confirmed_terminal(cls, events, event: Mapping) -> bool:
        return any(
            item.get("handId") == event.get("handId")
            and item.get("seat") == event.get("seat")
            and item.get("action") in cls.TERMINAL_ACTIONS
            and not item.get("inferred")
            and not item.get("visualCandidate")
            for item in reversed(events)
        )

    @classmethod
    def is_recent_duplicate(cls, events, event: Mapping, window_seconds=.75) -> bool:
        signature = cls.signature(event)
        observed_at = float(event.get("observedAt") or 0)
        return any(
            cls.signature(item) == signature
            and abs(float(item.get("observedAt") or 0) - observed_at) < window_seconds
            for item in events[-12:]
        )

    @staticmethod
    def normalize_street_time(events, event: MutableMapping) -> None:
        if event.get("historicalEvidenceBinding"):
            return
        seconds = [
            float(item["videoSecond"])
            for item in events
            if item.get("handId") == event.get("handId")
            and item.get("street") == event.get("street")
            and item.get("videoSecond") is not None
        ]
        if not seconds or event.get("videoSecond") is None:
            return
        latest = max(seconds)
        if float(event["videoSecond"]) >= latest:
            return
        event["rawObservedSecond"] = event["videoSecond"]
        event["videoSecond"] = latest
        event["timeAdjustedByActionOrder"] = True

    @staticmethod
    def record_participant(participants, seat_trackers, event: Mapping) -> int:
        seat_index = (event.get("seat") or 1) - 1
        hand_id = event.get("handId")
        if event.get("seat") and hand_id not in participants:
            participants[hand_id] = {
                index for index, item in seat_trackers.items()
                if item.get("occupancy") == "occupied"
                and item.get("handEligible", True)
                and item.get("joinedDuringHandId") != hand_id
                and item.get("excludedDuringHandId") != hand_id
            }
        if event.get("seat") and event.get("action") != "fold":
            tracker = seat_trackers.get(seat_index)
            if tracker is not None and tracker.get("joinedDuringHandId") == hand_id:
                return seat_index
            participants.setdefault(hand_id, set()).add(seat_index)
            if tracker is not None:
                excluded_at = tracker.get("excludedObservedAt")
                event_at = event.get("observedAt", event.get("videoSecond"))
                restores_current_state = (
                    tracker.get("excludedDuringHandId") != hand_id or
                    excluded_at is None or event_at is None or
                    float(event_at) >= float(excluded_at)
                )
                if restores_current_state:
                    tracker["handEligible"] = True
                    tracker.pop("excludedDuringHandId", None)
                    tracker.pop("excludedObservedAt", None)
                if tracker.get("joinedDuringHandId") != hand_id:
                    tracker.pop("joinedDuringHandId", None)
        return seat_index

    @staticmethod
    def reorder(events: MutableSequence, hand_dealers, participants, fallback_dealer,
                seat_count: int, include_event_seats=True) -> None:
        ordered = []
        for hand_id in sorted({item.get("handId", 0) for item in events}):
            hand_events = [item for item in events if item.get("handId", 0) == hand_id]
            dealer = hand_dealers.get(hand_id, fallback_dealer)
            eligible = set(participants.get(hand_id, ()))
            if include_event_seats:
                eligible.update((item.get("seat") or 1) - 1
                                for item in hand_events if item.get("seat"))
            ordered.extend(order_action_events(hand_events, dealer, eligible, seat_count))
        events[:] = ordered
