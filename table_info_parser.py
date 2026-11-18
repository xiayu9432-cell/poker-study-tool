import re


MONEY = re.compile(r"\$?\s*(\d+(?:\.\d+)?)")
TABLE_NUMBER = re.compile(r"(?:德州扑克|德州扑克牌|扑克)[-—_ ]*([A-Za-z0-9]{3,})", re.I)


HAPPY_IMPACT_DECISION_RULES = {
    "complete": True,
    "standardHoldemCompatible": True,
    "forcedStraddle": {
        "minimumPlayers": 4,
        "amountSource": "blind_text_third_amount",
        "seat": "under_the_gun",
        "preflopActsLast": True,
    },
}

SUNLANG_DECISION_RULES = {
    "complete": True,
    "standardHoldemCompatible": True,
}


def parse_table_play(text):
    value = str(text or "").replace(" ", "")
    hold_em = "\u5fb7\u5dde\u6251\u514b" in value or "\u5fb7\u5dde\u6251\u514b\u724c" in value
    if "\u677e\u6d6a" in value and hold_em:
        return {
            "type": "\u677e\u6d6a\u5fb7\u5dde\u6251\u514b",
            "special": "high_ante",
            "rulesConfirmed": True,
            "decisionRules": dict(SUNLANG_DECISION_RULES),
        }
    if "\u66b4\u51fb" in value and hold_em:
        return {
            "type": "\u6b22\u4e50\u66b4\u51fb\u5fb7\u5dde",
            "special": "\u5fc5\u4e0b\u5c40",
            "rulesConfirmed": True,
            "decisionRules": {
                **HAPPY_IMPACT_DECISION_RULES,
                "forcedStraddle": dict(HAPPY_IMPACT_DECISION_RULES["forcedStraddle"]),
            },
        }
    if hold_em:
        return {"type": "\u5fb7\u5dde\u6251\u514b", "special": None}
    return None


def parse_table_number(text):
    value = str(text or "").replace(" ", "")
    match = TABLE_NUMBER.search(value)
    return match.group(1) if match else None

def parse_blind_text(text):
    normalized = (str(text or "").replace("：", ":").replace("，", ",")
                  .replace("（", "(").replace("）", ")"))
    table_match = TABLE_NUMBER.search(normalized)
    if table_match:
        normalized = normalized[table_match.end():]
    normalized = re.sub(r"(?<![A-Za-z])S(?=\s*\d)", "$", normalized, flags=re.I)
    normalized = re.sub(r"(?<=[$/(])\s*[Oo](?=\.\d)", "0", normalized)
    normalized = re.sub(r"(\$\s*)0\.0\s+(\d+)", r"\g<1>0.\2", normalized)
    normalized = re.sub(r"(\$\s*)0\s+(\d+)", r"\g<1>0.\2", normalized)
    parts = normalized.split("(", 1)
    main = parts[0]
    values = [float(value) for value in MONEY.findall(main)]
    if len(values) < 2:
        return None
    small, big = values[:2]
    straddle = values[2] if len(values) >= 3 else None
    ante = None
    if small <= 0 or big <= small:
        return None
    if len(parts) == 2:
        match = MONEY.search(parts[1])
        if match:
            ante = float(match.group(1))
    return {"small": small, "big": big, "straddle": straddle, "ante": ante,
            "hasAnte": ante is not None, "currency": "usd" if "$" in normalized else "coin",
            "raw": str(text)}


RAKE_TABLE_USD_NORMAL = {
    (0.02, 0.05, 0.10): (0.04, 0.15, 0.30),
    (0.05, 0.10, 0.20): (0.04, 0.30, 0.60),
    (0.10, 0.20, 0.40): (0.04, 0.60, 1.20),
    (0.20, 0.50, 1.00): (0.04, 1.00, 2.00),
    (0.50, 1.00, 2.00): (0.04, 2.00, 4.00),
    (1.00, 2.00, 4.00): (0.04, 4.00, 8.00),
    (2.00, 4.00, 8.00): (0.04, 4.00, 8.00),
    (5.00, 10.00, 20.00): (0.04, 10.00, 20.00),
    (10.00, 20.00, 40.00): (0.04, 30.00, 40.00),
    (25.00, 50.00, 100.00): (0.04, 75.00, 100.00),
    (50.00, 100.00, 200.00): (0.04, 150.00, 200.00),
    (100.00, 200.00, 400.00): (0.04, 300.00, 300.00),
    (200.00, 400.00, 800.00): (0.04, 600.00, 600.00),
    (400.00, 800.00, 1600.00): (0.04, 1200.00, 1200.00),
    (500.00, 1000.00, 2000.00): (0.04, 1500.00, 1500.00),
    (1000.00, 2000.00, 4000.00): (0.04, 2000.00, 2000.00),
}

RAKE_TABLE_USD_SUNLANG = {
    (0.02, 0.05, 0.10): (0.04, 0.30, 0.60), (0.05, 0.10, 0.25): (0.04, 0.60, 1.20),
    (0.10, 0.20, 0.50): (0.04, 1.20, 2.40), (0.20, 0.50, 1.00): (0.04, 2.00, 4.00),
    (0.50, 1.00, 2.50): (0.04, 4.00, 8.00), (1.00, 2.00, 5.00): (0.04, 8.00, 16.00),
    (2.00, 4.00, 10.00): (0.04, 8.00, 16.00), (5.00, 10.00, 25.00): (0.04, 20.00, 40.00),
    (10.00, 20.00, 50.00): (0.04, 60.00, 80.00), (25.00, 50.00, 125.00): (0.04, 150.00, 200.00),
    (50.00, 100.00, 250.00): (0.04, 300.00, 400.00), (100.00, 200.00, 500.00): (0.04, 300.00, 300.00),
    (200.00, 400.00, 1000.00): (0.04, 600.00, 600.00), (400.00, 800.00, 2000.00): (0.04, 1200.00, 1200.00),
    (500.00, 1000.00, 2500.00): (0.04, 1500.00, 1500.00), (1000.00, 2000.00, 5000.00): (0.04, 2000.00, 2000.00),
}

RAKE_TABLE_COIN_NORMAL = {
    (0.02, 0.05, 0.10): (0.04, 0.15, 0.30), (0.10, 0.20, 0.40): (0.04, 0.60, 1.20),
    (0.20, 0.50, 1.00): (0.04, 1.50, 3.00), (0.50, 1.00, 2.00): (0.04, 3.00, 6.00),
    (1.00, 2.00, 4.00): (0.04, 4.00, 8.00), (2.00, 4.00, 8.00): (0.04, 8.00, 16.00),
    (5.00, 10.00, 20.00): (0.04, 10.00, 20.00), (10.00, 20.00, 40.00): (0.04, 20.00, 40.00),
    (25.00, 50.00, 100.00): (0.04, 50.00, 100.00), (50.00, 100.00, 200.00): (0.05, 100.00, 300.00),
    (100.00, 200.00, 400.00): (0.05, 300.00, 300.00), (200.00, 400.00, 800.00): (0.05, 600.00, 600.00),
    (400.00, 800.00, 1600.00): (0.05, 1200.00, 1200.00), (500.00, 1000.00, 2000.00): (0.05, 1500.00, 1500.00),
    (1000.00, 2000.00, 4000.00): (0.05, 2000.00, 2000.00),
}

RAKE_TABLE_COIN_SUNLANG = {
    (0.02, 0.05, 0.10): (0.04, 0.30, 0.60), (0.10, 0.20, 0.50): (0.04, 1.20, 2.40),
    (0.20, 0.50, 1.00): (0.04, 3.00, 6.00), (0.50, 1.00, 2.50): (0.04, 6.00, 12.00),
    (1.00, 2.00, 5.00): (0.04, 8.00, 16.00), (2.00, 4.00, 10.00): (0.04, 16.00, 32.00),
    (5.00, 10.00, 25.00): (0.04, 20.00, 40.00), (10.00, 20.00, 50.00): (0.04, 40.00, 80.00),
    (25.00, 50.00, 125.00): (0.04, 100.00, 200.00), (50.00, 100.00, 250.00): (0.04, 200.00, 400.00),
    (100.00, 200.00, 500.00): (0.04, 300.00, 300.00), (200.00, 400.00, 1000.00): (0.04, 600.00, 600.00),
    (400.00, 800.00, 2000.00): (0.04, 1200.00, 1200.00), (500.00, 1000.00, 2500.00): (0.04, 1500.00, 1500.00),
    (1000.00, 2000.00, 5000.00): (0.04, 2000.00, 2000.00),
}

RAKE_TABLE = RAKE_TABLE_USD_NORMAL


def rake_strategy_policies():
    tables = (
        ("usd", "normal", RAKE_TABLE_USD_NORMAL),
        ("usd", "sunlang", RAKE_TABLE_USD_SUNLANG),
        ("coin", "normal", RAKE_TABLE_COIN_NORMAL),
        ("coin", "sunlang", RAKE_TABLE_COIN_SUNLANG),
    )
    supported_shapes = {(0.04, 3.0), (0.04, 6.0), (0.04, 12.0)}
    policies = {}
    for currency, table_kind, table in tables:
        for (small, big, straddle), (rate, cap_two_four, cap_five_plus) in table.items():
            for player_group, cap in (("2-4", cap_two_four), ("5+", cap_five_plus)):
                cap_bb = round(cap / big, 9)
                key = (rate, cap_bb)
                if key not in supported_shapes:
                    continue
                policies.setdefault(key, []).append({
                    "currency": currency,
                    "table_kind": table_kind,
                    "small_blind": small,
                    "big_blind": big,
                    "straddle": straddle,
                    "player_group": player_group,
                    "cap": cap,
                })
    return [{
        "id": f"rake-{rate:g}-cap-{cap_bb:g}bb",
        "percent": rate,
        "cap_bb": cap_bb,
        "no_flop_no_drop": True,
        "source": "table_info_parser.py",
        "source_rows": policies[(rate, cap_bb)],
    } for rate, cap_bb in sorted(policies)]


def lookup_rake(small, big, ante=None, players=2, straddle=None, currency="usd", table_play=None):
    if small is None or big is None:
        return None
    key = (round(float(small), 2), round(float(big), 2),
           round(float(straddle if straddle is not None else float(big) * 2), 2))
    sunlang = "松浪" in str(table_play or "")
    tables = {("usd", False): RAKE_TABLE_USD_NORMAL, ("usd", True): RAKE_TABLE_USD_SUNLANG,
              ("coin", False): RAKE_TABLE_COIN_NORMAL, ("coin", True): RAKE_TABLE_COIN_SUNLANG}
    table = tables.get((str(currency or "usd").lower(), sunlang), RAKE_TABLE_USD_NORMAL)
    row = next((value for row_key, value in table.items()
                if abs(row_key[0] - key[0]) < 1e-9 and abs(row_key[1] - key[1]) < 1e-9), None)
    if row is None:
        return None
    rate, cap_two_four, cap_four_plus = row
    return {"rate": rate, "cap": cap_two_four if players <= 4 else cap_four_plus}
