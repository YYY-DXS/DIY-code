"""自绘控件：圆角按钮、开关、卡片、渐变分隔线。"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import font as tkfont
from typing import Callable

from .theme import COLORS, Fonts


def lerp_color(a: str, b: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    a = a.lstrip("#")
    b = b.lstrip("#")
    out = []
    for i in (0, 2, 4):
        x = int(a[i : i + 2], 16)
        y = int(b[i : i + 2], 16)
        out.append(round(x + (y - x) * t))
    return "#%02X%02X%02X" % tuple(out)


def rounded_points(x1: float, y1: float, x2: float, y2: float, r: float, steps: int = 7) -> list[float]:
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts: list[float] = []
    corners = (
        (x2 - r, y1 + r, -90.0, 0.0),
        (x2 - r, y2 - r, 0.0, 90.0),
        (x1 + r, y2 - r, 90.0, 180.0),
        (x1 + r, y1 + r, 180.0, 270.0),
    )
    for cx, cy, a0, a1 in corners:
        for i in range(steps + 1):
            ang = math.radians(a0 + (a1 - a0) * i / steps)
            pts.extend((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


class Card(tk.Frame):
    """带 1px 描边的圆角面板（用底层 Frame 做描边实现）。"""

    def __init__(self, master: tk.Misc, radius: int = 14, fill: str | None = None, border: str | None = None, **kw):
        fill = fill or COLORS["surface"]
        border = border or COLORS["border"]
        super().__init__(master, bg=border, bd=0, highlightthickness=0, **kw)
        self.canvas = tk.Canvas(self, bg=border, bd=0, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self._radius = radius
        self._fill = fill
        self._border = border
        self.body = tk.Frame(self.canvas, bg=fill, bd=0, highlightthickness=0)
        self._win = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", self._redraw)

    def set_colors(self, fill: str | None = None, border: str | None = None) -> None:
        if fill:
            self._fill = fill
            self.body.configure(bg=fill)
        if border:
            self._border = border
            self.canvas.configure(bg=border)
        self._redraw()

    def _redraw(self, _event=None) -> None:
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        self.canvas.delete("bg")
        if w < 4 or h < 4:
            return
        pad = 1
        pts = rounded_points(pad, pad, w - pad, h - pad, self._radius, 8)
        self.canvas.create_polygon(pts, fill=self._fill, outline=self._border, width=1, tags="bg")
        self.canvas.tag_lower("bg")
        self.canvas.itemconfigure(self._win, width=w - 2 * pad - 2, height=h - 2 * pad - 2)
        self.canvas.coords(self._win, pad + 1, pad + 1)


class RoundedButton(tk.Canvas):
    """圆角按钮，支持 primary / ghost / subtle 三种风格与悬停过渡。"""

    VARIANTS = {
        "primary": (COLORS["accent"], "#0A1018", "#67E8F9", "#0E5C6E"),
        "violet": (COLORS["violet"], "#FFFFFF", "#A78BFA", "#5B21B6"),
        "ghost": (COLORS["surface2"], COLORS["text_dim"], COLORS["surface3"], COLORS["accent"]),
        "subtle": (COLORS["surface"], COLORS["text_dim"], COLORS["surface3"], COLORS["text"]),
        "danger": (COLORS["surface2"], COLORS["err"], "#3A1D22", COLORS["err"]),
    }

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command: Callable[[], None] | None = None,
        variant: str = "ghost",
        width: int | None = None,
        height: int = 36,
        radius: int = 9,
        font: tuple | None = None,
        padx: int = 16,
    ):
        bg, fg, hover, _ = self.VARIANTS.get(variant, self.VARIANTS["ghost"])
        self._font = font or Fonts.ui_md
        try:
            text_w = tkfont.Font(root=master, font=self._font).measure(text)
        except Exception:
            text_w = len(text) * 9
        w = width or text_w + padx * 2
        super().__init__(master, width=w, height=height, bg=master["bg"], bd=0, highlightthickness=0, cursor="hand2")
        self._base, self._fg, self._hover = bg, fg, hover
        self._radius = radius
        self._height = height
        self._command = command
        self._enabled = True
        self._t = 0.0
        self._shape = None
        self._label = self.create_text(w / 2, height / 2 + 1, text=text, fill=fg, font=self._font)
        self.bind("<Configure>", self._redraw)
        self.bind("<Enter>", lambda _e: self._animate(1.0))
        self.bind("<Leave>", lambda _e: self._animate(0.0))
        self.bind("<Button-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)

    # -- 绘制 ------------------------------------------------------------
    def _redraw(self, _event=None) -> None:
        w = self.winfo_width() or int(self["width"])
        h = self.winfo_height() or self._height
        color = lerp_color(self._base, self._hover, self._t) if self._enabled else COLORS["surface2"]
        fg = self._fg if self._enabled else COLORS["text_mute"]
        self.delete("shape")
        pts = rounded_points(0.5, 0.5, w - 0.5, h - 0.5, self._radius, 7)
        self._shape = self.create_polygon(pts, fill=color, outline="", tags="shape")
        self.tag_lower("shape")
        self.itemconfigure(self._label, fill=fg)
        self.coords(self._label, w / 2, h / 2 + 1)

    def _animate(self, target: float) -> None:
        if not self._enabled:
            return
        step = 0.22 if target > self._t else -0.22
        value = self._t + step
        if (step > 0 and value >= target) or (step < 0 and value <= target):
            value = target
        self._t = value
        self._redraw()
        if abs(self._t - target) > 1e-3:
            self.after(16, lambda: self._animate(target))

    # -- 交互 ------------------------------------------------------------
    def _press(self, _event) -> None:
        if self._enabled:
            self.move(self._label, 0, 1)

    def _release(self, _event) -> None:
        if not self._enabled:
            return
        self.move(self._label, 0, -1)
        if self._command:
            self._command()

    def set_text(self, text: str) -> None:
        self.itemconfigure(self._label, text=text)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._t = 0.0
        self._redraw()

    def set_variant(self, variant: str) -> None:
        bg, fg, hover, _ = self.VARIANTS.get(variant, self.VARIANTS["ghost"])
        self._base, self._fg, self._hover = bg, fg, hover
        self._t = 0.0
        self._redraw()


class ToggleSwitch(tk.Canvas):
    """小型滑动开关，右侧带文字标签。"""

    def __init__(
        self,
        master: tk.Misc,
        text: str = "",
        command: Callable[[bool], None] | None = None,
        value: bool = False,
        width: int = 40,
        height: int = 21,
    ):
        self._label_w = 0
        self._text = text
        if text:
            try:
                text_w = tkfont.Font(root=master, font=Fonts.ui_sm).measure(text)
            except Exception:
                text_w = len(text) * 14
            self._label_w = text_w + 8
        total = width + self._label_w
        super().__init__(master, width=total, height=height, bg=master["bg"], bd=0, highlightthickness=0, cursor="hand2")
        # 注意：不能叫 self._w，那是 tkinter 内部保存控件路径名的属性
        self._track_w, self._h = width, height
        self._on = value
        self._command = command
        self._t = 1.0 if value else 0.0
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Button-1>", self._toggle)
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        h = self._h
        r = h / 2
        track = lerp_color(COLORS["surface3"], COLORS["accent_dk"], self._t)
        pts = rounded_points(0.5, 0.5, self._track_w - 0.5, h - 0.5, r, 8)
        self.create_polygon(pts, fill=track, outline=lerp_color(COLORS["border"], COLORS["accent"], self._t))
        knob_x = r + self._t * (self._track_w - 2 * r)
        knob_color = lerp_color(COLORS["text_mute"], COLORS["accent_hi"], self._t)
        self.create_oval(knob_x - r + 3, 3, knob_x + r - 3, h - 3, fill=knob_color, outline="")
        if self._text:
            self.create_text(self._track_w + 6, h / 2 + 1, text=self._text, anchor="w", fill=COLORS["text_dim"], font=Fonts.ui_sm)

    def _redraw(self) -> None:
        self._draw()

    def _toggle(self, _event=None) -> None:
        self.set(not self._on, notify=True)

    def set(self, value: bool, notify: bool = False) -> None:
        target = 1.0 if value else 0.0
        self._on = value
        step = 0.25 if target > self._t else -0.25
        value_t = self._t + step
        if (step > 0 and value_t >= target) or (step < 0 and value_t <= target):
            value_t = target
        self._t = value_t
        self._draw()
        if abs(self._t - target) > 1e-3:
            self.after(16, lambda: self.set(value, notify=False))
        elif notify and self._command:
            self._command(value)

    @property
    def value(self) -> bool:
        return self._on


class GradientRule(tk.Canvas):
    """一段从青色渐变到紫色再淡出的发丝线，用来做科技风分隔。"""

    def __init__(self, master: tk.Misc, height: int = 2, **kw):
        super().__init__(master, height=height, bg=master["bg"], bd=0, highlightthickness=0, **kw)
        self._h = height
        self.bind("<Configure>", self._redraw)

    def _redraw(self, _event=None) -> None:
        self.delete("all")
        w = self.winfo_width()
        if w < 4:
            return
        steps = max(2, w // 2)
        for i in range(steps):
            t = i / (steps - 1)
            if t < 0.55:
                color = lerp_color(COLORS["accent"], COLORS["violet"], t / 0.55)
            else:
                color = lerp_color(COLORS["violet"], COLORS["surface"], (t - 0.55) / 0.45)
            x0 = i * w / steps
            self.create_line(x0, 0, x0 + w / steps + 1, 0, fill=color, width=self._h)


class GridBackdrop(tk.Canvas):
    """淡淡的网格底纹，制造"仪表盘"质感。"""

    def __init__(self, master: tk.Misc, height: int = 58, step: int = 22, **kw):
        super().__init__(master, height=height, bg=COLORS["surface"], bd=0, highlightthickness=0, **kw)
        self._step = step
        self.bind("<Configure>", self._redraw)

    def _redraw(self, _event=None) -> None:
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 4:
            return
        line = "#121B25"
        for x in range(0, w, self._step):
            self.create_line(x, 0, x, h, fill=line)
        for y in range(0, h, self._step):
            self.create_line(0, y, w, y, fill=line)
        for x in range(0, w, self._step * 2):
            for y in range(0, h, self._step * 2):
                self.create_line(x - 2, y, x + 3, y, fill="#1B2A38")
                self.create_line(x, y - 2, x, y + 3, fill="#1B2A38")


class SwapButton(tk.Canvas):
    """圆形换向按钮，箭头是画出来的，不依赖字体里有没有 ⇄ 字形。"""

    def __init__(self, master: tk.Misc, command: Callable[[], None], size: int = 46):
        super().__init__(master, width=size, height=size, bg=master["bg"], bd=0, highlightthickness=0, cursor="hand2")
        self._size = size
        self._command = command
        self._hover = False
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<Button-1>", lambda _e: self._command())
        self._draw()

    def _set_hover(self, value: bool) -> None:
        self._hover = value
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        s = self._size
        c = s / 2
        ring = COLORS["accent"] if self._hover else COLORS["border_hi"]
        fill = COLORS["surface3"] if self._hover else COLORS["surface2"]
        col = COLORS["accent"] if self._hover else COLORS["text_dim"]
        self.create_oval(1, 1, s - 1, s - 1, outline=ring, fill=fill, width=1)
        x0, x1 = c - 8.5, c + 8.5
        y1, y2 = c - 5.5, c + 5.5
        self.create_line(x0, y1, x1 - 1.5, y1, fill=col, width=2, capstyle="round")
        self.create_line(x1 - 6, y1 - 4, x1 - 1.5, y1, x1 - 6, y1 + 4, fill=col, width=2, capstyle="round", joinstyle="round")
        self.create_line(x1, y2, x0 + 1.5, y2, fill=col, width=2, capstyle="round")
        self.create_line(x0 + 6, y2 - 4, x0 + 1.5, y2, x0 + 6, y2 + 4, fill=col, width=2, capstyle="round", joinstyle="round")


class StatusDot(tk.Canvas):
    """状态圆点，带呼吸光晕。"""

    def __init__(self, master: tk.Misc, color: str | None = None, size: int = 14):
        super().__init__(master, width=size, height=size, bg=master["bg"], bd=0, highlightthickness=0)
        self._size = size
        self._color = color or COLORS["text_mute"]
        self._pulse = 0.0
        self._running = False
        self.bind("<Configure>", lambda _e: self._draw())
        self._draw()

    def set_color(self, color: str) -> None:
        self._color = color
        self._draw()

    def start_pulse(self) -> None:
        if not self._running:
            self._running = True
            self._tick()

    def stop_pulse(self) -> None:
        self._running = False
        self._pulse = 0.0
        self._draw()

    def _tick(self) -> None:
        if not self._running:
            return
        self._pulse = (self._pulse + 0.12) % (2 * math.pi)
        self._draw()
        self.after(50, self._tick)

    def _draw(self) -> None:
        self.delete("all")
        cx = cy = self._size / 2
        r = self._size / 4
        if self._running:
            halo = r + (math.sin(self._pulse) + 1) / 2 * 3
            self.create_oval(cx - halo, cy - halo, cx + halo, cy + halo, outline=lerp_color(self._color, COLORS["surface"], 0.62), width=1)
        self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=self._color, outline="")
