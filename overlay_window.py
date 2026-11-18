import ctypes
import ctypes.wintypes
import threading
import tkinter as tk


GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
WS_EX_LAYERED = 0x80000
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
GA_ROOT = 2
LWA_COLORKEY = 0x00000001
TRANSPARENT_COLOR = "#010203"
TRANSPARENT_COLORREF = 0x030201
BORDER_COLOR = "#ffb000"
BORDER_WIDTH = 10


class OverlayWindow:
    def __init__(self):
        self.commands = []
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.ready.wait(5)

    def update(self, bbox, message="", arrow=None, visible=True, color=BORDER_COLOR):
        with self.lock:
            self.commands.append((bbox, message, arrow, visible, color))

    def close(self):
        if getattr(self, "root", None) is not None:
            self.root.after(0, self.root.destroy)

    def _run(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.border_windows = [self._border_window(self.root)] + [self._border_window() for _ in range(3)]
        self.message_window = self._message_window()
        self.ready.set()
        self._tick()
        self.root.mainloop()

    def _border_window(self, window=None):
        window = window or tk.Toplevel(self.root)
        window.withdraw()
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.configure(bg=BORDER_COLOR)
        window.update_idletasks()
        hwnd = self._root_hwnd(window)
        self._set_click_through(hwnd, layered=False)
        return window, hwnd

    def _message_window(self):
        window = tk.Toplevel(self.root)
        window.withdraw()
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.configure(bg=TRANSPARENT_COLOR)
        canvas = tk.Canvas(window, bg=TRANSPARENT_COLOR, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        window.update_idletasks()
        hwnd = self._root_hwnd(window)
        self._set_click_through(hwnd, layered=True)
        if not ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, TRANSPARENT_COLORREF, 255, LWA_COLORKEY):
            raise ctypes.WinError()
        return window, canvas, hwnd

    @staticmethod
    def _root_hwnd(window):
        child_hwnd = window.winfo_id()
        return ctypes.windll.user32.GetAncestor(child_hwnd, GA_ROOT) or child_hwnd

    @staticmethod
    def _set_click_through(hwnd, layered):
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
        if layered:
            style |= WS_EX_LAYERED
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

    def _tick(self):
        command = None
        with self.lock:
            if self.commands:
                command = self.commands[-1]
                self.commands.clear()
        if command:
            self._render(*command)
        self.root.after(60, self._tick)

    def _render(self, bbox, message, arrow, visible, color):
        if not visible or not bbox:
            self._hide()
            return
        x1, y1, x2, y2 = map(int, bbox)
        width, height = max(10, x2 - x1), max(10, y2 - y1)
        border = min(BORDER_WIDTH, max(2, min(width, height) // 4))
        geometries = (
            (x1, y1, width, border),
            (x1, y2 - border, width, border),
            (x1, y1, border, height),
            (x2 - border, y1, border, height),
        )
        for (window, hwnd), (x, y, item_width, item_height) in zip(self.border_windows, geometries):
            window.configure(bg=color)
            window.geometry(f"{item_width}x{item_height}+{x}+{y}")
            window.deiconify()
            window.update_idletasks()
            window.lift()
            ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, item_width, item_height, SWP_NOACTIVATE)
        self._render_message((x1, y1, width, height), message, arrow)

    def _render_message(self, geometry, message, arrow):
        window, canvas, hwnd = self.message_window
        if not message and not arrow:
            window.withdraw()
            return
        x, y, width, height = geometry
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.deiconify()
        window.update_idletasks()
        window.lift()
        ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, width, height, SWP_NOACTIVATE)
        canvas.delete("all")
        if message:
            canvas.create_rectangle(width * .17, height * .31, width * .83, height * .39, fill="#101713", outline="#70eda2", width=2)
            canvas.create_text(width * .50, height * .35, text=message, fill="white", font=("Microsoft YaHei", max(10, int(width * .025)), "bold"), width=width * .62)
        if arrow:
            target_x = arrow["x"] * width
            target_y = arrow["y"] * height
            start_y = max(45, target_y - height * .13)
            color = "#ffdf3f" if arrow.get("blink", False) else "#70eda2"
            canvas.create_oval(target_x - 20, target_y - 20, target_x + 20, target_y + 20, outline=color, width=5)
            canvas.create_line(target_x, start_y, target_x, target_y - 22, fill=color, width=max(7, int(width * .012)), arrow=tk.LAST, arrowshape=(26, 32, 12))
            canvas.create_text(target_x, start_y - 12, text=arrow.get("label", "建议"), fill=color, font=("Microsoft YaHei", max(11, int(width * .026)), "bold"))

    def _hide(self):
        for window, _ in self.border_windows:
            window.withdraw()
        self.message_window[0].withdraw()
