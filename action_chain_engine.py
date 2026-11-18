from collections.abc import Iterable, Mapping

from action_ledger_layer import ActionLedgerLayer


STREETS = ("preflop", "flop", "turn", "river")
FORCED_ACTIONS = frozenset(("blind", "post_blind", "straddle"))
AGGRESSIVE_ACTIONS = frozenset(("bet", "raise", "reraise", "allin"))
MONEY_ACTIONS = FORCED_ACTIONS | AGGRESSIVE_ACTIONS | frozenset(("call",))


class ActionChainEngine:
    """Rebuild one hand from confirmed observations and poker rules."""

    @staticmethod
    def _next(current, seats, seat_count):
        if current is None or not seats:
            return None
        for offset in range(1, seat_count + 1):
            candidate = (current + offset) % seat_count
            if candidate in seats:
                return candidate
        return None

    @classmethod
    def _street_start(cls, dealer, seats, seat_count, street, forced):
        if not seats or dealer is None:
            return None
        if street == "preflop":
            live = [event for event in forced if event.get("action") == "straddle"]
            if live:
                return cls._next(int(live[-1]["seat"]) - 1, seats, seat_count)
            small = cls._next(dealer, seats, seat_count)
            big = cls._next(small, seats, seat_count)
            return cls._next(big, seats, seat_count)
        return cls._next(dealer, seats, seat_count)

    @staticmethod
    def _amount(event, previous):
        amount = event.get("amount")
        if isinstance(amount, (int, float)):
            return max(float(previous), float(amount))
        increase = event.get("increase")
        if isinstance(increase, (int, float)):
            return max(float(previous), float(previous) + float(increase))
        return None

    @classmethod
    def rebuild(cls, events: Iterable[Mapping], dealer_index: int | None,
                participants: Iterable[int], seat_count: int, hand_id=None,
                street=None):
        seats = {int(seat) for seat in participants if 0 <= int(seat) < seat_count}
        hand_events = [dict(event) for event in events
                       if hand_id is None or event.get("handId") == hand_id]
        if hand_id is None and hand_events:
            hand_id = hand_events[-1].get("handId")
            hand_events = [event for event in hand_events if event.get("handId") == hand_id]
        if hand_id is not None:
            ActionLedgerLayer.reorder(
                hand_events, {hand_id: dealer_index}, {hand_id: set(seats)},
                dealer_index, seat_count, include_event_seats=False)
        conflicts = []
        folded = set()
        allin = set()
        snapshots = {}
        target_street = street if street in STREETS else None

        for current_street in STREETS:
            if target_street and STREETS.index(current_street) > STREETS.index(target_street):
                break
            current = [event for event in hand_events if event.get("street", "preflop") == current_street]
            forced = [event for event in current if event.get("action") in FORCED_ACTIONS]
            voluntary = [event for event in current if event.get("action") not in FORCED_ACTIONS]
            in_hand = seats - folded
            can_act = in_hand - allin
            investments = {seat: 0.0 for seat in in_hand}
            highest = 0.0
            full_raise_size = 0.0
            for event in forced:
                seat = int(event.get("seat") or 0) - 1
                if seat not in in_hand:
                    continue
                amount = cls._amount(event, investments.get(seat, 0.0))
                if amount is None:
                    conflicts.append({"street": current_street, "seat": seat + 1,
                                      "reason": "forced_amount_missing"})
                    continue
                investments[seat] = amount
                if amount > highest:
                    highest = amount
                    if current_street == "preflop":
                        full_raise_size = max(full_raise_size, amount)

            awaiting = set(can_act)
            expected = cls._street_start(dealer_index, can_act, seat_count,
                                         current_street, forced)
            round_number = 1
            for event in voluntary:
                seat = int(event.get("seat") or 0) - 1
                action = str(event.get("action") or "")
                if event.get("orderConflict"):
                    conflicts.append({
                        "street": current_street, "seat": seat + 1,
                        "reason": "legacy_order_conflict",
                        "missingSeats": list(event.get("missingSeatsBefore") or ()),
                    })
                if (seat not in can_act or event.get("visualCandidate") or
                        action.endswith("_unresolved")):
                    conflicts.append({"street": current_street, "seat": seat + 1,
                                      "reason": "actor_not_eligible"})
                    continue
                if expected is not None and seat != expected:
                    missing = []
                    cursor = expected
                    for _ in range(seat_count):
                        if cursor == seat:
                            break
                        if cursor in awaiting:
                            missing.append(cursor + 1)
                        cursor = (cursor + 1) % seat_count
                    conflicts.append({"street": current_street, "seat": seat + 1,
                                      "reason": "action_order_gap", "missingSeats": missing})
                prior = investments.get(seat, 0.0)
                amount = cls._amount(event, prior) if action in MONEY_ACTIONS else prior
                if action in MONEY_ACTIONS and amount is None:
                    conflicts.append({"street": current_street, "seat": seat + 1,
                                      "reason": "action_amount_missing"})
                    continue
                if action == "check" and prior < highest - .001:
                    conflicts.append({"street": current_street, "seat": seat + 1,
                                      "reason": "illegal_check"})
                elif action == "call" and amount < highest - .001:
                    conflicts.append({"street": current_street, "seat": seat + 1,
                                      "reason": "short_call_without_allin"})
                elif action in AGGRESSIVE_ACTIONS and amount <= highest + .001 and action != "allin":
                    conflicts.append({"street": current_street, "seat": seat + 1,
                                      "reason": "raise_does_not_increase_price"})

                if amount is not None:
                    investments[seat] = amount
                prior_highest = highest
                raises_price = action in AGGRESSIVE_ACTIONS and amount is not None and amount > highest + .001
                if raises_price:
                    increment = amount - highest
                    highest = amount
                    full_raise = prior_highest <= .001 or increment + .001 >= max(.001, full_raise_size)
                    if full_raise:
                        full_raise_size = increment
                        round_number += 1
                    awaiting = {candidate for candidate in can_act - {seat}
                                if investments.get(candidate, 0.0) < highest - .001 or full_raise}
                else:
                    awaiting.discard(seat)

                if action == "fold":
                    folded.add(seat)
                    can_act.discard(seat)
                    awaiting.discard(seat)
                elif action == "allin":
                    allin.add(seat)
                    can_act.discard(seat)
                    awaiting.discard(seat)
                expected = cls._next(seat, awaiting, seat_count)

            snapshots[current_street] = {
                "street": current_street,
                "nextActor": expected,
                "nextActorSeat": None if expected is None else expected + 1,
                "awaitingSeats": [seat + 1 for seat in sorted(awaiting)],
                "currentPrice": round(highest, 6),
                "investments": {str(seat + 1): round(value, 6)
                                for seat, value in sorted(investments.items())},
                "round": round_number,
                "roundClosed": not awaiting,
                "activeSeats": [seat + 1 for seat in sorted(in_hand - folded)],
                "canActSeats": [seat + 1 for seat in sorted(can_act)],
            }

        selected = snapshots.get(target_street) if target_street else (
            snapshots.get(STREETS[max((STREETS.index(name) for name in snapshots), default=0)]))
        selected = dict(selected or {
            "street": target_street, "nextActor": None, "nextActorSeat": None,
            "awaitingSeats": [], "currentPrice": 0.0, "investments": {},
            "round": 1, "roundClosed": False, "activeSeats": [], "canActSeats": [],
        })
        current_conflicts = [item for item in conflicts
                             if item.get("street") == selected.get("street")]
        historical_conflicts = [item for item in conflicts
                                if item.get("street") != selected.get("street")]
        selected.update(
            handId=hand_id,
            reliable=not current_conflicts,
            conflicts=current_conflicts,
            historicalConflicts=historical_conflicts,
            streets=snapshots,
        )
        return selected
