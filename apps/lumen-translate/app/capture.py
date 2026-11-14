"""截屏取字：全屏选区浮层 + 抓图。"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable

from . import win32
from .theme import COLORS, Fonts

# 选区太小就当成误触
MIN_SIZE = 8


def grab_region(bbox: tuple[int, int, int, int], path: str | Path | None = None) -> Path:
    """抓取屏幕上一块区域，存成 PNG 返回路径。

    bbox 是 (left, top, right, bottom) 屏幕坐标，允许跨显示器（all_screens）。
    """

    from PIL import ImageGrab  # 延迟导入，免得没装 Pillow 时连模块都进不来

    left, top, right, bottom = (int(v) for v in bbox)
    left, right = min(left, right), max(left, right)
    top, bottom = min(top, bottom), max(top, bottom)
    image = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    if path is None:
        import tempfile

        path = Path(tempfile.gettempdir()) / "lumen_shot.png"
    path = Path(path)
    image.save(path, "PNG")
    return path


def normalize_bbox(x1: int, y1: int, x2: int, y2: int) -> tuple[int, int, int, int]:
    return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))


# 超过这个像素数就不再放大，免得 OCR 太慢
UPSCALE_LIMIT = 1_200_000


def preprocess_for_ocr(image_path: str | Path, scale: int = 2, shift: int = 1) -> Path:
    """给 Windows OCR 做预处理：次像素对齐合成灰度 + 放大。

    屏幕上的小字是 ClearType 次像素渲染的（每个字形的笔画落在 1/3 像素上并带
    彩色边缘），Windows OCR 对它的英文识别率很差（"Screenshot"→"creenshot"）。
    按 R/G/B 的次像素顺序把三个通道各错开一点再合成灰度，等于把次像素位置还原
    成真实亮度，配合放大 2 倍，英文识别率会有肉眼可见的提升。
    """

    import numpy as np
    from PIL import Image

    image_path = Path(image_path)
    image = Image.open(image_path).convert("RGB")
    if image.width * image.height > UPSCALE_LIMIT:
        scale = 1
    array = np.asarray(image).astype("float32")
    red = np.roll(array[:, :, 0], shift, axis=1)
    blue = np.roll(array[:, :, 2], -shift, axis=1)
    gray = ((red + array[:, :, 1] + blue) / 3.0).clip(0, 255).astype("uint8")
    result = Image.fromarray(gray)
    if scale > 1:
        result = result.resize((result.width * scale, result.height * scale), Image.LANCZOS)
    target = image_path.with_name(image_path.stem + f"_ocr{scale}x.png")
    result.save(target)
    return target


class RegionSelector(tk.Toplevel):
    """全屏压暗 + 十字光标，拖一块出来就回调。

    on_done(bbox) 的 bbox 是屏幕坐标；Esc / 右键 / 选区太小 = on_cancel()。
    """

    def __init__(self, master: tk.Misc, on_done: Callable[[tuple[int, int, int, int]], None], on_cancel: Callable[[], None]):
        super().__init__(master)
        self.on_done = on_done
        self.on_cancel = on_cancel
        self.vx, self.vy, self.vw, self.vh = win32.virtual_screen()
        self.start: tuple[int, int] | None = None
        self.rect_id: int | None = None
        self.size_id: int | None = None
        self.lines: list[int] = []

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.30)  # 整屏压暗，选区看得更清楚
        except tk.TclError:
            pass
        self.configure(bg="#05080c")
        self.geometry(f"{self.vw}x{self.vh}+{self.vx}+{self.vy}")

        self.canvas = tk.Canvas(self, bg="#05080c", highlightthickness=0, cursor="crosshair", bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(
            self.vw // 2, 34,
            text="拖动鼠标框选要翻译的区域    ·    Esc 取消",
            fill=COLORS["accent"], font=(Fonts.ui, 13, "bold"),
        )

        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", lambda _e: self._cancel())
        self.bind("<Escape>", lambda _e: self._cancel())
        self.canvas.bind("<Motion>", self._on_hover)

        self.after(30, self._take_focus)

    def _take_focus(self) -> None:
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    # -- 交互 ------------------------------------------------------------
    def _on_press(self, event) -> None:
        self.start = (event.x, event.y)
        if self.rect_id is not None:
            self.canvas.delete(self.rect_id)
            self.rect_id = None

    def _on_drag(self, event) -> None:
        if not self.start:
            return
        x1, y1 = self.start
        x2, y2 = event.x, event.y
        if self.rect_id is None:
            self.rect_id = self.canvas.create_rectangle(x1, y1, x2, y2, outline=COLORS["accent"], width=2)
        else:
            self.canvas.coords(self.rect_id, x1, y1, x2, y2)
        width, height = abs(x2 - x1), abs(y2 - y1)
        label = f"{width} × {height}"
        if self.size_id is None:
            self.size_id = self.canvas.create_text(x2 + 10, y2 + 14, text=label, anchor="nw", fill=COLORS["text"], font=Fonts.mono_sm)
        else:
            self.canvas.coords(self.size_id, x2 + 10, y2 + 14)
            self.canvas.itemconfigure(self.size_id, text=label)

    def _on_release(self, event) -> None:
        if not self.start:
            return
        left, top, right, bottom = normalize_bbox(self.start[0], self.start[1], event.x, event.y)
        if right - left < MIN_SIZE or bottom - top < MIN_SIZE:
            self._cancel()
            return
        bbox = (left + self.vx, top + self.vy, right + self.vx, bottom + self.vy)
        self._finish()
        self.on_done(bbox)

    def _on_hover(self, event) -> None:
        """悬停时画两条细辅助线，方便对齐。"""

        for item in self.lines:
            self.canvas.delete(item)
        self.lines = [
            self.canvas.create_line(0, event.y, self.vw, event.y, fill="#2b3b4a", width=1),
            self.canvas.create_line(event.x, 0, event.x, self.vh, fill="#2b3b4a", width=1),
        ]
        for item in self.lines:
            self.canvas.tag_lower(item)

    def _cancel(self) -> None:
        self._finish()
        self.on_cancel()

    def _finish(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
