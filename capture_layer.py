import time
from collections import deque

import cv2
import numpy as np
from PIL import ImageGrab


class CaptureLayer:
    def __init__(self, buffer_seconds=10.0):
        self.buffer_seconds = float(buffer_seconds)

    @staticmethod
    def grab(bbox):
        image = ImageGrab.grab(bbox=tuple(bbox), all_screens=True).convert("RGB")
        return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR), time.time()

    @staticmethod
    def encode(sequence, captured_at, bbox, frame):
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return None
        return {"sequence": sequence, "capturedAt": captured_at, "bbox": list(bbox),
                "jpeg": encoded.tobytes()}

    def append(self, buffer, item):
        buffer.append(item)
        cutoff = item["capturedAt"] - self.buffer_seconds
        while buffer and buffer[0]["capturedAt"] < cutoff:
            buffer.popleft()

    @staticmethod
    def status(buffer, dropped, queued):
        count = len(buffer)
        span = buffer[-1]["capturedAt"] - buffer[0]["capturedAt"] if count > 1 else 0.0
        memory = sum(len(item["jpeg"]) for item in buffer)
        return {"frames": count, "seconds": round(span, 3),
                "memoryMb": round(memory / 1048576, 1),
                "dropped": dropped, "queue": queued}
