from itertools import product


RANKS = "AKQJT98765432"
POSITIONS_BY_PLAYERS = {
    2: ("BTN/SB", "BB"),
    3: ("BTN", "SB", "BB"),
    4: ("CO", "BTN", "SB", "BB"),
    5: ("UTG", "CO", "BTN", "SB", "BB"),
    6: ("UTG", "HJ", "CO", "BTN", "SB", "BB"),
    7: ("UTG", "MP", "HJ", "CO", "BTN", "SB", "BB"),
    8: ("UTG", "UTG+1", "MP", "HJ", "CO", "BTN", "SB", "BB"),
}
STACK_BUCKETS = tuple(f"{start}-{start + 20}BB" for start in range(0, 200, 20))
RAKE_POLICIES = (
    "4%-3BB封顶",
    "4%-6BB封顶",
    "4%-12BB封顶",
)
ACTION_PRESSURE = {
    "无人入池": ("无加注",),
    "一人跛入": ("无加注",),
    "多人跛入": ("无加注",),
    "面对一次开池": ("小开池", "标准开池", "大开池"),
    "开池后有人跟注": ("小开池", "标准开池", "大开池"),
    "面对三下注": ("小三下注", "标准三下注", "大三下注"),
    "面对四下注": ("大四下注", "全下压力"),
    "面对短码全下": ("全下压力",),
    "Straddle无人入池": ("Straddle价格",),
    "Straddle有人跛入": ("Straddle价格",),
}


def _earlier_positions(players, hero_position):
    positions = POSITIONS_BY_PLAYERS[players]
    return positions[:positions.index(hero_position)]


def legal_scenario_families(players, hero_position):
    positions = POSITIONS_BY_PLAYERS[players]
    hero_index = positions.index(hero_position)
    earlier = positions[:hero_index]
    later = positions[hero_index + 1:]
    families = []
    if hero_position != "BB":
        families.append({"family": "无人入池", "heroRole": "首次入池者",
                         "actors": ()})
    for limper in earlier:
        families.append({"family": "一人跛入", "heroRole": "隔离加注者",
                         "actors": (limper,)})
    if len(earlier) >= 2:
        families.append({"family": "多人跛入", "heroRole": "隔离加注者",
                         "actors": tuple(earlier[-2:])})
    for opener in earlier:
        families.append({"family": "面对一次开池", "heroRole": "冷面对开池",
                         "actors": (opener,)})
        callers = earlier[earlier.index(opener) + 1:]
        if callers:
            families.append({"family": "开池后有人跟注", "heroRole": "挤压位",
                             "actors": (opener, callers[-1])})
    if hero_position != "BB":
        for reraiser in later:
            families.append({"family": "面对三下注", "heroRole": "原开池者",
                             "actors": (reraiser,)})
            families.append({"family": "面对短码全下", "heroRole": "原开池者",
                             "actors": (reraiser,)})
    for opener in earlier:
        for squeezer in later:
            families.append({"family": "面对三下注", "heroRole": "冷跟后面对挤压",
                             "actors": (opener, squeezer)})
            families.append({"family": "面对四下注", "heroRole": "三下注者",
                             "actors": (opener, squeezer)})
    if players >= 3 and hero_position not in ("BTN/SB", "BB"):
        families.append({"family": "Straddle无人入池", "heroRole": "首次入池者",
                         "actors": ("Straddle",)})
        if earlier:
            families.append({"family": "Straddle有人跛入", "heroRole": "隔离加注者",
                             "actors": (earlier[-1], "Straddle")})
    return tuple(families)


def iter_legal_range_table_keys():
    for players, position in position_player_pairs():
        for family in legal_scenario_families(players, position):
            pressures = ACTION_PRESSURE[family["family"]]
            for stack, rake, pressure in product(STACK_BUCKETS, RAKE_POLICIES, pressures):
                yield {
                    "activePlayers": players,
                    "heroPosition": position,
                    "heroRole": family["heroRole"],
                    "actors": family["actors"],
                    "effectiveStackBucket": stack,
                    "rakePolicy": rake,
                    "priorActionPattern": family["family"],
                    "pressureBucket": pressure,
                }


def legal_range_table_count():
    return sum(1 for _ in iter_legal_range_table_keys())


def legal_hand_state_count():
    return legal_range_table_count() * len(hand_classes())


def hand_classes():
    pairs = [rank * 2 for rank in RANKS]
    suited = []
    offsuit = []
    for high_index, high in enumerate(RANKS):
        for low in RANKS[high_index + 1:]:
            suited.append(f"{high}{low}s")
            offsuit.append(f"{high}{low}o")
    return tuple(pairs + suited + offsuit)


def action_pressure_pairs():
    return tuple((action, pressure)
                 for action, pressures in ACTION_PRESSURE.items()
                 for pressure in pressures)


def position_player_pairs():
    return tuple((players, position)
                 for players, positions in POSITIONS_BY_PLAYERS.items()
                 for position in positions)


def standardized_state_upper_bound():
    return (len(hand_classes()) * len(position_player_pairs()) *
            len(STACK_BUCKETS) * len(RAKE_POLICIES) *
            len(action_pressure_pairs()))


def iter_state_keys():
    for hand, player_position, stack, rake, action_pressure in product(
            hand_classes(), position_player_pairs(), STACK_BUCKETS,
            RAKE_POLICIES, action_pressure_pairs()):
        players, position = player_position
        action_pattern, pressure = action_pressure
        yield {
            "handClass": hand,
            "activePlayers": players,
            "heroPosition": position,
            "effectiveStackBucket": stack,
            "rakePolicy": rake,
            "priorActionPattern": action_pattern,
            "pressureBucket": pressure,
        }


standardized_state_count = standardized_state_upper_bound
