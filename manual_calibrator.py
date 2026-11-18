import base64
import ctypes
import io
import json
import sys
import tkinter as tk

import cv2
import numpy as np
from PIL import Image, ImageGrab


BORDER_COLOR = "#ffb000"
BORDER_WIDTH = 10


def png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def detect_green(image):
    frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([35, 45, 35]), np.array([100, 255, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (31, 31)))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    options = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if height >= frame.shape[0] * .45 and .30 <= width / max(height, 1) <= .70:
            options.append((width * height, [x, y, x + width, y + height]))
    return max(options)[1] if options else None


def adjust(initial_bbox):
    screenshot = ImageGrab.grab(all_screens=True)
    virtual_left = ctypes.windll.user32.GetSystemMetrics(76)
    virtual_top = ctypes.windll.user32.GetSystemMetrics(77)
    green = detect_green(screenshot)
    green = [virtual_left + green[0], virtual_top + green[1], virtual_left + green[2], virtual_top + green[3]] if green else None
    scale = min(1.0, 2560 / max(screenshot.size))
    preview = screenshot.resize((round(screenshot.width * scale), round(screenshot.height * scale)), Image.Resampling.BILINEAR) if scale < 1 else screenshot
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry(f"{preview.width}x{preview.height}+{virtual_left}+{virtual_top}")
    photo = tk.PhotoImage(data=base64.b64encode(png_bytes(preview)).decode())
    canvas = tk.Canvas(root, highlightthickness=0, width=preview.width, height=preview.height, cursor="fleur")
    canvas.pack(fill="both", expand=True)
    canvas.create_image(0, 0, image=photo, anchor="nw")
    canvas.create_text(20, 20, anchor="nw", text="拖动框内移动；拖四边缩放；Enter 或双击完成；Esc 取消", fill="#ffdf3f", font=("Microsoft YaHei", 16, "bold"))
    outer = [initial_bbox[0] - BORDER_WIDTH, initial_bbox[1] - BORDER_WIDTH, initial_bbox[2] + BORDER_WIDTH, initial_bbox[3] + BORDER_WIDTH]
    rect = [(outer[0] - virtual_left) * scale, (outer[1] - virtual_top) * scale, (outer[2] - virtual_left) * scale, (outer[3] - virtual_top) * scale]
    rect_id = canvas.create_rectangle(*rect, outline=BORDER_COLOR, width=max(4, round(BORDER_WIDTH * scale)))
    state = {"mode": None, "start": None, "original": None, "result": None}

    def hit(x, y):
        x1, y1, x2, y2 = rect
        edge = 16
        if abs(x - x1) <= edge: return "left"
        if abs(x - x2) <= edge: return "right"
        if abs(y - y1) <= edge: return "top"
        if abs(y - y2) <= edge: return "bottom"
        return "move" if x1 < x < x2 and y1 < y < y2 else None

    def down(event):
        state.update(mode=hit(event.x, event.y), start=(event.x, event.y), original=rect.copy())

    def move(event):
        if not state["mode"]: return
        original = state["original"]
        dx, dy = event.x - state["start"][0], event.y - state["start"][1]
        if state["mode"] == "move": rect[:] = [original[0] + dx, original[1] + dy, original[2] + dx, original[3] + dy]
        elif state["mode"] == "left": rect[0] = min(event.x, rect[2] - 100)
        elif state["mode"] == "right": rect[2] = max(event.x, rect[0] + 100)
        elif state["mode"] == "top": rect[1] = min(event.y, rect[3] - 200)
        elif state["mode"] == "bottom": rect[3] = max(event.y, rect[1] + 200)
        canvas.coords(rect_id, *rect)

    def finish(_=None):
        outside = [virtual_left + round(rect[0] / scale), virtual_top + round(rect[1] / scale), virtual_left + round(rect[2] / scale), virtual_top + round(rect[3] / scale)]
        state["result"] = [outside[0] + BORDER_WIDTH, outside[1] + BORDER_WIDTH, outside[2] - BORDER_WIDTH, outside[3] - BORDER_WIDTH]
        root.destroy()

    canvas.bind("<ButtonPress-1>", down)
    canvas.bind("<B1-Motion>", move)
    def release(_):
        state["mode"] = None
        if not green:
            return
        outside = [virtual_left + round(rect[0] / scale), virtual_top + round(rect[1] / scale), virtual_left + round(rect[2] / scale), virtual_top + round(rect[3] / scale)]
        inside = [outside[0] + BORDER_WIDTH, outside[1] + BORDER_WIDTH, outside[2] - BORDER_WIDTH, outside[3] - BORDER_WIDTH]
        snap = 55
        inside = [green[index] if abs(inside[index] - green[index]) <= snap else inside[index] for index in range(4)]
        adjusted = [inside[0] - BORDER_WIDTH, inside[1] - BORDER_WIDTH, inside[2] + BORDER_WIDTH, inside[3] + BORDER_WIDTH]
        rect[:] = [(adjusted[0] - virtual_left) * scale, (adjusted[1] - virtual_top) * scale, (adjusted[2] - virtual_left) * scale, (adjusted[3] - virtual_top) * scale]
        canvas.coords(rect_id, *rect)

    canvas.bind("<ButtonRelease-1>", release)
    canvas.bind("<Double-Button-1>", finish)
    root.bind("<Return>", finish)
    root.bind("<Escape>", lambda _: root.destroy())
    root.after(100, lambda: (root.lift(), root.focus_force()))
    root.mainloop()
    return state["result"]


if __name__ == "__main__":
    result = adjust(json.loads(sys.argv[1]))
    print(json.dumps(result))
