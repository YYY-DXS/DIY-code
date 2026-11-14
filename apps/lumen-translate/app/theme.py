"""视觉主题：深色科技风的配色、字体与控件样式。"""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ---------------------------------------------------------------- 调色板
COLORS = {
    "bg": "#070A0F",          # 窗口底色
    "surface": "#0D131B",     # 卡片
    "surface2": "#121A24",    # 输入区
    "surface3": "#18222E",    # 悬浮 / 次级
    "border": "#1C2836",
    "border_hi": "#2A3B4E",
    "text": "#E8F2F8",
    "text_dim": "#93A7BB",
    "text_mute": "#5C6F83",
    "accent": "#22D3EE",
    "accent_hi": "#67E8F9",
    "accent_dk": "#0E5C6E",
    "violet": "#8B5CF6",
    "ok": "#34D399",
    "warn": "#FBBF24",
    "err": "#F87171",
}

_FALLBACK = {
    "ui": ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", "TkDefaultFont"),
    "mono": ("Cascadia Mono", "Consolas", "JetBrains Mono", "Courier New"),
}

_resolved: dict[str, str] = {}


def _pick(root: tk.Misc, family: str) -> str:
    if family in _resolved:
        return _resolved[family]
    try:
        available = {f.lower() for f in tkfont.families(root)}
    except Exception:  # pragma: no cover - 某些环境下取不到字体列表
        available = set()
    chosen = _FALLBACK[family][-1]
    for cand in _FALLBACK[family]:
        if cand.lower() in available:
            chosen = cand
            break
    _resolved[family] = chosen
    return chosen


class Fonts:
    """窗口字体集合，创建窗口后调用 ``Fonts.init(root)``。"""

    ui = "Segoe UI"
    mono = "Consolas"
    ui_sm = ("Segoe UI", 10)
    ui_md = ("Segoe UI", 10)
    ui_lg = ("Segoe UI", 11)
    ui_xl = ("Segoe UI", 14, "bold")
    ui_bold = ("Segoe UI", 10, "bold")
    brand = ("Segoe UI", 13, "bold")
    mono_sm = ("Consolas", 9)
    mono_xs = ("Consolas", 8)
    editor = ("Segoe UI", 12)
    readout = ("Segoe UI", 12)

    @classmethod
    def init(cls, root: tk.Misc) -> None:
        cls.ui = _pick(root, "ui")
        cls.mono = _pick(root, "mono")
        u = cls.ui
        m = cls.mono
        # 小字号的中文会糊，9 号只留给纯 ASCII 的等宽标签
        cls.ui_sm = (u, 10)
        cls.ui_md = (u, 10)
        cls.ui_lg = (u, 11)
        cls.ui_xl = (u, 15, "bold")
        cls.ui_bold = (u, 10, "bold")
        cls.brand = (u, 14, "bold")
        cls.mono_sm = (m, 9)
        cls.mono_xs = (m, 8)
        cls.editor = (u, 12)
        cls.readout = (u, 12)


# ---------------------------------------------------------------- 深色标题栏
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36


def _colorref(hex_color: str) -> int:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return r | (g << 8) | (b << 16)


def apply_dark_titlebar(window: tk.Misc) -> None:
    """把 Windows 原生标题栏染成与界面一致的深色。"""

    if sys.platform != "win32":
        return
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            return
        value = ctypes.c_int(1)
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value))
        caption = ctypes.c_int(_colorref(COLORS["surface"]))
        text = ctypes.c_int(_colorref(COLORS["text"]))
        border = ctypes.c_int(_colorref(COLORS["border"]))
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(caption), ctypes.sizeof(caption))
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_TEXT_COLOR, ctypes.byref(text), ctypes.sizeof(text))
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(border), ctypes.sizeof(border))
    except Exception:
        pass


def enable_dpi_awareness() -> None:
    """避免高分屏下窗口发虚。"""

    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def apply_ttk_theme(root: tk.Misc) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    c = COLORS
    style.configure(
        "Lumen.TCombobox",
        fieldbackground=c["surface2"],
        background=c["surface2"],
        foreground=c["text"],
        arrowcolor=c["accent"],
        bordercolor=c["border"],
        lightcolor=c["surface2"],
        darkcolor=c["surface2"],
        insertcolor=c["text"],
        relief="flat",
        padding=(10, 5),
    )
    style.map(
        "Lumen.TCombobox",
        fieldbackground=[("readonly", c["surface2"]), ("disabled", c["surface3"])],
        foreground=[("readonly", c["text"])],
        bordercolor=[("focus", c["accent_dk"]), ("hover", c["border_hi"])],
        arrowcolor=[("hover", c["accent_hi"])],
    )

    style.configure(
        "Lumen.Vertical.TScrollbar",
        background=c["surface3"],
        troughcolor=c["surface"],
        bordercolor=c["surface"],
        lightcolor=c["surface3"],
        darkcolor=c["surface3"],
        arrowcolor=c["text_mute"],
        relief="flat",
        width=10,
    )
    style.map(
        "Lumen.Vertical.TScrollbar",
        background=[("active", c["border_hi"]), ("pressed", c["accent_dk"])],
    )
    style.configure("Lumen.Horizontal.TScrollbar", background=c["surface3"], troughcolor=c["surface"], relief="flat")

    # 下拉列表（其实是 Tk Listbox）走 option 数据库
    root.option_add("*TCombobox*Listbox.background", c["surface3"])
    root.option_add("*TCombobox*Listbox.foreground", c["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", c["accent_dk"])
    root.option_add("*TCombobox*Listbox.selectForeground", c["accent_hi"])
    root.option_add("*TCombobox*Listbox.borderWidth", 0)
    root.option_add("*TCombobox*Listbox.font", Fonts.ui_md)
    return style
