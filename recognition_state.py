import copy
import threading
import time

from action_chain_rules import seat_is_hand_eligible


def _event_second(event):
    video = event.get("videoSecond")
    recognized = event.get("recognizedAt")
    if isinstance(video, (int, float)):
        if (isinstance(recognized, (int, float)) and
                (float(video) > 1_000_000_000) == (float(recognized) > 1_000_000_000) and
                float(recognized) - float(video) > 2.0):
            return float(recognized)
        return float(video)
    for key in ("recognizedAt", "observedAt", "time"):
        value = event.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return float("inf")


class FieldState:
    def __init__(self):
        self._values = {}
        self._lock = threading.RLock()

    def commit(self, name, value, confidence, source, valid=True, **context):
        now = time.time()
        with self._lock:
            previous = self._values.get(name)
            if valid:
                self._values[name] = {
                    "value": copy.deepcopy(value), "confidence": round(float(confidence), 3),
                    "source": source, "updatedAt": now, "observedAt": context.get("observed_at", now),
                    "confirmedAt": context.get("confirmed_at", now), "stale": False,
                }
                for key in ("handId", "street", "frameSequence"):
                    if context.get(key) is not None:
                        self._values[name][key] = context[key]
            elif previous:
                previous["stale"] = True
                previous["rejectedAt"] = now
                previous["rejectedSource"] = source
                previous["rejectedConfidence"] = round(float(confidence), 3)
            return copy.deepcopy(self._values.get(name))

    def value(self, name, default=None, max_age=None):
        with self._lock:
            field = self._values.get(name)
            if not field:
                return default
            if max_age is not None and time.time() - field["updatedAt"] > max_age:
                return default
            return copy.deepcopy(field["value"])

    def snapshot(self):
        with self._lock:
            now = time.time()
            result = copy.deepcopy(self._values)
            for field in result.values():
                field["ageMs"] = round((now - field["updatedAt"]) * 1000)
            return result


class HandMachine:
    STREETS = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}

    def __init__(self):
        self.active = False
        self.hand_id = 0
        self.street = "waiting"
        self.board = []
        self.hero = []
        self.pot = None

    def update(self, participating, hero_cards, board_cards, pot, blind_count, force_new_hand=False,
               suppress_new_hand=False):
        board_count = len(board_cards)
        valid_board = board_count in self.STREETS
        cards_started = len(hero_cards) == 2 and len(self.hero) != 2
        cards_changed = (len(hero_cards) == 2 and len(self.hero) == 2 and len(self.board) >= 3 and
                         list(hero_cards) != list(self.hero) and board_count == 0)
        board_reset = len(self.board) >= 3 and board_count == 0
        pot_reset = pot is not None and self.pot is not None and pot < self.pot * .55
        new_hand = bool(not suppress_new_hand and participating and (force_new_hand or cards_started or cards_changed or
                        (board_count >= 3 and not self.active) or
                        (blind_count >= 2 and not self.active) or (board_reset and pot_reset)))
        street_changed = False
        if new_hand:
            self.hand_id += 1
            self.active = True
            self.street = "preflop"
            self.board = []
            self.hero = list(hero_cards)
        if valid_board and board_count >= len(self.board):
            next_street = self.STREETS[board_count]
            street_changed = next_street != self.street
            self.street = next_street
            self.board = list(board_cards)
            self.active = self.active or board_count >= 3
        if len(hero_cards) == 2:
            self.hero = list(hero_cards)
        if pot is not None:
            self.pot = pot
        return {"active": self.active, "id": self.hand_id, "street": self.street,
                "pot": self.pot, "boardCards": list(self.board), "heroCards": list(self.hero),
                "newHand": new_hand, "cardsChanged": cards_changed, "boardReset": board_reset,
                "streetChanged": street_changed}


def occupied_order(seats, dealer_index):
    occupied = [seat["index"] for seat in seats if seat.get("occupancy") == "occupied"]
    if dealer_index is None or dealer_index not in occupied:
        return []
    start = occupied.index(dealer_index)
    return occupied[start:] + occupied[:start]


def hand_eligible_seat(seat, evidenced_indices=()):
    return seat_is_hand_eligible(seat, evidenced_indices)


def position_for(seats, hero_index, dealer_index, straddle_index=None):
    order = occupied_order(seats, dealer_index)
    if hero_index not in order or len(order) < 2:
        return "unknown"
    distance = order.index(hero_index)
    labels = {
        2: ["dealer", "big_blind"],
        3: ["dealer", "small_blind", "big_blind"],
        4: ["dealer", "small_blind", "big_blind", "cutoff"],
        5: ["dealer", "small_blind", "big_blind", "under_the_gun", "cutoff"],
        6: ["dealer", "small_blind", "big_blind", "under_the_gun", "hijack", "cutoff"],
        7: ["dealer", "small_blind", "big_blind", "under_the_gun", "middle", "hijack", "cutoff"],
        8: ["dealer", "small_blind", "big_blind", "under_the_gun", "under_the_gun_plus_one", "middle", "hijack", "cutoff"],
    }
    position = labels.get(len(order), labels[8])[distance]
    return "straddle" if hero_index == straddle_index else position


STREET_ORDER = {"preflop": 0, "flop": 1, "turn": 2, "river": 3}


def minimum_raise_to(events, hand_id, street, big_blind):
    """Return the minimum legal cumulative street investment, or None if evidence is unsafe."""
    if not isinstance(big_blind, (int, float)) or big_blind <= 0:
        return None
    street_events = [event for event in events
                     if event.get("handId") == hand_id and event.get("street") == street]
    if any(event.get("orderConflict") or event.get("strategyEligible") is False
           for event in street_events):
        return None
    highest = 0.0
    minimum_increment = float(big_blind)
    for event in street_events:
        action = event.get("action")
        if action not in ("blind", "post_blind", "straddle", "call", "bet", "raise", "reraise", "allin"):
            continue
        amount = event.get("amount")
        if not isinstance(amount, (int, float)) or amount < 0:
            return None
        amount = float(amount)
        if action == "straddle" and amount > highest:
            highest = amount
            minimum_increment = max(minimum_increment, amount)
            continue
        if action in ("blind", "post_blind", "call"):
            highest = max(highest, amount)
            continue
        if amount <= highest:
            continue
        increment = amount - highest
        highest = amount
        if action != "allin" or increment + 1e-9 >= minimum_increment:
            minimum_increment = max(minimum_increment, increment)
    return round(highest + minimum_increment, 4)


def full_raise_count(events, hand_id, street, big_blind):
    """Count only bets/raises that meet the current minimum increment."""
    if not isinstance(big_blind, (int, float)) or big_blind <= 0:
        return None
    street_events = [event for event in events
                     if event.get("handId") == hand_id and event.get("street") == street]
    if any(event.get("orderConflict") or event.get("strategyEligible") is False
           for event in street_events):
        return None
    highest = 0.0
    minimum_increment = float(big_blind)
    count = 0
    for event in street_events:
        action = event.get("action")
        if action not in ("blind", "post_blind", "straddle", "call", "bet", "raise", "reraise", "allin"):
            continue
        amount = event.get("amount")
        if not isinstance(amount, (int, float)) or amount < 0:
            return None
        amount = float(amount)
        if action == "straddle" and amount > highest:
            highest = amount
            minimum_increment = max(minimum_increment, amount)
            continue
        if action in ("blind", "post_blind", "call") or amount <= highest:
            highest = max(highest, amount)
            continue
        increment = amount - highest
        highest = amount
        if increment + 1e-9 >= minimum_increment:
            count += 1
            minimum_increment = max(minimum_increment, increment)
    return count


def order_action_events(events, dealer_index, occupied_indices, seat_count):
    """Order observed actions by poker rules without inventing missing actions."""
    forced = [dict(event) for event in events if event.get("action") in ("blind", "post_blind", "straddle")]
    voluntary = [dict(event) for event in events if event.get("action") not in ("blind", "post_blind", "straddle")]
    active_for_forced = set(occupied_indices)
    small_blind = _next_seat(dealer_index, active_for_forced, seat_count)
    big_blind = _next_seat(small_blind, active_for_forced, seat_count)

    def forced_key(event):
        seat = (event.get("seat") or 1) - 1
        action = event.get("action")
        if action == "blind" and seat == small_blind:
            role = 0
        elif action == "blind" and seat == big_blind:
            role = 1
        elif action == "straddle":
            role = 2
        else:
            role = 3
        return (event.get("handId", 0), role, _event_second(event), event.get("seat", 0))

    result = sorted(forced, key=forced_key)
    for sequence, event in enumerate(result, 1):
        for key in ("missingBefore", "missingSeatsBefore", "orderConflictReason"):
            event.pop(key, None)
        event["orderConflict"] = False
        event["sequence"] = sequence
    hands = sorted({event.get("handId", 0) for event in voluntary})
    for hand_id in hands:
        hand_events = [event for event in voluntary if event.get("handId", 0) == hand_id]
        hand_straddles = [event for event in forced if event.get("handId", 0) == hand_id and
                          event.get("action") == "straddle"]
        preflop_anchor = ((hand_straddles[-1].get("seat") or 1) - 1) if hand_straddles else None
        active = set(occupied_indices)
        for street in ("preflop", "flop", "turn", "river"):
            pending = sorted([event for event in hand_events if event.get("street") == street],
                             key=lambda event: (_event_second(event), event.get("time", 0)))
            if not pending:
                continue
            start = (_next_seat(preflop_anchor, active, seat_count)
                     if street == "preflop" and preflop_anchor is not None
                     else _street_start(dealer_index, active, seat_count, street))
            expected = start
            round_number = 1
            street_result = []
            awaiting = set(active)
            highest_amount = max(
                (float(event.get("amount") or 0) for event in forced
                 if event.get("handId", 0) == hand_id and
                 event.get("street", "preflop") == street),
                default=0.0,
            )
            while pending and expected is not None and awaiting:
                earliest = pending[0]
                earliest_second = _event_second(earliest)
                indistinguishable = [event for event in pending
                                     if (event.get("frameSequence") is not None and
                                         event.get("frameSequence") == earliest.get("frameSequence")) or
                                     (_event_second(event) == earliest_second) or
                                     abs(_event_second(event) - earliest_second) <= 2.0]
                match = next((event for event in indistinguishable
                              if event.get("seat") == expected + 1), None)
                if match is None:
                    match = next((event for event in pending
                                  if event.get("seat") == expected + 1 and
                                  event.get("action") == "fold" and
                                  earliest.get("action") == "fold"), None)
                if match is None:
                    match = min(indistinguishable, key=lambda event: (
                        (((event.get("seat") or 1) - 1 - expected) % seat_count),
                        _event_second(event), event.get("time", 0)))
                for key in ("missingBefore", "missingSeatsBefore", "orderConflictReason"):
                    match.pop(key, None)
                observed = (match.get("seat") or 1) - 1
                if observed != expected:
                    missing = []
                    cursor = expected
                    for _ in range(seat_count):
                        if cursor == observed:
                            break
                        if cursor in awaiting:
                            missing.append(cursor + 1)
                        cursor = (cursor + 1) % seat_count
                    expected = observed
                    if missing:
                        match["missingBefore"] = True
                        match["missingSeatsBefore"] = missing
                pending.remove(match)
                match["actionRound"] = None if match.get("missingBefore") else round_number
                match["orderConflict"] = bool(match.get("missingBefore"))
                street_result.append(match)
                action = match.get("action")
                amount = match.get("amount")
                if action == "fold":
                    active.discard(expected)
                    awaiting.discard(expected)
                elif action == "allin":
                    if isinstance(amount, (int, float)) and float(amount) > highest_amount + .01:
                        round_number += 1
                        awaiting = set(active) - {expected}
                        highest_amount = float(amount)
                    active.discard(expected)
                    awaiting.discard(expected)
                elif action in ("raise", "reraise", "bet"):
                    raises_price = (isinstance(amount, (int, float)) and
                                    float(amount) > highest_amount + .01)
                    if raises_price:
                        round_number += 1
                        awaiting = set(active) - {expected}
                        highest_amount = float(amount)
                    else:
                        awaiting.discard(expected)
                else:
                    awaiting.discard(expected)
                expected = _next_seat(expected, awaiting, seat_count)
            for event in pending:
                event["actionRound"] = None
                event["orderConflict"] = True
                event.setdefault("missingSeatsBefore", [])
                event["orderConflictReason"] = "前序动作缺失或识别顺序与规则冲突"
            street_result.extend(pending)
            for sequence, event in enumerate(street_result, 1):
                event["sequence"] = sequence
            result.extend(street_result)
    ordered = sorted(result, key=lambda event: (event.get("handId", 0),
                  STREET_ORDER.get(event.get("street"), -1),
                  0 if event.get("action") in ("blind", "post_blind", "straddle") else 1,
                  event.get("sequence", 0), event.get("videoSecond", 0)))
    sequence_by_street = {}
    for event in ordered:
        key = (event.get("handId", 0), event.get("street"))
        sequence_by_street[key] = sequence_by_street.get(key, 0) + 1
        event["sequence"] = sequence_by_street[key]
    return annotate_action_ledger(ordered, occupied_indices, seat_count)


def annotate_action_ledger(events, occupied_indices, seat_count):
    """Attach auditable betting state without inventing missing actions."""
    investments = {}
    active = set(occupied_indices)
    current_hand = current_street = None
    highest = 0.0
    awaiting = set()
    for event in events:
        hand_id, street = event.get("handId"), event.get("street")
        if hand_id != current_hand:
            current_hand, current_street = hand_id, None
            active = set(occupied_indices)
        if street != current_street:
            current_street = street
            investments = {seat: 0.0 for seat in active}
            highest = 0.0
            awaiting = set(active)
        seat = (event.get("seat") or 0) - 1
        action = event.get("action")
        amount, increase = event.get("amount"), event.get("increase")
        prior_highest = highest
        event["priorHighestBet"] = round(prior_highest, 4)
        if action in ("blind", "post_blind", "straddle", "call", "bet", "raise", "reraise", "allin"):
            if isinstance(amount, (int, float)):
                investments[seat] = max(investments.get(seat, 0.0), float(amount))
            elif isinstance(increase, (int, float)):
                investments[seat] = investments.get(seat, 0.0) + float(increase)
            highest = max(highest, investments.get(seat, 0.0))
        raises_price = (action in ("bet", "raise", "reraise", "allin") and
                        investments.get(seat, 0.0) > prior_highest + .01)
        if raises_price:
            awaiting = set(active) - {seat}
        else:
            awaiting.discard(seat)
        if action in ("fold", "allin"):
            active.discard(seat)
            awaiting.discard(seat)
        event["currentHighestBet"] = round(highest, 4)
        event["streetInvestments"] = {str(index + 1): round(value, 4)
                                      for index, value in sorted(investments.items())}
        event["unactedSeats"] = [candidate + 1 for offset in range(1, seat_count + 1)
                                  for candidate in [(seat + offset) % seat_count]
                                  if candidate in awaiting]
        event["unactedAfter"] = len(event["unactedSeats"])
        if event.get("orderConflict"):
            event["chainStatus"] = "unresolved"
            event["strategyEligible"] = False
        else:
            if event.get("chainStatus") == "unresolved":
                event["chainStatus"] = "rule_confirmed"
            else:
                event.setdefault("chainStatus", "rule_confirmed")
            event["strategyEligible"] = not event.get("visualCandidate") and not str(
                event.get("action", "")).endswith("_unresolved")
    return events


def _street_start(dealer, active, seat_count, street):
    if dealer is None or not active:
        return None
    if street == "preflop":
        small = _next_seat(dealer, active, seat_count)
        big = _next_seat(small, active, seat_count)
        return _next_seat(big, active, seat_count)
    return _next_seat(dealer, active, seat_count)


def _next_seat(current, active, seat_count):
    if current is None or not active:
        return None
    for offset in range(1, seat_count + 1):
        candidate = (current + offset) % seat_count
        if candidate in active:
            return candidate
    return None
