from action_ledger_layer import ActionLedgerLayer


def test_terminal_and_duplicate_rules():
    events = [{"handId": 1, "street": "turn", "seat": 3, "action": "fold",
               "observedAt": 2.0}]
    assert ActionLedgerLayer.has_confirmed_terminal(events, {"handId": 1, "seat": 3})
    assert not ActionLedgerLayer.has_confirmed_terminal(events, {"handId": 2, "seat": 3})
    duplicate = dict(events[0], observedAt=2.5)
    assert ActionLedgerLayer.is_recent_duplicate(events, duplicate)


def test_time_participant_and_order_rules():
    events = [{"handId": 1, "street": "flop", "seat": 1, "action": "check",
               "videoSecond": 5.0, "observedAt": 5.0}]
    later = {"handId": 1, "street": "flop", "seat": 2, "action": "check",
             "videoSecond": 4.0, "observedAt": 4.0}
    ActionLedgerLayer.normalize_street_time(events, later)
    assert later["videoSecond"] == 5.0
    assert later["rawObservedSecond"] == 4.0

    participants = {}
    trackers = {1: {"handEligible": False}}
    assert ActionLedgerLayer.record_participant(participants, trackers, later) == 1
    assert participants == {1: {1}}
    assert trackers[1]["handEligible"]

    events.append(later)
    ActionLedgerLayer.reorder(events, {1: 7}, participants, 7, 8)
    assert [item["seat"] for item in events] == [1, 2]


def test_explicit_historical_evidence_keeps_original_time():
    events = [{"handId": 1, "street": "preflop", "seat": 2,
               "action": "call", "videoSecond": 139.583}]
    repaired = {"handId": 1, "street": "preflop", "seat": 1,
                "action": "fold", "videoSecond": 139.583,
                "historicalEvidenceBinding": True}

    ActionLedgerLayer.normalize_street_time(events + [
        {"handId": 1, "street": "preflop", "seat": 3,
         "action": "raise", "videoSecond": 145.0}
    ], repaired)

    assert repaired["videoSecond"] == 139.583
    assert "rawObservedSecond" not in repaired
