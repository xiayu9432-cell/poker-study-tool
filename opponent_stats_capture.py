import re

import cv2


class OpponentStatsParser:
    LABELS = {
        "levelHands": ("本级别手数", "本級別手數"),
        "vpipRate": ("主动入池率", "主動入池率"),
        "totalHands": ("总手数", "總手數"),
        "pfrRate": ("加注入池率", "加註入池率"),
    }
    ADVANCED_LABELS = {
        "threeBetRate": ("3-BET", "3BET"),
        "cBetRate": ("C-BET", "CBET"),
        "showdownRate": ("摊牌率", "攤牌率"),
        "showdownWinRate": ("摊牌胜率", "攤牌勝率"),
        "aggressionFactor": ("激进度", "激進度"),
        "averageBuyIn": ("场均带入", "場均帶入"),
        "averageResult": ("场均战绩", "場均戰績"),
        "bbPer100": ("每百手盈亏", "每百手盈虧"),
    }
    EXCLUDED_NAME_TEXT = {
        "备注信息", "備註信息", "弹幕", "彈幕", "屏蔽", "举报", "舉報",
        "路人", "弃牌", "棄牌", "本级别手数", "本級別手數",
        "主动入池率", "主動入池率", "总手数", "總手數",
        "加注入池率", "加註入池率",
    }

    @staticmethod
    def _clean(value):
        return re.sub(r"\s+", "", str(value or "")).replace("％", "%").rstrip(":：")

    @classmethod
    def _label_item(cls, items, aliases):
        aliases = {cls._clean(alias) for alias in aliases}
        matches = [item for item in items if cls._clean(item.get("text")) in aliases]
        return max(matches, key=lambda item: float(item.get("confidence", 0)), default=None)

    @classmethod
    def popup_visible(cls, items):
        return sum(cls._label_item(items, aliases) is not None
                   for aliases in cls.LABELS.values()) >= 3

    @staticmethod
    def _number(item, percent=False):
        text = str(item.get("text") or "").replace("％", "%")
        match = re.search(r"\d+(?:\.\d+)?", text)
        if not match:
            return None
        value = float(match.group())
        if percent:
            if "%" not in text or not 0 <= value <= 100:
                return None
            return value / 100
        if not value.is_integer() or value < 0:
            return None
        return int(value)

    @classmethod
    def _value_below(cls, items, label, column_width, percent=False):
        candidates = []
        for item in items:
            if float(item.get("confidence", 0)) < .70:
                continue
            delta_y = float(item.get("cy", 0)) - float(label.get("cy", 0))
            delta_x = abs(float(item.get("cx", 0)) - float(label.get("cx", 0)))
            if not column_width * .06 <= delta_y <= column_width * .70 or delta_x > column_width * .55:
                continue
            value = cls._number(item, percent)
            if value is not None:
                candidates.append((delta_y + delta_x * .2, item, value))
        return min(candidates, default=(None, None, None), key=lambda entry: entry[0])[1:]

    @classmethod
    def _name_above(cls, items, label_y, width, column_width, image=None):
        candidates = []
        for item in items:
            text = str(item.get("text") or "").strip()
            clean = re.sub(r"[♂♀⚥⚦⚧]+$", "", cls._clean(text).rstrip(".…"))
            confidence = float(item.get("confidence", 0))
            cx, cy = float(item.get("cx", 0)), float(item.get("cy", 0))
            if not clean or confidence < .70 or clean in cls.EXCLUDED_NAME_TEXT:
                continue
            if not label_y - column_width * 1.35 <= cy <= label_y - column_width * .35 or not width * .20 <= cx <= width * .80:
                continue
            if re.fullmatch(r"[$+\-]?\d+(?:\.\d+)?%?", clean) or len(clean) < 2:
                continue
            if re.fullmatch(r"(?:id[:：]?)?\d{5,}", clean, re.IGNORECASE):
                continue
            if any(word in clean.casefold() for word in ("jp", "mvp", "allin", "all-in")):
                continue
            if clean[-1:] in "Oo0" and cls._has_gender_icon(item, image):
                clean = clean[:-1]
            if len(clean) >= 2:
                candidates.append((cy, -confidence, clean))
        return min(candidates, default=(0, 0, ""))[-1]

    @staticmethod
    def _has_gender_icon(item, image):
        if image is None or any(item.get(key) is None for key in ("x1", "x2", "y1", "y2")):
            return False
        height, width = image.shape[:2]
        x1, x2 = int(item["x1"]), int(item["x2"])
        y1, y2 = int(item["y1"]), int(item["y2"])
        glyph_width = max(12, y2 - y1)
        patch = image[max(0, y1):min(height, y2),
                      max(0, x1, x2 - glyph_width):min(width, x2)]
        if patch.size == 0:
            return False
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        hue, saturation, value = cv2.split(hsv)
        colored = (saturation > 70) & (value > 70) & (
            ((hue >= 85) & (hue <= 135)) | (hue >= 140) | (hue <= 8))
        return int(colored.sum()) >= max(6, patch.shape[0] * patch.shape[1] // 40)

    @staticmethod
    def _metric_number(item, kind):
        text = str(item.get("text") or "").replace("％", "%")
        match = re.search(r"[+\-]?\d+(?:\.\d+)?", text)
        if not match:
            return None
        value = float(match.group())
        if kind == "percent":
            return value / 100 if "%" in text and 0 <= value <= 100 else None
        if kind == "bb":
            return value if re.search(r"bb", text, re.IGNORECASE) else None
        return value

    @classmethod
    def _value_right(cls, items, label, width, kind):
        candidates = []
        for item in items:
            if item is label or float(item.get("confidence", 0)) < .70:
                continue
            delta_x = float(item.get("cx", 0)) - float(label.get("cx", 0))
            delta_y = abs(float(item.get("cy", 0)) - float(label.get("cy", 0)))
            if not width * .05 <= delta_x <= width * .42 or delta_y > 45:
                continue
            value = cls._metric_number(item, kind)
            if value is not None:
                candidates.append((delta_x + delta_y * 5, item, value))
        return min(candidates, default=(None, None, None), key=lambda entry: entry[0])[1:]

    @classmethod
    def parse(cls, items, width, height, image=None):
        labels = {field: cls._label_item(items, aliases)
                  for field, aliases in cls.LABELS.items()}
        missing = [field for field, item in labels.items() if item is None]
        if missing:
            raise ValueError("头像统计弹窗标签不完整：" + "、".join(missing))
        if max(float(item.get("cy", 0)) for item in labels.values()) - min(
                float(item.get("cy", 0)) for item in labels.values()) > 35:
            raise ValueError("头像统计弹窗标签不在同一行")
        label_x = sorted(float(item.get("cx", 0)) for item in labels.values())
        column_width = sum(right - left for left, right in zip(label_x, label_x[1:])) / 3
        if column_width <= 0:
            raise ValueError("头像统计弹窗列宽无效")

        values = {}
        value_items = {}
        for field, label in labels.items():
            item, value = cls._value_below(items, label, column_width, field.endswith("Rate"))
            if item is None:
                raise ValueError(f"未识别到{field}的数值")
            values[field] = value
            value_items[field] = item

        if values["totalHands"] < values["levelHands"]:
            raise ValueError("总手数小于本级别手数")
        if values["pfrRate"] > values["vpipRate"] + .001:
            raise ValueError("加注入池率高于主动入池率")
        label_y = sum(float(item.get("cy", 0)) for item in labels.values()) / len(labels)
        name = cls._name_above(items, label_y, width, column_width, image)
        if not name:
            raise ValueError("未识别到弹窗中的玩家名称")
        confidences = [float(item.get("confidence", 0)) for item in labels.values()]
        confidences.extend(float(item.get("confidence", 0)) for item in value_items.values())
        result = {
            "name": name,
            **values,
            "confidence": min(confidences),
            "rateDenominatorAssumption": "levelHands",
            "labelY": label_y,
            "columnWidth": column_width,
            "popupRegion": [
                max(0, int(width * .08)), max(0, int(label_y - 170)),
                min(width, int(width * .92)), min(height, int(label_y + 360)),
            ],
        }
        metric_kinds = {
            "threeBetRate": "percent", "cBetRate": "percent",
            "showdownRate": "percent", "showdownWinRate": "percent",
            "aggressionFactor": "decimal", "averageBuyIn": "decimal",
            "averageResult": "decimal", "bbPer100": "bb",
        }
        for field, aliases in cls.ADVANCED_LABELS.items():
            label = cls._label_item(items, aliases)
            if label is None:
                continue
            item, value = cls._value_right(items, label, width, metric_kinds[field])
            if item is not None:
                result[field] = value
                result[f"{field}Confidence"] = float(item.get("confidence", 0))
        return result
