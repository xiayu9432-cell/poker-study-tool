import math


POSITION_MAP = {
    "under_the_gun": "UTG", "under_the_gun_plus_one": "UTG+1",
    "middle": "MP", "hijack": "HJ", "cutoff": "CO", "dealer": "BTN",
    "small_blind": "SB", "big_blind": "BB",
}
POSITION_LABELS = {
    2: ("BTN", "BB"),
    3: ("BTN", "SB", "BB"),
    4: ("BTN", "SB", "BB", "CO"),
    5: ("BTN", "SB", "BB", "UTG", "CO"),
    6: ("BTN", "SB", "BB", "UTG", "HJ", "CO"),
    7: ("BTN", "SB", "BB", "UTG", "MP", "HJ", "CO"),
    8: ("BTN", "SB", "BB", "UTG", "UTG+1", "MP", "HJ", "CO"),
}
VOLUNTARY = {"call", "bet", "raise", "reraise", "allin"}
RAISES = {"bet", "raise", "reraise", "allin"}


def hand_class(cards):
    if not isinstance(cards, list) or len(cards) != 2:
        return None
    ranks = "23456789TJQKA"
    try:
        first, second = cards
        if any(not isinstance(card, str) or len(card) != 2 or
               card[0].upper() not in ranks or card[1].lower() not in "shdc"
               for card in cards):
            return None
        first = first[0].upper() + first[1].lower()
        second = second[0].upper() + second[1].lower()
        if first == second:
            return None
        high, low = sorted((first[0], second[0]), key=ranks.index, reverse=True)
    except (TypeError, ValueError):
        return None
    if high == low:
        return high * 2
    return high + low + ("s" if first[1] == second[1] else "o")


def stack_bucket(stack_bb):
    if not isinstance(stack_bb, (int, float)) or not math.isfinite(stack_bb) or stack_bb < 0:
        return None
    low = min(180, int(stack_bb // 20) * 20)
    return f"{low}-{low + 20}BB"


def rake_policy(rate, cap, big_blind):
    if not all(isinstance(value, (int, float)) and math.isfinite(value)
               for value in (rate, cap, big_blind)) or big_blind <= 0:
        return None
    normalized_rate = rate / 100 if rate > 1 else rate
    cap_bb = cap / big_blind
    if not math.isclose(normalized_rate, .04, abs_tol=.0001):
        return None
    nearest = min((3, 6, 12), key=lambda value: abs(value - cap_bb))
    if abs(nearest - cap_bb) > .25:
        return None
    return f"4%-{nearest}BB封顶"


def effective_stack_bb(state, hero_index):
    big_blind = state.get("blindBig")
    chips = state.get("decisionChipStacks") or {}
    if not isinstance(big_blind, (int, float)) or big_blind <= 0:
        return None
    hero_chips = (chips.get(str(hero_index)) or {}).get("value")
    if not isinstance(hero_chips, (int, float)) or hero_chips < 0:
        return None
    current_actions = [event for event in state.get("actionLog") or []
                       if event.get("handId") == state.get("handId")]
    folded = {event.get("seat") for event in current_actions
              if event.get("action") == "fold"}
    opponents = []
    for seat in state.get("seats") or []:
        if (seat.get("index") == hero_index or seat.get("empty") or
                seat.get("index", -1) + 1 in folded):
            continue
        value = (chips.get(str(seat.get("index"))) or {}).get("value")
        if isinstance(value, (int, float)) and value >= 0:
            opponents.append(min(hero_chips, value))
    straddles = [event.get("amount") for event in state.get("actionLog") or []
                 if event.get("handId") == state.get("handId") and
                 event.get("street") == "preflop" and
                 event.get("action") == "straddle" and
                 isinstance(event.get("amount"), (int, float)) and
                 event.get("amount") > 0]
    blind_straddle = state.get("blindStraddle")
    if isinstance(blind_straddle, (int, float)) and blind_straddle > 0:
        straddles.append(blind_straddle)
    live_blind = max([big_blind, *straddles])
    return max(opponents, default=None) / live_blind if opponents else None


def action_family(state, hero_index):
    actions = [event for event in state.get("actionLog") or []
               if event.get("handId") == state.get("handId") and
               event.get("street") == "preflop" and
               event.get("seat") != hero_index + 1]
    voluntary = [event for event in actions if event.get("action") in VOLUNTARY]
    straddle = any(event.get("action") == "straddle" for event in actions)
    if voluntary and voluntary[-1].get("action") == "allin":
        return "面对短码全下"
    raises = int(state.get("preflopFullRaiseCount") or 0)
    calls = sum(event.get("action") == "call" for event in voluntary)
    if raises >= 3:
        return "面对四下注"
    if raises >= 2:
        return "面对三下注"
    if raises == 1:
        return "开池后有人跟注" if calls else "面对一次开池"
    if straddle:
        return "Straddle有人跛入" if calls else "Straddle无人入池"
    if calls >= 2:
        return "多人跛入"
    if calls == 1:
        return "一人跛入"
    return "无人入池"


def seat_positions(state):
    occupied = [seat.get("index") for seat in state.get("seats") or []
                if not seat.get("empty") and isinstance(seat.get("index"), int)]
    dealer = state.get("dealerIndex")
    if dealer not in occupied or len(occupied) not in POSITION_LABELS:
        return {}
    start = occupied.index(dealer)
    order = occupied[start:] + occupied[:start]
    return dict(zip(order, POSITION_LABELS[len(order)]))


def strategy_actors_and_role(state, hero_index, family):
    positions = seat_positions(state)
    actions = [event for event in state.get("actionLog") or []
               if event.get("handId") == state.get("handId") and
               event.get("street") == "preflop" and
               event.get("action") in VOLUNTARY]
    opponents = [event for event in actions if event.get("seat") != hero_index + 1]
    actor_positions = tuple(positions.get(int(event["seat"]) - 1)
                            for event in opponents if positions.get(int(event["seat"]) - 1))
    hero_raised = any(event.get("seat") == hero_index + 1 and
                      event.get("action") in RAISES for event in actions)
    if family == "面对三下注":
        role = "原开池者" if hero_raised else "冷跟后面对挤压"
    elif family == "面对四下注":
        role = "三下注者"
    elif family in {"一人跛入", "多人跛入", "Straddle有人跛入"}:
        role = "隔离加注者"
    elif family in {"无人入池", "Straddle无人入池"}:
        role = "首次入池者"
    elif family == "开池后有人跟注":
        role = "挤压位"
    else:
        role = "冷面对开池"
    return actor_positions, role


def pressure_bucket(family, call_bb):
    if family in {"无人入池", "一人跛入", "多人跛入"}:
        return "无加注"
    if family.startswith("Straddle"):
        return "Straddle价格"
    if family == "面对短码全下":
        return "全下压力"
    if family == "面对四下注":
        return "全下压力" if call_bb >= 25 else "大四下注"
    if family == "面对三下注":
        return "小三下注" if call_bb < 5 else "标准三下注" if call_bb < 12 else "大三下注"
    return "小开池" if call_bb < 2.5 else "标准开池" if call_bb <= 4 else "大开池"


def action_price_bb(state):
    big_blind = state.get("blindBig")
    if not isinstance(big_blind, (int, float)) or big_blind <= 0:
        return 0.0
    amounts = [float(event["amount"]) for event in state.get("actionLog") or []
               if event.get("handId") == state.get("handId") and
               event.get("street") == "preflop" and
               event.get("action") in VOLUNTARY and
               isinstance(event.get("amount"), (int, float)) and
               event["amount"] >= 0]
    current_price = max(amounts, default=0.0)
    call_amount = state.get("callAmount")
    if isinstance(call_amount, (int, float)) and call_amount >= 0:
        current_price = max(current_price, float(call_amount))
    return current_price / float(big_blind)


def recognize_preflop(state, hero_index, require_actionable=True):
    missing = []
    if state.get("street") != "preflop":
        return {"eligible": False, "reason": "不是翻牌前"}
    if (require_actionable and (state.get("actionable") is not True or
            state.get("expectedActionSeat") != hero_index + 1 or
            state.get("heroActsAfterExpected"))):
        return {"eligible": False, "reason": "动作链未闭合"}
    hand = hand_class(state.get("heroCards"))
    if hand is None:
        missing.append("本人两张牌")
    players = state.get("activePlayerCount")
    if not isinstance(players, int) or not 2 <= players <= 8:
        missing.append("在局人数")
    position = POSITION_MAP.get(state.get("heroPosition"))
    if position is None:
        missing.append("本人位置")
    stack_bb_value = effective_stack_bb(state, hero_index)
    stack = stack_bucket(stack_bb_value)
    if stack is None:
        missing.append("同帧有效筹码")
    rake = rake_policy(state.get("rakeRate"), state.get("rakeCap"), state.get("blindBig"))
    if rake is None:
        missing.append("三档抽成映射")
    if not isinstance(state.get("preflopFullRaiseCount"), int):
        missing.append("完整加注次数")
    if missing:
        return {"eligible": False, "reason": "输入不足", "missing": missing}
    family = action_family(state, hero_index)
    actors, hero_role = strategy_actors_and_role(state, hero_index, family)
    call_bb = action_price_bb(state)
    normalized = {
        "activePlayers": players, "heroPosition": position,
        "effectiveStackBucket": stack, "rakePolicy": rake,
        "priorActionPattern": family,
        "pressureBucket": pressure_bucket(family, call_bb),
        "actors": actors, "heroRole": hero_role,
    }
    return {
        "eligible": True, "mode": "只读旁路", "handClass": hand,
        "effectiveStackBb": round(stack_bb_value, 2), "normalizedState": normalized,
        "scene": {"family": family, "actors": actors, "heroRole": hero_role},
        "pressure": {"bucket": normalized["pressureBucket"], "callBb": round(call_bb, 2)},
    }
