from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path


RANKS = "AKQJT98765432"
RANK_VALUE = {rank: len(RANKS) - index for index, rank in enumerate(RANKS)}
OPEN_FRACTIONS = {
    "UTG": .13, "UTG+1": .15, "MP": .18, "HJ": .22, "CO": .29,
    "BTN": .43, "BTN/SB": .43, "SB": .34, "BB": 0.0,
}
RAKE_TIGHTENING = {"4%-3BB封顶": 0.0, "4%-6BB封顶": .02, "4%-12BB封顶": .04}
SOURCE_POSITION = {
    (8, "UTG"): "UTG+1", (8, "UTG+1"): "UTG+2", (8, "MP"): "LJ",
    (7, "UTG"): "UTG+2", (7, "MP"): "LJ",
    (6, "UTG"): "LJ", (5, "UTG"): "HJ", (4, "CO"): "CO",
}


def parse_hand(hand):
    first, second = hand[0], hand[1]
    return first, second, hand[2:] == "s", first == second


def hand_score(hand):
    first, second, suited, pair = parse_hand(hand)
    high, low = RANK_VALUE[first], RANK_VALUE[second]
    if pair:
        return 28 + high * 4
    gap = high - low
    return (high * 4 + low * 1.5 + (5 if suited else 0) +
            max(0, 4 - gap) * 1.5 + (3 if first == "A" else 0))


def is_speculative(hand):
    first, second, suited, pair = parse_hand(hand)
    if pair:
        return RANK_VALUE[first] <= RANK_VALUE["8"]
    return suited and RANK_VALUE[first] <= RANK_VALUE["J"] and \
        RANK_VALUE[first] - RANK_VALUE[second] <= 2


def is_premium(hand):
    return hand in {"AA", "KK", "QQ", "JJ", "AKs", "AKo"}


def _open_fraction(position, players, stack_bucket, rake_policy):
    fraction = OPEN_FRACTIONS.get(position, .16)
    if players <= 4:
        fraction += .05
    fraction -= RAKE_TIGHTENING[rake_policy]
    stack_low = int(stack_bucket.split("-", 1)[0])
    if stack_low < 40:
        fraction -= .03
    return max(.06, min(.50, fraction))


def ranked_hands(hands):
    return sorted(hands, key=lambda hand: (hand_score(hand), hand), reverse=True)


@lru_cache(maxsize=1)
def _source_rfi_ranges():
    path = (Path(__file__).parent / "sources" / "pokercoaching-preflop-charts" /
            "rfi-source-ranges.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {position: frozenset(item["hands"])
            for position, item in data["ranges"].items()}


@lru_cache(maxsize=1)
def _source_rfi_actions():
    source_dir = Path(__file__).parent / "sources" / "pokercoaching-preflop-charts"
    ranges = json.loads((source_dir / "rfi-source-ranges.json").read_text(
        encoding="utf-8"))["ranges"]
    charts = json.loads((source_dir / "chart-actions.json").read_text(
        encoding="utf-8"))["charts"]
    page_three = {(item["page"], item["chart"]): item["actions"]
                  for item in charts if item["page"] == 3}
    return {position: page_three[(3, item["chart"])]
            for position, item in ranges.items()}


@lru_cache(maxsize=1)
def _source_response_ranges():
    path = (Path(__file__).parent / "sources" / "pokercoaching-preflop-charts" /
            "response-source-ranges.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _position_group_contains(group, position):
    return position in group.split("/")


def source_response_color(group, hand, hero_position, opponent_position, players):
    hero = source_reference_position(hero_position, players)
    opponent = source_reference_position(opponent_position, players)
    if hero is None or opponent is None:
        return None
    records = _source_response_ranges()[group]
    matches = [record for record in records if record["hero"] == hero and
               _position_group_contains(record["opponent"], opponent)]
    if len(matches) != 1:
        return None
    return matches[0]["actions"].get(hand)


def source_reference_position(position, players):
    if position in {"HJ", "CO", "BTN", "SB", "BB"} and players >= 3:
        return position
    return SOURCE_POSITION.get((players, position))


def source_open_color(hand, position, players):
    source_position = source_reference_position(position, players)
    if source_position is None:
        return None
    return (_source_rfi_actions().get(source_position) or {}).get(hand)


def _source_open_range(hands, position, players, rake_policy):
    source_position = source_reference_position(position, players)
    source_ranges = _source_rfi_ranges()
    if source_position is None or source_position not in source_ranges:
        return None
    source = source_ranges[source_position] & frozenset(hands)
    tightening = RAKE_TIGHTENING[rake_policy]
    keep = round(len(source) * (1 - tightening))
    ranked = ranked_hands(source)
    return frozenset(ranked[:max(1, keep)]) | frozenset(
        hand for hand in hands if is_premium(hand))


@lru_cache(maxsize=None)
def open_range(hands, position, players, stack_bucket, rake_policy):
    stack_low = int(stack_bucket.split("-", 1)[0])
    if stack_low >= 60:
        sourced = _source_open_range(hands, position, players, rake_policy)
        if sourced is not None:
            return sourced
    ranked = ranked_hands(hands)
    keep = round(len(ranked) * _open_fraction(
        position, players, stack_bucket, rake_policy))
    return frozenset(ranked[:max(1, keep)]) | frozenset(
        hand for hand in hands if is_premium(hand))


@lru_cache(maxsize=None)
def isolation_range(hands, position, players, stack_bucket, rake_policy, family):
    opening = open_range(hands, position, players, stack_bucket, rake_policy)
    candidates = [hand for hand in ranked_hands(opening)
                  if not is_speculative(hand) or is_premium(hand)]
    keep_fraction = {
        "一人跛入": .65,
        "多人跛入": .50,
        "Straddle有人跛入": .40,
    }[family]
    if position in {"SB", "BB"}:
        keep_fraction -= .15
    stack_low = int(stack_bucket.split("-", 1)[0])
    if stack_low < 40:
        keep_fraction -= .10
    keep = max(1, round(len(candidates) * max(.20, keep_fraction)))
    return frozenset(candidates[:keep]) | frozenset(
        hand for hand in hands if is_premium(hand))


@dataclass(frozen=True)
class BaselineDecision:
    action: str
    reason_code: str
    requires_realtime_math: bool = False
    evidence_level: str = "C"
    evidence_source: str = "现金桌经验规则，待数据校准"


def _decision(action, reason, requires_math=False, level="C", source=None):
    return BaselineDecision(
        action, reason, requires_math, level,
        source or ("教材或来源牌表原则与当前数学模型交叉验证" if level == "B"
                   else "现金桌经验规则，待数据校准"),
    )


def decide(hand, state, hands):
    family = state["priorActionPattern"]
    stack_low = int(state["effectiveStackBucket"].split("-", 1)[0])
    opening = open_range(hands, state["heroPosition"], state["activePlayers"],
                         state["effectiveStackBucket"], state["rakePolicy"])
    if family in ("无人入池", "Straddle无人入池"):
        sourced = (stack_low >= 60 and
                   source_reference_position(state["heroPosition"],
                                             state["activePlayers"]) is not None)
        level = "B" if sourced else "C"
        if state["heroPosition"] == "BB":
            return _decision("过牌", "大盲无人加注可免费看牌", level="B")
        if hand not in opening:
            return _decision("弃牌", "不在当前位置开池范围", level=level)
        color = (source_open_color(hand, state["heroPosition"],
                                   state["activePlayers"])
                 if family == "无人入池" and sourced else None)
        if state["heroPosition"] == "SB" and color == "green" and not is_premium(hand):
            return _decision("跟注", "来源范围将此牌归为小盲补齐区", level="B")
        return _decision("加注", "首次入池采用加注或弃牌", level=level)
    if family in ("一人跛入", "多人跛入", "Straddle有人跛入"):
        isolating = isolation_range(
            hands, state["heroPosition"], state["activePlayers"],
            state["effectiveStackBucket"], state["rakePolicy"], family)
        if hand in isolating:
            return _decision("隔离加注", "独立隔离范围支持减少多人底池并扩大价值")
        if state["heroPosition"] == "BB" and family != "Straddle有人跛入":
            return _decision("过牌", "大盲面对跟注者无需补筹码，可免费让牌")
        if (family != "Straddle有人跛入" and stack_low >= 80 and
                is_speculative(hand) and state["heroPosition"] in ("CO", "BTN")):
            return _decision("跟注", "深筹码后位保留隐含赔率")
        return _decision("弃牌", "不在独立隔离或受控跟注范围")
    if family in ("面对短码全下", "面对四下注"):
        return _decision("实时精算", "实际金额和对手范围决定是否继续", True, "B")
    if family == "面对三下注":
        actors = tuple(state.get("actors") or ())
        color = (source_response_color(
            "rfiVs3bet", hand, state["heroPosition"], actors[-1],
            state["activePlayers"])
                 if stack_low >= 60 and state.get("heroRole") == "原开池者" and actors
                 else None)
        if color == "red":
            return _decision("价值四下注", "来源范围支持继续，具体金额由实时精算决定", True, "B")
        if color == "blue":
            return _decision("加注", "来源牌表为诈唬加注区，具体收益和金额由实时精算确认", True, "B")
        if color == "green":
            return _decision("跟注", "来源牌表为面对三下注的跟注区，真实价格仍由实时精算确认", True, "B")
        if color == "gray":
            return _decision("实时精算", "来源牌表为混合弃牌区，必须结合真实价格决定", True, "B")
        if color == "white":
            return _decision("弃牌", "不在当前开池者面对三下注的继续范围", level="B")
        if is_premium(hand):
            return _decision("加注或跟注", "强牌继续并由实际价格选尺寸", True)
        return _decision("实时精算", "三下注压力需要实际价格和范围", True)
    if family in ("面对一次开池", "开池后有人跟注"):
        actors = tuple(state.get("actors") or ())
        color = (source_response_color(
            "facingRfi", hand, state["heroPosition"], actors[0],
            state["activePlayers"])
                 if family == "面对一次开池" and stack_low >= 60 and actors
                 else None)
        if color == "red":
            return _decision("价值三下注", "来源范围将此牌归为价值三下注", level="B")
        if color == "blue":
            return _decision("加注", "来源牌表为诈唬加注区，真实价格、抽成和弃牌率仍由精算确认", True, "B")
        if color == "green":
            return _decision("跟注", "来源牌表为面对开池的跟注区，真实价格和抽成仍由精算确认", True, "B")
        if color == "gray":
            return _decision("实时精算", "来源牌表为混合弃牌区，必须结合真实价格决定", True, "B")
        if color == "white":
            return _decision("弃牌", "不在当前位置面对该开池位的继续范围", level="B")
        if is_premium(hand):
            return _decision("价值三下注", "强牌降低多人入池并扩大价值")
        if stack_low >= 60 and hand in opening and not is_speculative(hand):
            return _decision("实时精算", "边缘继续需要实际底池赔率和抽成", True)
        return _decision("弃牌", "位置筹码或抽成不足以支持继续")
    return _decision("拒绝建议", "行动场景未覆盖", True)
