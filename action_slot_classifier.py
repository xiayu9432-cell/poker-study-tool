import json
from pathlib import Path

import cv2
import numpy as np


ACTION_WORDS_EN = [(word, 'straddle') for word in
                   ('straddle', 'stradl', 'stradle', 'sradl', 'stadl', '跳盲', '跨注')]


ACTION_WORDS = [('补盲', 'post_blind'), ('让牌', 'check'), ('跟注', 'call'), ('下注', 'bet'),
                ('加注', 'raise'), ('全下', 'all_in'), ('弃牌', 'fold'), ('弃', 'fold')]


class ActionSlotClassifier:
    def __init__(self, api, labels_path):
        self.api = api
        labels_path = Path(labels_path)
        rows = json.loads(labels_path.read_text(encoding='utf-8'))
        self.templates = []
        for row in rows:
            if not row.get('label'):
                continue
            image_path = labels_path.parent / row['image']
            image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            if image is not None:
                self.templates.append((row['label'], self._feature(image)))

    @staticmethod
    def _feature(image):
        resized = cv2.resize(image, (96, 48), interpolation=cv2.INTER_AREA)
        normalized = cv2.equalizeHist(resized).astype(np.float32)
        normalized -= normalized.mean()
        length = np.linalg.norm(normalized)
        return normalized / length if length else normalized

    def classify(self, crop, ocr_line=None):
        upscaled = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        text, confidence = (ocr_line or self.api._ocr_line)(upscaled)
        action = next((label for word, label in ACTION_WORDS_EN + ACTION_WORDS
                       if word.lower() in text.lower()), None)
        feature = self._feature(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))
        if action:
            same_action = [float(np.sum(feature * template)) for label, template in self.templates if label == action]
            template_score = max(same_action, default=0)
            combined = max(float(confidence), template_score)
            if confidence >= .72 or template_score >= .78:
                return action, text, combined, 'ocr+template' if template_score >= .78 else 'ocr'
        scores = [(float(np.sum(feature * template)), label) for label, template in self.templates]
        scores.sort(reverse=True)
        return None, text, float(confidence or 0), 'unknown'
