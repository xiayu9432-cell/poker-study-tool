from collections.abc import Mapping


def seat_is_hand_eligible(seat: Mapping, evidenced_indices=()) -> bool:
    if not isinstance(seat, Mapping) or not isinstance(seat.get("index"), int):
        return False
    index = int(seat["index"])
    if index in set(evidenced_indices):
        return True
    action = str(seat.get("action") or "").strip().lower()
    occupancy = str(seat.get("occupancy") or "").strip().lower()
    if seat.get("empty") is True or action == "empty" or occupancy in ("empty", "away"):
        return False
    return occupancy == "occupied" or bool(seat.get("name") or seat.get("chips") is not None)


def provable_prior_street_action(previous: Mapping, later: Mapping, prior_street: str):
    seat = later.get("seat")
    if not seat or later.get("street") == prior_street:
        return None
    if previous.get("street") != prior_street or previous.get("unactedSeats") != [seat]:
        return None
    investments = previous.get("streetInvestments") or {}
    highest = previous.get("currentHighestBet")
    invested = investments.get(str(seat), investments.get(seat))
    if not isinstance(highest, (int, float)) or not isinstance(invested, (int, float)):
        return None
    deficit = float(highest) - float(invested)
    if deficit < -.001:
        return None
    return {"action": "check" if deficit <= .001 else "call",
            "amount": float(highest), "increase": max(0.0, deficit)}
