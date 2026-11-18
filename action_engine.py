import json
import time
from collections.abc import Iterable, Mapping
from copy import deepcopy
from pathlib import Path

from action_chain_engine import ActionChainEngine
from action_ledger_layer import ActionLedgerLayer
from hand_state_layer import HandStateLayer
from recognition_state import full_raise_count, minimum_raise_to


ORDINARY_ACTIONS = frozenset((
    "fold", "check", "call", "bet", "raise", "reraise",
))
FORCED_CONTEXT_ACTIONS = frozenset(("blind", "post_blind"))


class ActionEventStore:
    PROJECTION_FIELDS = (
        "eventId", "handId", "street", "seat", "action", "amount", "increase",
        "confidence", "evidence", "chainStatus", "strategyEligible",
        "orderConflict", "inferred", "frameSequence", "observedAt", "videoSecond",
        "actionRound", "sequence", "pendingExactAmount", "amountLowerBound",
    )

    def __init__(self, path=None):
        self._records = []
        self._projection = {}
        self._next_event_id = 1
        self._path = Path(path) if path else None
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if self._path.exists():
                for line in self._path.read_text(encoding="utf-8").splitlines():
                    try:
                        record = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(record, dict):
                        self._records.append(record)

    def append(self, kind, event, reason=None, prior_event=None):
        record = {
            "ledgerSequence": len(self._records) + 1,
            "kind": kind,
            "recordedAt": time.time(),
            "event": deepcopy(dict(event)),
        }
        if reason:
            record["reason"] = reason
        if prior_event is not None:
            record["priorEvent"] = deepcopy(dict(prior_event))
        self._records.append(record)
        if self._path is not None:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return deepcopy(record)

    def accepted(self, event):
        return self.append("accepted", event)

    def corrected(self, prior_event, event, reason):
        return self.append("corrected", event, reason, prior_event)

    def retracted(self, event, reason):
        return self.append("retracted", event, reason)

    def sync_projection(self, events, reason="formal_projection_sync"):
        current = {}
        appended = []
        for event in events:
            event_id = event.get("eventId")
            if not event_id:
                event_id = f"action-{time.time_ns()}-{self._next_event_id}"
                self._next_event_id += 1
                event["eventId"] = event_id
            snapshot = self._projection_snapshot(event)
            current[event_id] = snapshot
            prior = self._projection.get(event_id)
            if prior is None:
                appended.append(self.accepted(snapshot))
            elif prior != snapshot:
                appended.append(self.corrected(prior, snapshot, reason))
        for event_id, prior in self._projection.items():
            if event_id not in current:
                appended.append(self.retracted(prior, reason))
        self._projection = current
        return appended

    def close_projection(self):
        self._projection.clear()

    def _projection_snapshot(self, event):
        return deepcopy({key: event.get(key) for key in self.PROJECTION_FIELDS
                         if key in event})

    def snapshot(self):
        return deepcopy(self._records)

    def count(self):
        return len(self._records)


class ActionEngine:
    SUPPORTED_ACTIONS = ORDINARY_ACTIONS | FORCED_CONTEXT_ACTIONS | frozenset((
        "straddle", "allin",
    ))

    @staticmethod
    def select_fold_promotions(candidates, hand_id, street, expected_index,
                               seat_count, eligible, stop_before=None,
                               require_text=False, current_second=None,
                               terminal=()):
        if expected_index is None:
            return {"candidates": [], "nextExpected": None}
        selected = []
        expected = expected_index
        terminal = set(terminal or ())
        eligible = set(eligible or range(seat_count))
        for _ in range(seat_count):
            if stop_before is not None and expected == stop_before:
                break
            candidate = next((item for item in reversed(candidates)
                              if item.get("handId") == hand_id and
                              item.get("street") == street and
                              item.get("seat") == expected + 1 and
                              item.get("action") == "fold" and
                              item.get("evidenceFrames", 0) >= 3 and
                              not item.get("promoted") and
                              not item.get("expired") and
                              ((item.get("evidenceSignals", {}).get("avatarText") and
                                (not require_text or current_second is None or
                                 item.get("lastSeenSecond", item.get("videoSecond")) is None or
                                 current_second - item.get(
                                     "lastSeenSecond", item.get("videoSecond")) <= 2.0)) or
                               (not require_text and item.get("evidenceFrames", 0) >= 5 and
                                item.get("evidenceSignals", {}).get("avatarModel")) or
                               (not require_text and item.get("evidenceFrames", 0) >= 8 and
                                item.get("evidenceSignals", {}).get("contrastDrop")))), None)
            if candidate is None and require_text:
                break
            if candidate is not None:
                selected.append(candidate)
                terminal.add(expected)
            next_expected = HandStateLayer.next_actor(
                expected, seat_count, eligible,
                terminal if require_text else ())
            if next_expected is None:
                expected = None
                break
            expected = next_expected
        return {"candidates": selected, "nextExpected": expected}

    @staticmethod
    def select_rule_proven_checks(event, events, seat_trackers, expected_index,
                                  seat_count, eligible, terminal=()):
        if (event.get("inferred") or event.get("street") == "preflop" or
                event.get("action") not in ("bet", "raise", "reraise", "allin") or
                float(event.get("confidence") or 0) < .85 or
                not event.get("seat") or expected_index is None):
            return []
        observed_index = int(event["seat"]) - 1
        if expected_index == observed_index:
            return []
        current = [item for item in events
                   if item.get("handId") == event.get("handId") and
                   item.get("street") == event.get("street")]
        highest = max((float(item.get("amount") or 0) for item in current
                       if item.get("action") in ("bet", "raise", "reraise", "allin")),
                      default=0.0)
        if highest > .001:
            return []
        selected = []
        expected = expected_index
        terminal = set(terminal or ())
        eligible = set(eligible or range(seat_count))
        for _ in range(seat_count):
            if expected is None or expected == observed_index:
                break
            tracker = seat_trackers.get(expected, {})
            if (tracker.get("occupancy") != "occupied" or
                    not tracker.get("handEligible", True) or
                    tracker.get("visualState") in ("fold", "allin", "away", "empty")):
                break
            selected.append(expected)
            expected = HandStateLayer.next_actor(
                expected, seat_count, eligible, terminal)
        return selected

    @staticmethod
    def prove_prior_street_action(events, later_event, prior):
        previous = next((item for item in reversed(events)
                         if item.get("handId") == later_event.get("handId") and
                         item.get("street") == prior.get("street")), None)
        return HandStateLayer.prior_street_proof(
            events, later_event, prior) if previous is not None else None

    @staticmethod
    def prove_hero_check_before_later_action(event, context, events,
                                             hero_index, expected_index,
                                             tracker_amount):
        if (not context or event.get("seat") == hero_index + 1 or
                event.get("handId") != context.get("handId") or
                event.get("street") != context.get("street") or
                not any(button.get("kind") == "check"
                        for button in context.get("buttons", [])) or
                expected_index != hero_index):
            return False
        prior_amount = float(context.get("priorAmount") or 0)
        hero_amount = max(
            (float(item.get("amount") or 0) for item in events
             if item.get("handId") == event.get("handId") and
             item.get("street") == event.get("street") and
             item.get("seat") == hero_index + 1 and
             item.get("action") in ("call", "bet", "raise", "reraise", "allin")),
            default=0.0)
        if max(hero_amount, float(tracker_amount or 0)) > prior_amount + max(.01, prior_amount * .02):
            return False
        event_second = event.get("videoSecond", event.get("observedAt"))
        context_second = context.get("videoSecond", context.get("observedAt"))
        return not (event_second is not None and context_second is not None and
                    float(event_second) < float(context_second))

    @staticmethod
    def select_unmatched_price_folds(event, missing_seats, events, seat_trackers):
        if (event.get("action") in ("fold", "blind", "post_blind", "straddle") or
                float(event.get("confidence") or 0) < .85):
            return []
        current = [item for item in events
                   if item.get("handId") == event.get("handId") and
                   item.get("street") == event.get("street")]
        prior_price = max((float(item.get("amount") or 0) for item in current
                           if item is not event and
                           item.get("action") in ("blind", "post_blind", "straddle",
                                                  "bet", "raise", "reraise", "allin")),
                          default=0.0)
        selected = []
        for seat in missing_seats or ():
            tracker = seat_trackers.get(int(seat) - 1, {})
            invested = float(tracker.get("stableBet") or 0)
            if (tracker.get("occupancy") == "occupied" and
                    tracker.get("handEligible", True) and
                    tracker.get("visualState") != "allin" and
                    invested < prior_price - max(.001, prior_price * .02)):
                selected.append({"seat": int(seat), "amount": invested})
        return selected

    @staticmethod
    def select_retractable_check_for_allin_call(buttons, events, hand_id, street,
                                                hero_index, seat_count, eligible,
                                                terminal=()):
        if not any(button.get("kind") == "call" and
                   (button.get("value") == "allin" or button.get("allinCall"))
                   for button in buttons):
            return None
        current = [item for item in events
                   if item.get("handId") == hand_id and item.get("street") == street and
                   item.get("action") not in ("blind", "post_blind", "straddle")]
        if not current:
            return None
        candidate = current[-1]
        evidence = str(candidate.get("evidence") or "")
        if (candidate.get("action") != "check" or
                candidate.get("seat") == hero_index + 1 or
                float(candidate.get("confidence") or 0) > .88 or
                any(marker in evidence for marker in (
                    "hero_action", "official_", "next_street", "later_action"))):
            return None
        candidate_index = int(candidate["seat"]) - 1
        next_actor = HandStateLayer.next_actor(
            candidate_index, seat_count, set(eligible or ()), set(terminal or ()))
        return candidate if next_actor == hero_index else None

    @staticmethod
    def select_allin_confirmed_by_hero_allin_call(buttons, events, hand_id, street):
        if not any(button.get("kind") == "call" and
                   (button.get("value") == "allin" or button.get("allinCall"))
                   for button in buttons):
            return None
        return next((event for event in reversed(events)
                     if event.get("handId") == hand_id and
                     event.get("street") == street and
                     event.get("action") == "allin" and
                     isinstance(event.get("amount"), (int, float)) and
                     float(event.get("amount") or 0) > 0 and
                     .5 <= float(event.get("confidence") or 0) < .85 and
                     "allin" in str(event.get("evidence") or "").lower() and
                     "investment_amount" in str(event.get("evidence") or "").lower()), None)

    @staticmethod
    def select_fold_confirmed_by_hero_buttons(events, hand_id, street,
                                              hero_index, frame_sequence,
                                              strategy_confidence=.85):
        event = next((item for item in reversed(events)
                      if item.get("handId") == hand_id and
                      item.get("street") == street and
                      item.get("action") not in FORCED_CONTEXT_ACTIONS | {"straddle"}), None)
        if (event is None or event.get("action") != "fold" or event.get("inferred") or
                event.get("orderConflict") or not event.get("strategyEligible", True) or
                event.get("nextExpectedSeat") != hero_index + 1 or
                not (.72 <= float(event.get("confidence") or 0) < strategy_confidence) or
                (isinstance(event.get("frameSequence"), int) and
                 isinstance(frame_sequence, int) and
                 event["frameSequence"] > frame_sequence)):
            return None
        return event

    @staticmethod
    def select_allin_confirmed_by_call_amount(buttons, events, hand_id, street,
                                              hero_index, strategy_confidence=.85,
                                              require_later_equal_action=False):
        call_button = next((button for button in buttons
                            if button.get("kind") == "call" and
                            isinstance(button.get("value"), (int, float))), None)
        if call_button is None:
            return None
        current = [event for event in events
                   if event.get("handId") == hand_id and event.get("street") == street]
        investments = {"blind", "post_blind", "straddle", "call", "bet",
                       "raise", "reraise", "allin"}
        hero_invested = max((float(event["amount"]) for event in current
                             if event.get("seat") == hero_index + 1 and
                             event.get("action") in investments and
                             isinstance(event.get("amount"), (int, float))), default=0.0)
        target = hero_invested + float(call_button["value"])
        tolerance = max(.01, target * .015) if require_later_equal_action else max(.05, target * .02)
        candidate = next((event for event in reversed(current)
                          if event.get("seat") != hero_index + 1 and
                          event.get("action") == "allin" and
                          isinstance(event.get("amount"), (int, float)) and
                          abs(float(event["amount"]) - target) <= tolerance and
                          .55 <= float(event.get("confidence") or 0) and
                          (require_later_equal_action or
                           float(event.get("confidence") or 0) < strategy_confidence or
                           event.get("orderConflict")) and
                          "allin" in str(event.get("evidence") or "").lower() and
                          (require_later_equal_action or
                           "investment_amount" in str(event.get("evidence") or "").lower() or
                           isinstance(event.get("investmentText"), str))), None)
        if candidate is None:
            return None
        corroborating = None
        if require_later_equal_action:
            candidate_second = candidate.get("videoSecond", candidate.get("observedAt"))
            corroborating = next((event for event in current
                                  if event is not candidate and
                                  event.get("seat") not in (candidate.get("seat"), hero_index + 1) and
                                  event.get("action") in {"call", "raise", "reraise", "allin"} and
                                  isinstance(event.get("amount"), (int, float)) and
                                  abs(float(event["amount"]) - target) <= tolerance and
                                  not event.get("orderConflict") and
                                  event.get("strategyEligible", True) and
                                  float(event.get("confidence") or 0) >= strategy_confidence and
                                  (candidate_second is None or
                                   event.get("videoSecond", event.get("observedAt")) is None or
                                   event.get("videoSecond", event.get("observedAt")) >= candidate_second)), None)
            if corroborating is None:
                return None
        return {
            "candidate": candidate, "callButton": call_button,
            "heroInvested": hero_invested, "target": target,
            "corroborating": corroborating,
        }

    @staticmethod
    def exclusion_reason(event):
        action = str(event.get("action") or "")
        if action not in ORDINARY_ACTIONS | FORCED_CONTEXT_ACTIONS:
            return "special_action_deferred"
        if action in FORCED_CONTEXT_ACTIONS:
            return None
        if event.get("visualCandidate") or action.endswith("_unresolved"):
            return "unconfirmed_candidate"
        if event.get("inferred") or event.get("chainStatus") == "rule_confirmed":
            return "rule_inference_deferred"
        if event.get("orderConflict"):
            return "order_conflict_deferred"
        return None

    @classmethod
    def rebuild(cls, events: Iterable[Mapping], dealer_index, participants,
                seat_count, hand_id, street):
        source = [dict(event) for event in events]
        reason = next((cls.exclusion_reason(event) for event in source
                       if cls.exclusion_reason(event) is not None), None)
        if reason:
            return {"status": "fallback", "reason": reason, "snapshot": None,
                    "events": source}
        ActionLedgerLayer.reorder(
            source, {hand_id: dealer_index}, {hand_id: set(participants)},
            dealer_index, seat_count, include_event_seats=False)
        snapshot = ActionChainEngine.rebuild(
            source, dealer_index, participants, seat_count,
            hand_id=hand_id, street=street)
        return {"status": "shadow_ready", "reason": None,
                "snapshot": snapshot, "events": source}

    @classmethod
    def rebuild_special(cls, events: Iterable[Mapping], dealer_index, participants,
                        seat_count, hand_id, street, big_blind):
        source = [dict(event) for event in events]
        for event in source:
            action = str(event.get("action") or "")
            if action.endswith("_unresolved") or event.get("visualCandidate"):
                return {"status": "fallback", "reason": "unconfirmed_candidate",
                        "snapshot": None, "events": source}
            if action not in cls.SUPPORTED_ACTIONS:
                return {"status": "fallback", "reason": "unsupported_special_action",
                        "snapshot": None, "events": source}
        ActionLedgerLayer.reorder(
            source, {hand_id: dealer_index}, {hand_id: set(participants)},
            dealer_index, seat_count, include_event_seats=False)
        snapshot = ActionChainEngine.rebuild(
            source, dealer_index, participants, seat_count,
            hand_id=hand_id, street=street)
        legal_min_raise = minimum_raise_to(source, hand_id, street, big_blind)
        raises = full_raise_count(source, hand_id, street, big_blind)
        if legal_min_raise is None or raises is None:
            return {"status": "fallback", "reason": "special_amount_unreliable",
                    "snapshot": snapshot, "events": source}
        return {"status": "shadow_ready", "reason": None,
                "snapshot": snapshot, "events": source,
                "minimumRaiseTo": legal_min_raise,
                "fullRaiseCount": raises}

    @classmethod
    def commit(cls, events, dealer_index, participants, seat_count, hand_id,
               street, big_blind):
        source = [dict(event) for event in events]
        for event in source:
            action = str(event.get("action") or "")
            if event.get("visualCandidate") or action.endswith("_unresolved"):
                return {"status": "rejected", "reason": "unconfirmed_candidate",
                        "snapshot": None, "events": source}
            if action not in cls.SUPPORTED_ACTIONS:
                return {"status": "rejected", "reason": "unsupported_action",
                        "snapshot": None, "events": source}
        replay_participants = set(participants or ())
        replay_participants.update(
            int(event["seat"]) - 1 for event in source
            if event.get("seat") and event.get("action") in ("fold", "allin")
        )
        ActionLedgerLayer.reorder(
            source, {hand_id: dealer_index}, {hand_id: replay_participants},
            dealer_index, seat_count, include_event_seats=False)
        snapshot = ActionChainEngine.rebuild(
            source, dealer_index, replay_participants, seat_count,
            hand_id=hand_id, street=street)
        events[:] = source
        return {
            "status": "formal_ready" if snapshot.get("reliable") else "formal_unresolved",
            "reason": None if snapshot.get("reliable") else "current_street_unreliable",
            "snapshot": snapshot,
            "events": source,
            "minimumRaiseTo": minimum_raise_to(source, hand_id, street, big_blind),
            "fullRaiseCount": full_raise_count(source, hand_id, street, big_blind),
        }

    @classmethod
    def rebuild_multiway(cls, events: Iterable[Mapping], dealer_index, participants,
                         seat_count, hand_id, street, big_blind,
                         side_pot_contract=None):
        result = cls.rebuild_special(
            events, dealer_index, participants, seat_count, hand_id, street,
            big_blind)
        if result["status"] != "shadow_ready":
            return result
        allins = [event for event in result["events"]
                  if event.get("action") == "allin"]
        if len({event.get("seat") for event in allins}) < 2:
            return {**result, "status": "fallback",
                    "reason": "multiway_allin_context_missing"}
        contract = side_pot_contract if isinstance(side_pot_contract, Mapping) else {}
        layers = contract.get("layers")
        if contract.get("exact") is not True or not isinstance(layers, list) or not layers:
            return {**result, "status": "fallback",
                    "reason": "side_pot_contract_unresolved"}
        if any(not isinstance(layer, Mapping) or
               len(set(layer.get("eligibleSeats") or layer.get("participants") or [])) < 2
               for layer in layers):
            return {**result, "status": "fallback",
                    "reason": "side_pot_eligibility_unresolved"}
        return {**result, "multiwayReady": True,
                "sidePotContractVersion": contract.get("contractVersion")}

    @staticmethod
    def boundary_event_reason(event, current_hand_id, current_street):
        if event.get("handId") != current_hand_id:
            return "old_hand_rejected"
        captured_hand = event.get("capturedHandId", event.get("handId"))
        if captured_hand != current_hand_id:
            return "captured_old_hand_rejected"
        captured_street = event.get("capturedStreet", event.get("street"))
        if captured_street != event.get("street"):
            return "capture_street_rebound_required"
        if current_street not in ("preflop", "flop", "turn", "river"):
            return "current_street_unconfirmed"
        return None

    @classmethod
    def validate_boundary(cls, event, current_hand_id, current_street,
                          buttons_visible, button_hand_id=None,
                          button_street=None):
        reason = cls.boundary_event_reason(event, current_hand_id, current_street)
        if reason:
            return {"valid": False, "reason": reason}
        if buttons_visible and button_hand_id == current_hand_id and button_street == current_street:
            return {"valid": True, "reason": None}
        if not buttons_visible:
            return {"valid": False, "reason": "buttons_disappeared_wait_for_confirmation"}
        return {"valid": False, "reason": "button_context_mismatch"}
