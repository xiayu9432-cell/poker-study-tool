from copy import deepcopy


STREETS = ("preflop", "flop", "turn", "river")
AGGRESSIVE_ACTIONS = frozenset(("bet", "raise", "reraise", "allin"))
FORCED_ACTIONS = frozenset(("blind", "post_blind", "straddle"))


class ActionTimeline:
    """Keep auditable hand, street, and reopened-action time windows."""

    def __init__(self):
        self.current = None

    def reset(self):
        self.current = None

    @staticmethod
    def _boundary(observed_at=None, frame_sequence=None, video_second=None):
        return {
            "at": observed_at,
            "frameSequence": frame_sequence,
            "videoSecond": video_second,
        }

    @staticmethod
    def _apply_boundary(target, prefix, boundary):
        target[f"{prefix}At"] = boundary.get("at")
        target[f"{prefix}FrameSequence"] = boundary.get("frameSequence")
        target[f"{prefix}VideoSecond"] = boundary.get("videoSecond")

    def start_hand(self, hand_id, observed_at=None, frame_sequence=None,
                   video_second=None):
        if (self.current and self.current.get("handId") == hand_id and
                self.current.get("endedAt") is None):
            return False
        boundary = self._boundary(observed_at, frame_sequence, video_second)
        self.current = {"handId": hand_id, "streets": {}}
        self._apply_boundary(self.current, "started", boundary)
        self._start_street("preflop", boundary)
        return True

    def close_hand(self, observed_at=None, frame_sequence=None, video_second=None):
        if not self.current:
            return None
        boundary = self._boundary(observed_at, frame_sequence, video_second)
        open_street = next((item for item in reversed(list(self.current["streets"].values()))
                            if item.get("endedAt") is None), None)
        if open_street:
            self._close_street(open_street, boundary)
        self._apply_boundary(self.current, "ended", boundary)
        return self.snapshot()

    def transition_street(self, hand_id, from_street, to_street, observed_at=None,
                          frame_sequence=None, video_second=None):
        if not self.current or self.current.get("handId") != hand_id:
            self.start_hand(hand_id, observed_at, frame_sequence, video_second)
        boundary = self._boundary(observed_at, frame_sequence, video_second)
        previous = self.current["streets"].get(from_street)
        if previous and previous.get("endedAt") is None:
            self._close_street(previous, boundary)
        for item in self.current["streets"].values():
            if item.get("street") != to_street and item.get("endedAt") is None:
                self._close_street(item, boundary)
        if to_street not in self.current["streets"]:
            self._start_street(to_street, boundary)
        return self.current["streets"].get(to_street)

    def _start_street(self, street, boundary):
        item = {"street": street, "actionRounds": []}
        self._apply_boundary(item, "started", boundary)
        item.update(endedAt=None, endedFrameSequence=None, endedVideoSecond=None)
        self.current["streets"][street] = item
        self._replace_rounds(item, [])
        return item

    def _close_street(self, street_item, boundary):
        self._apply_boundary(street_item, "ended", boundary)
        rounds = street_item.get("actionRounds") or []
        if rounds and rounds[-1].get("endedAt") is None:
            self._apply_boundary(rounds[-1], "ended", boundary)

    @staticmethod
    def _event_boundary(event):
        return {
            "at": event.get("capturedObservedAt", event.get("observedAt")),
            "frameSequence": event.get("capturedFrameSequence", event.get("frameSequence")),
            "videoSecond": event.get("rawObservedSecond", event.get("videoSecond")),
        }

    @staticmethod
    def _raises_price(event):
        if event.get("action") not in AGGRESSIVE_ACTIONS:
            return False
        amount = event.get("amount")
        prior = event.get("priorHighestBet")
        if isinstance(amount, (int, float)) and isinstance(prior, (int, float)):
            return float(amount) > float(prior) + .01
        return True

    def _replace_rounds(self, street_item, events):
        previous_rounds = {
            item.get("round"): item for item in street_item.get("actionRounds", [])
            if isinstance(item.get("round"), int)
        }
        valid = [event for event in events
                 if isinstance(event.get("actionRound"), int) and
                 event.get("action") not in FORCED_ACTIONS]
        chronological = sorted(
            (event for event in events if event.get("action") not in FORCED_ACTIONS),
            key=lambda event: (
                event.get("rawObservedSecond", event.get("videoSecond"))
                if event.get("rawObservedSecond", event.get("videoSecond")) is not None
                else float("inf"),
                event.get("capturedFrameSequence", event.get("frameSequence"))
                if event.get("capturedFrameSequence", event.get("frameSequence")) is not None
                else float("inf"),
                event.get("capturedObservedAt", event.get("observedAt"))
                if event.get("capturedObservedAt", event.get("observedAt")) is not None
                else float("inf"),
            ),
        )
        if chronological:
            earliest = self._event_boundary(chronological[0])
            for suffix, key in (("At", "at"), ("FrameSequence", "frameSequence"),
                                ("VideoSecond", "videoSecond")):
                current = street_item.get(f"started{suffix}")
                value = earliest.get(key)
                if value is not None and (current is None or float(value) < float(current)):
                    street_item[f"started{suffix}"] = value
        price_openers = []
        highest_price = 0.0
        for event in chronological:
            if event.get("action") not in AGGRESSIVE_ACTIONS:
                continue
            amount = event.get("amount")
            if isinstance(amount, (int, float)):
                if float(amount) <= highest_price + .01:
                    continue
                highest_price = float(amount)
            elif not self._raises_price(event):
                continue
            price_openers.append(event)
        highest_round = max((event["actionRound"] for event in valid), default=1)
        highest_round = max(
            highest_round,
            len(price_openers) + 1,
            max((event["actionRound"] + 1 for event in valid
                 if self._raises_price(event)), default=1),
        )
        transitions = {
            round_number: (self._event_boundary(opener), opener)
            for round_number, opener in enumerate(price_openers, 2)
        }
        for round_number in range(2, highest_round + 1):
            first_index = next((index for index, event in enumerate(valid)
                                if event["actionRound"] == round_number), None)
            if first_index is None:
                continue
            opener = next((event for event in reversed(valid[:first_index])
                           if event.get("actionRound") == round_number - 1 and
                           self._raises_price(event)), None)
            if opener is None:
                established = previous_rounds.get(round_number, {}).get("openedBy") or {}
                opener = next((event for event in valid
                               if self._raises_price(event) and
                               event.get("seat") == established.get("seat") and
                               event.get("action") == established.get("action") and
                               event.get("amount") == established.get("amount")), None)
            if opener and round_number not in transitions:
                transitions[round_number] = (self._event_boundary(opener), opener)
        rounds = []
        for round_number in range(1, highest_round + 1):
            if round_number == 1:
                start = {
                    "at": street_item.get("startedAt"),
                    "frameSequence": street_item.get("startedFrameSequence"),
                    "videoSecond": street_item.get("startedVideoSecond"),
                }
                opener = None
            else:
                start, opener = transitions.get(round_number, ({
                    "at": None, "frameSequence": None, "videoSecond": None,
                }, None))
            item = {
                "round": round_number,
                "windowId": (f"{self.current.get('handId')}:{street_item['street']}:"
                             f"{round_number}"),
                "eventCount": sum(event.get("actionRound") == round_number
                                  for event in valid),
                "seats": [event.get("seat") for event in valid
                          if event.get("actionRound") == round_number],
            }
            self._apply_boundary(item, "started", start)
            if opener:
                item["openedBy"] = {
                    "seat": opener.get("seat"), "action": opener.get("action"),
                    "amount": opener.get("amount"), "sequence": opener.get("sequence"),
                }
            rounds.append(item)
        for index, item in enumerate(rounds):
            if index + 1 < len(rounds):
                next_item = rounds[index + 1]
                end = {
                    "at": next_item.get("startedAt"),
                    "frameSequence": next_item.get("startedFrameSequence"),
                    "videoSecond": next_item.get("startedVideoSecond"),
                }
                self._apply_boundary(item, "ended", end)
                item["closedBy"] = dict(next_item.get("openedBy") or {})
            else:
                end = {
                    "at": street_item.get("endedAt"),
                    "frameSequence": street_item.get("endedFrameSequence"),
                    "videoSecond": street_item.get("endedVideoSecond"),
                }
                self._apply_boundary(item, "ended", end)
        street_item["actionRounds"] = rounds

    def rebuild(self, events, hand_id, street):
        if not self.current or self.current.get("handId") != hand_id:
            return None
        street_item = self.current["streets"].get(street)
        if not street_item:
            return None
        relevant = [event for event in events
                    if event.get("handId") == hand_id and event.get("street") == street]
        self._replace_rounds(street_item, relevant)
        for event in relevant:
            match = self.match_event(event)
            event["timeWindowId"] = match.get("windowId") if match else None
            event["timeMatchedActionRound"] = match.get("round") if match else None
            event["timeWindowConflict"] = bool(
                match and isinstance(event.get("actionRound"), int) and
                match.get("round") != event.get("actionRound")
            )
        street_item["unmatchedActionCount"] = sum(
            event.get("timeMatchedActionRound") is None for event in relevant
            if event.get("action") not in FORCED_ACTIONS)
        return deepcopy(street_item)

    @staticmethod
    def _contains(item, point, start_key, end_key):
        value = point.get(start_key)
        start = item.get(f"started{start_key}")
        end = item.get(f"ended{end_key}")
        if value is None or start is None:
            return False
        return float(value) >= float(start) and (end is None or float(value) <= float(end))

    def match_point(self, hand_id, street, observed_at=None, frame_sequence=None,
                    video_second=None, rule_round=None):
        if not self.current or self.current.get("handId") != hand_id:
            return None
        street_item = self.current["streets"].get(street)
        if not street_item:
            return None
        point = {"At": observed_at, "FrameSequence": frame_sequence,
                 "VideoSecond": video_second}
        rounds = street_item.get("actionRounds") or []
        candidates = []
        for item in rounds:
            if (self._contains(item, point, "FrameSequence", "FrameSequence") or
                    self._contains(item, point, "VideoSecond", "VideoSecond") or
                    self._contains(item, point, "At", "At")):
                candidates.append(item)
        if rule_round is not None:
            rule_match = next((item for item in candidates
                               if item.get("round") == rule_round), None)
            if rule_match:
                return dict(rule_match)
        return dict(candidates[-1]) if candidates else None

    def match_event(self, event):
        boundary = self._event_boundary(event)
        return self.match_point(
            event.get("handId"), event.get("street"), boundary.get("at"),
            boundary.get("frameSequence"), boundary.get("videoSecond"),
            event.get("actionRound"),
        )

    def capture_context(self, hand_id, street, observed_at=None,
                        frame_sequence=None, video_second=None):
        match = self.match_point(hand_id, street, observed_at, frame_sequence, video_second)
        if match:
            return {"actionRound": match.get("round"), "windowId": match.get("windowId")}
        return {"actionRound": None, "windowId": None}

    def street_for_point(self, hand_id, observed_at=None, frame_sequence=None,
                         video_second=None):
        if not self.current or self.current.get("handId") != hand_id:
            return None
        point = {"At": observed_at, "FrameSequence": frame_sequence,
                 "VideoSecond": video_second}
        streets = list(self.current.get("streets", {}).values())
        for item in reversed(streets):
            if (self._contains(item, point, "FrameSequence", "FrameSequence") or
                    self._contains(item, point, "VideoSecond", "VideoSecond") or
                    self._contains(item, point, "At", "At")):
                return item.get("street")
        return None

    def snapshot(self):
        return deepcopy(self.current)
