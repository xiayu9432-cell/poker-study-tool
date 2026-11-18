import cv2
from rapidocr_onnxruntime import RapidOCR


class AvatarStateClassifier:
    STATES = (
        ("fold", ("弃牌", "奔牌", "fold", "폴탬", "폴", "쒜탬", "굴탬")),
        ("waiting", ("等待",)),
        ("away", ("暂离",)),
        ("allin", ("全下", "all in", "allin", "all-in")),
        ("free_raise", ("自由加注",)),
        ("showdown", ("比牌",)),
    )

    def __init__(self, api):
        self.api = api
        self.ocr = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)

    @classmethod
    def _state_from_text(cls, text, confidence):
        normalized = text.lower().replace(" ", "")
        low_confidence = confidence < 0.72
        if "弃牌" in normalized or "fold" in normalized or normalized in ("奔牌", "굴탬"):
            return "fold"
        for state in ("away", "waiting"):
            words = next(words for candidate, words in cls.STATES if candidate == state)
            if any(word.lower() in normalized for word in words):
                return state
        if normalized == "离" or ("离" in normalized and any(char.isdigit() for char in normalized)):
            return "away"
        if any(char.isdigit() for char in normalized) and "s" in normalized:
            return "thinking"
        if low_confidence:
            return "unknown"
        if normalized == "åæ":
            return "fold"
        for state, words in cls.STATES:
            if any(word.lower() in normalized for word in words):
                return state
        return "unknown"

    def classify(self, crop, ocr=None):
        height = crop.shape[0]
        line_crop = crop[int(height * .10):int(height * .70)]
        line_upscaled = cv2.resize(line_crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        upscaled = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        engine = ocr or self.ocr
        result, _ = engine(line_upscaled, use_det=False, use_cls=False, use_rec=True)
        if result:
            item = result[0] if isinstance(result, list) else result
            text, confidence = str(item[0]), float(item[1])
        else:
            text, confidence = "", 0.0
        state = self._state_from_text(text, confidence)
        if state != "unknown":
            return state, text, confidence
        result, _ = engine(upscaled)
        text = "".join(item[1] for item in (result or []))
        confidence = min((float(item[2]) for item in (result or [])), default=0)
        return self._state_from_text(text, confidence), text, confidence

    def classify_line(self, crop, ocr):
        height = crop.shape[0]
        line_crop = crop[int(height * .25):int(height * .65)]
        image = cv2.resize(line_crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        result, _ = ocr(image, use_det=False, use_cls=False, use_rec=True)
        text = str(result[0][0]) if result else ""
        confidence = float(result[0][1]) if result else 0.0
        return self._state_from_text(text, confidence), text, confidence
