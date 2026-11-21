"""桌面小组件：多窗口卡片版。

- 把天气 / DeepSeek 余额 / 系统资源三张卡拆成独立窗口
- 每张卡可以单独拖动，松手吸附到 40px 网格
- 靠近屏幕边缘/其他卡片时磁吸对齐，显示落点阴影和参考线
- 位置写入 config.json 的 cards 字段，重启后恢复
- 托盘/右键可打开「添加组件」页面，显示/隐藏现有卡片
- widget.py 仅作为渲染/数据模块保留；默认入口是 启动.bat / cards.py
"""

from __future__ import annotations

import asyncio
import ctypes
import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from ctypes import wintypes as wt

from PIL import Image, ImageDraw, ImageFilter

import widget as W

SNAP_GRID = 40
SNAP_MAGNET = 40                 # 磁吸范围：离对齐线 40px 内就吸过去
CARD_GAP = 12                    # 卡片之间统一的视觉间距（DIP）
CARD_MARGIN = 10                 # 裁剪时给阴影留的余量（DIP）
HTTRANSPARENT = -1
HTCLIENT = 1
HWND_BOTTOM = 1
ERROR_ALREADY_EXISTS = 183

CARD_CLASS = "LumenDesktopCard"
HOST_CLASS = "LumenCardsHost"
OVERLAY_CLASS = "LumenCardOverlay"
GALLERY_CLASS = "LumenCardGallery"
DESKTOP_CLASSES = {"Progman", "WorkerW", "SHELLDLL_DefView"}
CARD_WINDOWS: dict = {}
HOST_WINDOWS: dict = {}
GALLERY_WINDOWS: dict = {}
_MUTEX = None

CARD_SPECS = (
    ("weather", W.CARD_WEATHER, "天气"),
    ("balance", W.CARD_BALANCE, "DeepSeek 余额"),
    ("system", W.CARD_SYSTEM, "系统资源"),
    ("volume", None, "音量混音器"),
    ("music", None, "音乐播放器"),
    ("battery", None, "蓝牙电量"),
    ("calendar", None, "日历"),
)

CUSTOM_SPECS = {
    "volume": (280, 200),
    "music": (280, 200),
    "battery": (220, 170),
    "calendar": (280, 170),
}

GALLERY_ITEMS = (
    ("weather", "天气", "温度、天气、空气质量", True),
    ("balance", "DeepSeek 余额", "余额、今日消耗、可用状态", True),
    ("system", "系统资源", "CPU、内存、磁盘占用", True),
    ("volume", "音量混音器", "主音量 + 每个应用单独调音量", True),
    ("music", "音乐播放器", "标题、歌手、播放状态与控制", True),
    ("battery", "蓝牙电量", "BLE / Windows 可读设备", True),
    ("calendar", "日历", "ICS 订阅或本地 .ics", True),
)

# 有些 API 只在 widget 里声明了一部分，这里补上原型需要的。
_user32 = W.user32
_user32.ScreenToClient.argtypes = [wt.HWND, ctypes.POINTER(W.POINT)]
_user32.ScreenToClient.restype = wt.BOOL
_user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(W.POINT)]
_user32.ClientToScreen.restype = wt.BOOL


def _signed_x(lparam: int) -> int:
    return ctypes.c_short(lparam & 0xFFFF).value


def _signed_y(lparam: int) -> int:
    return ctypes.c_short((lparam >> 16) & 0xFFFF).value


def _work_area() -> tuple[int, int, int, int]:
    """主屏工作区。P0 先只处理主屏，多显示器留给下一阶段。"""
    rect = W.RECT()
    _user32.SystemParametersInfoW(W.SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    return rect.left, rect.top, rect.right, rect.bottom


def _guide_image(length: int, vertical: bool) -> Image.Image:
    """细虚线参考线，比整条亮线克制得多。"""
    length = max(1, int(length))
    size = (1, length) if vertical else (length, 1)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (84, 228, 190, 85)
    for pos in range(0, length, 14):
        end = min(length, pos + 7)
        if vertical:
            d.line((0, pos, 0, end), fill=color, width=1)
        else:
            d.line((pos, 0, end, 0), fill=color, width=1)
    return img


def present_layered(hwnd, img: Image.Image) -> None:
    """把一个 PIL 图像贴到分层窗口上。"""
    if img is None:
        return
    w, h = img.size
    bgra = img.convert("RGBA").tobytes("raw", "BGRA")

    bmi = W.BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(W.BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = W.DIB_RGB_COLORS

    screen_dc = _user32.GetDC(None)
    mem_dc = W.gdi32.CreateCompatibleDC(screen_dc)
    bits = ctypes.c_void_p()
    hbmp = W.gdi32.CreateDIBSection(
        mem_dc, ctypes.byref(bmi), W.DIB_RGB_COLORS,
        ctypes.byref(bits), None, 0
    )
    ctypes.memmove(bits, bgra, len(bgra))
    old = W.gdi32.SelectObject(mem_dc, hbmp)

    rect = W.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    dst = W.POINT(rect.left, rect.top)
    size = W.SIZE(w, h)
    src = W.POINT(0, 0)
    blend = W.BLENDFUNCTION(W.AC_SRC_OVER, 0, 255, W.AC_SRC_ALPHA)
    _user32.UpdateLayeredWindow(
        hwnd, screen_dc, ctypes.byref(dst), ctypes.byref(size),
        mem_dc, ctypes.byref(src), 0, ctypes.byref(blend), W.ULW_ALPHA
    )
    W.gdi32.SelectObject(mem_dc, old)
    W.gdi32.DeleteObject(hbmp)
    W.gdi32.DeleteDC(mem_dc)
    _user32.ReleaseDC(None, screen_dc)


def _card_shell(w: int, h: int, scale: float, title: str):
    margin = max(6, int(round(10 * scale)))
    img = Image.new("RGBA", (w + margin * 2, h + margin * 2), (0, 0, 0, 0))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(
        (margin, margin + 5, margin + w, margin + h + 5),
        radius=max(8, int(round((W.RADIUS + 6) * scale))),
        fill=(0, 0, 0, 135)
    )
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(5)))
    card = W.vertical_gradient((w, h), W.BG_TOP, W.BG_BOTTOM).convert("RGBA")
    card.putalpha(W.rounded_mask((w, h), W.RADIUS * scale))
    img.alpha_composite(card, (margin, margin))
    d = ImageDraw.Draw(img)
    d.line(
        (margin + int(14 * scale), margin + 1,
         margin + w - int(14 * scale), margin + 1),
        fill=(255, 255, 255, 24), width=1
    )
    d.text((margin + int(14 * scale), margin + int(12 * scale)),
           title, font=W.font(max(7, 12 * scale)), fill=W.FG)
    return img, margin, d


def _ellipsis(d, text: str, font, max_width: float) -> str:
    text = str(text or "")
    if d.textlength(text, font=font) <= max_width:
        return text
    while text and d.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text + "…"


def _small_button(img, d, rect, label, name, buttons, accent=False):
    hgt = max(8, int(rect[3] - rect[1]))
    font = W.font(max(8, int(hgt * 0.42)))
    d.rounded_rectangle(
        rect, radius=max(5, hgt // 2),
        fill=(38, 86, 74, 255) if accent else (48, 52, 62, 255)
    )
    tw = d.textlength(label, font=font)
    d.text((rect[0] + (rect[2] - rect[0] - tw) / 2,
            rect[1] + hgt / 2),
           label, font=font, fill=W.FG, anchor="lm")
    buttons[name] = rect


def render_volume(app, w: int, h: int, scale: float):
    img, m, d = _card_shell(w, h, scale, "音量")
    buttons = {}
    st = getattr(app.extra, "volume", {}) if hasattr(app, "extra") else {}
    dev = _ellipsis(d, st.get("device") or "默认输出设备",
                    W.font(max(7, 9 * scale)), w - 28 * scale)
    d.text((m + 14 * scale, m + 34 * scale), dev,
           font=W.font(max(7, 9 * scale)), fill=W.FG_DIM)
    master = st.get("master")
    muted = bool(st.get("muted"))
    pct = "--" if master is None else f"{int(round(master * 100))}%"
    d.text((m + 14 * scale, m + 60 * scale), pct,
           font=W.font(max(7, 28 * scale)), fill=W.BAD if muted else W.FG)
    d.text((m + 14 * scale, m + 94 * scale),
           "已静音" if muted else "主音量",
           font=W.font(max(7, 9 * scale)), fill=W.BAD if muted else W.FG_FAINT)
    btn_y = m + 66 * scale
    _small_button(img, d, (m + w - 86 * scale, btn_y,
                           m + w - 50 * scale, btn_y + 22 * scale),
                  "−", "vol_down", buttons)
    _small_button(img, d, (m + w - 46 * scale, btn_y,
                           m + w - 14 * scale, btn_y + 22 * scale),
                  "+", "vol_up", buttons)
    _small_button(img, d, (m + w - 86 * scale, btn_y + 28 * scale,
                           m + w - 14 * scale, btn_y + 50 * scale),
                  "取消静音" if muted else "静音",
                  "vol_mute", buttons, accent=muted)
    y = m + 120 * scale
    sessions = (st.get("sessions") or [])[:3]
    if not sessions:
        d.text((m + 14 * scale, y), "暂无活跃音频会话",
               font=W.font(max(7, 9 * scale)), fill=W.FG_FAINT)
    for row in sessions:
        name = _ellipsis(d, row.get("name") or "应用",
                         W.font(max(7, 9 * scale)), w - 112 * scale)
        d.text((m + 14 * scale, y), name,
               font=W.font(max(7, 9 * scale)), fill=W.FG_DIM)
        vol = int(round(float(row.get("volume") or 0) * 100))
        d.text((m + w - 100 * scale, y), f"{vol}%",
               font=W.font(max(7, 9 * scale)), fill=W.FG)
        _small_button(img, d, (m + w - 54 * scale, y - 6 * scale,
                               m + w - 32 * scale, y + 12 * scale),
                      "−", f"volapp:{row.get('pid')}:down", buttons)
        _small_button(img, d, (m + w - 28 * scale, y - 6 * scale,
                               m + w - 6 * scale, y + 12 * scale),
                      "+", f"volapp:{row.get('pid')}:up", buttons)
        y += 20 * scale
    return img, (m, m), buttons


def render_music(app, w: int, h: int, scale: float):
    img, m, d = _card_shell(w, h, scale, "音乐")
    buttons = {}
    st = getattr(app.extra, "media", {}) if hasattr(app, "extra") else {}
    title = st.get("title") or ""
    artist = st.get("artist") or ""
    status = st.get("status") or ""
    if not title:
        d.text((m + 14 * scale, m + 44 * scale), "未在播放",
               font=W.font(max(7, 16 * scale)), fill=W.FG_DIM)
        d.text((m + 14 * scale, m + 70 * scale),
               st.get("error") or "打开任意播放器后自动出现",
               font=W.font(max(7, 9 * scale)), fill=W.FG_FAINT)
    else:
        d.text((m + 14 * scale, m + 42 * scale),
               _ellipsis(d, title, W.font(max(7, 15 * scale)), w - 28 * scale),
               font=W.font(max(7, 15 * scale)), fill=W.FG)
        d.text((m + 14 * scale, m + 66 * scale),
               _ellipsis(d, artist, W.font(max(7, 10 * scale)), w - 28 * scale),
               font=W.font(max(7, 10 * scale)), fill=W.FG_DIM)
    d.text((m + 14 * scale, m + 92 * scale),
           {"Playing": "正在播放", "Paused": "已暂停"}.get(status, status or ""),
           font=W.font(max(7, 9 * scale)), fill=W.GOOD if status == "Playing" else W.FG_FAINT)
    by = m + h - 42 * scale
    _small_button(img, d, (m + 14 * scale, by, m + 66 * scale, by + 26 * scale),
                  "<<", "media_prev", buttons)
    _small_button(img, d, (m + 74 * scale, by, m + 126 * scale, by + 26 * scale),
                  "播放", "media_play", buttons, accent=True)
    _small_button(img, d, (m + 134 * scale, by, m + 186 * scale, by + 26 * scale),
                  ">>", "media_next", buttons)
    return img, (m, m), buttons


def render_battery(app, w: int, h: int, scale: float):
    img, m, d = _card_shell(w, h, scale, "蓝牙电量")
    st = getattr(app.extra, "battery", []) if hasattr(app, "extra") else []
    if not st:
        d.text((m + 14 * scale, m + 42 * scale), "暂无可读电量",
               font=W.font(max(7, 13 * scale)), fill=W.FG_DIM)
        d.text((m + 14 * scale, m + 66 * scale),
               _ellipsis(d, "经典蓝牙没有通用电量接口",
                         W.font(max(7, 8 * scale)), w - 28 * scale),
               font=W.font(max(7, 8 * scale)), fill=W.FG_FAINT)
        return img, (m, m), {}
    y = m + 38 * scale
    for item in st[:2]:
        name = _ellipsis(d, item.get("name") or "蓝牙设备",
                         W.font(max(7, 9 * scale)), w - 80 * scale)
        d.text((m + 14 * scale, y), name, font=W.font(max(7, 9 * scale)), fill=W.FG_DIM)
        pct = item.get("percent")
        d.text((m + w - 58 * scale, y),
               "--" if pct is None else f"{pct}%",
               font=W.font(max(7, 13 * scale)),
               fill=W.GOOD if (pct or 0) > 20 else W.WARN)
        bar = (m + 14 * scale, y + 18 * scale, m + w - 14 * scale, y + 24 * scale)
        d.rounded_rectangle(bar, radius=3, fill=(38, 42, 50, 255))
        if pct is not None:
            d.rounded_rectangle(
                (bar[0], bar[1],
                 bar[0] + (bar[2] - bar[0]) * max(0, min(100, pct)) / 100,
                 bar[3]), radius=3, fill=W.GOOD if pct > 20 else W.WARN
            )
        y += 44 * scale
    return img, (m, m), {}


def render_calendar(app, w: int, h: int, scale: float):
    img, m, d = _card_shell(w, h, scale, "日历")
    st = getattr(app.extra, "calendar", {}) if hasattr(app, "extra") else {}
    d.text((m + 14 * scale, m + 38 * scale),
           st.get("today") or time.strftime("%m月%d日"),
           font=W.font(max(7, 15 * scale)), fill=W.FG)
    events = st.get("events") or []
    if not events:
        d.text((m + 14 * scale, m + 66 * scale),
               _ellipsis(d, st.get("error") or "最近没有事件",
                         W.font(max(7, 9 * scale)), w - 28 * scale),
               font=W.font(max(7, 9 * scale)), fill=W.FG_FAINT)
        return img, (m, m), {}
    y = m + 66 * scale
    when_font = W.font(max(7, 8 * scale))
    title_font = W.font(max(7, 9 * scale))
    for ev in events[:3]:
        when = ev.get("when") or ""
        d.text((m + 14 * scale, y), when,
               font=when_font, fill=W.FG_FAINT)
        title_x = m + 14 * scale + d.textlength(when, font=when_font) + 6 * scale
        d.text((title_x, y),
               _ellipsis(d, ev.get("title") or "（无标题）", title_font,
                         w - (title_x - m) - 8 * scale),
               font=title_font, fill=W.FG_DIM)
        y += 26 * scale
    return img, (m, m), {}


CUSTOM_RENDERERS = {
    "volume": render_volume,
    "music": render_music,
    "battery": render_battery,
    "calendar": render_calendar,
}


class CardWindow:
    def __init__(self, app: "CardApp", key: str, rect, label: str,
                 card_x: int, card_y: int, zoom: float = 1.0):
        self.app = app
        self.key = key
        self.rect = rect
        self.label = label
        self.kind = "crop" if rect is not None else "custom"
        self.zoom = max(0.6, min(2.2, float(zoom or 1.0)))
        self.scale = app.scale * self.zoom
        self.card_x = int(card_x)
        self.card_y = int(card_y)
        if self.kind == "custom":
            cw, ch = CUSTOM_SPECS[key]
            self.card_w = max(1, int(round(cw * self.scale)))
            self.card_h = max(1, int(round(ch * self.scale)))
        else:
            self.card_w = max(1, int(round(rect[2] * self.scale)))
            self.card_h = max(1, int(round(rect[3] * self.scale)))
        self.image = None
        self.offset = (0, 0)
        self.buttons: dict = {}
        self.pressed = None
        self.dragging = False
        self.drag_started = False
        self.resizing = False
        self.resize_origin = (0, 0)
        self.resize_base = self.zoom
        self.resize_last = 0.0
        self.resize_pending = 0.0
        self.resize_snapshot = None
        self.resize_base_card = (self.card_w, self.card_h)
        self.resize_base_offset = (0, 0)
        self.visible = True
        self.drag_origin = (0, 0)
        self.win_origin = (0, 0)
        self.hover = None

        if self.kind == "custom":
            image, offset, buttons = app.render_custom(
                key, self.card_w, self.card_h, self.scale
            )
        else:
            image, offset, buttons = app.crop_card(rect, self.scale)
        self.image = image
        self.offset = offset
        self.buttons = buttons
        self.image = self._with_grip(self.image)

        hinst = W.kernel32.GetModuleHandleW(None)
        ex = (W.WS_EX_LAYERED | W.WS_EX_TOOLWINDOW | W.WS_EX_NOACTIVATE |
              W.WS_EX_TOPMOST)
        w, h = self.image.size
        self.hwnd = _user32.CreateWindowExW(
            ex, CARD_CLASS, f"LumenCard:{key}", W.WS_POPUP,
            self.card_x - self.offset[0], self.card_y - self.offset[1],
            w, h, None, None, hinst, None
        )
        if not self.hwnd:
            raise OSError(f"CreateWindowExW(card) 失败: {ctypes.get_last_error()}")
        CARD_WINDOWS[self.hwnd] = self
        _user32.ShowWindow(self.hwnd, W.SW_SHOWNOACTIVATE)
        self.set_card_pos(self.card_x, self.card_y)
        self.present()

    # -- 绘制 ---------------------------------------------------------------
    def _with_grip(self, image):
        image = image.copy()
        d = ImageDraw.Draw(image)
        x0 = self.offset[0] + self.card_w
        y0 = self.offset[1] + self.card_h
        for i in range(3):
            d.line(
                (x0 - 13 + i * 4, y0 - 2, x0 - 2, y0 - 13 + i * 4),
                fill=(255, 255, 255, 72), width=1
            )
        return image

    def update_image(self, image, offset, buttons) -> None:
        old_size = self.image.size if self.image else (0, 0)
        self.image = self._with_grip(image)
        self.offset = offset
        self.buttons = buttons
        if self.image.size != old_size:
            w, h = self.image.size
            self.app.ensure_zorder(self)
            _user32.SetWindowPos(
                self.hwnd, self.app.current_zorder(), 0, 0, w, h,
                W.SWP_NOMOVE | W.SWP_NOACTIVATE
            )
            self.set_card_pos(self.card_x, self.card_y)
        self.present()

    def present(self) -> None:
        present_layered(self.hwnd, self.image)

    # -- 位置 ---------------------------------------------------------------
    def set_card_pos(self, x: int, y: int) -> None:
        left, top, right, bottom = _work_area()
        x = max(left, min(int(x), max(left, right - self.card_w)))
        y = max(top, min(int(y), max(top, bottom - self.card_h)))
        self.card_x, self.card_y = x, y
        self.app.ensure_zorder(self)
        _user32.SetWindowPos(
            self.hwnd, self.app.current_zorder(),
            x - self.offset[0], y - self.offset[1], 0, 0,
            W.SWP_NOSIZE | W.SWP_NOACTIVATE
        )

    def set_visible(self, visible: bool) -> None:
        self.visible = bool(visible)
        if self.visible:
            _user32.ShowWindow(self.hwnd, W.SW_SHOWNOACTIVATE)
            self.app.ensure_zorder(self)
            _user32.SetWindowPos(
                self.hwnd, self.app.current_zorder(), 0, 0, 0, 0,
                W.SWP_NOMOVE | W.SWP_NOSIZE | W.SWP_NOACTIVATE |
                W.SWP_SHOWWINDOW
            )
        else:
            _user32.ShowWindow(self.hwnd, W.SW_HIDE)

    # -- 命中 ---------------------------------------------------------------
    def hit(self, px: int, py: int):
        gx = self.offset[0] + self.card_w
        gy = self.offset[1] + self.card_h
        if px >= gx - 14 and py >= gy - 14:
            return "__resize__"
        for name, (x0, y0, x1, y1) in self.buttons.items():
            if x0 <= px <= x1 and y0 <= py <= y1:
                return name
        return None

    def _alpha_at(self, px: int, py: int) -> int:
        try:
            return self.image.getpixel((int(px), int(py)))[3]
        except Exception:
            return 255

    # -- 消息 ---------------------------------------------------------------
    def handle(self, msg, wparam, lparam):
        if msg == 0x0084:                      # WM_NCHITTEST
            x, y = _signed_x(lparam), _signed_y(lparam)
            pt = W.POINT(x, y)
            _user32.ScreenToClient(self.hwnd, ctypes.byref(pt))
            if 0 <= pt.x < self.image.size[0] and 0 <= pt.y < self.image.size[1]:
                if self._alpha_at(pt.x, pt.y) < 8:
                    return HTTRANSPARENT
            return HTCLIENT
        if msg == W.WM_SETCURSOR:
            pos = W.POINT()
            _user32.GetCursorPos(ctypes.byref(pos))
            rect = W.RECT()
            _user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
            name = self.hit(pos.x - rect.left, pos.y - rect.top)
            if name == "__resize__":
                cursor = W.IDC_SIZENWSE
            elif name:
                cursor = W.IDC_HAND
            elif self.app.locked:
                cursor = 32512          # IDC_ARROW
            else:
                cursor = W.IDC_SIZEALL
            _user32.SetCursor(_user32.LoadCursorW(None, cursor))
            return 1
        if msg == W.WM_LBUTTONDOWN:
            x, y = _signed_x(lparam), _signed_y(lparam)
            self.pressed = self.hit(x, y)
            if self.pressed == "__resize__" and not self.app.locked:
                cur = W.POINT()
                _user32.GetCursorPos(ctypes.byref(cur))
                self.resize_origin = (cur.x, cur.y)
                self.resize_base = self.zoom
                self.resize_snapshot = self.image.copy()
                self.resize_base_card = (self.card_w, self.card_h)
                self.resize_base_offset = self.offset
                self.resizing = True
                _user32.SetCapture(self.hwnd)
                return 0
            if self.pressed is None and not self.app.locked:
                cur = W.POINT()
                _user32.GetCursorPos(ctypes.byref(cur))
                self.drag_origin = (cur.x, cur.y)
                rect = W.RECT()
                _user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
                self.win_origin = (rect.left, rect.top)
                self.dragging = True
                self.drag_started = False
                _user32.SetCapture(self.hwnd)
                self.app.begin_drag(self)
                self.app.ensure_zorder(self)
                _user32.SetWindowPos(
                    self.hwnd, self.app.current_zorder(), 0, 0, 0, 0,
                    W.SWP_NOMOVE | W.SWP_NOSIZE | W.SWP_NOACTIVATE
                )
            return 0
        if msg == W.WM_MOUSEMOVE:
            x, y = _signed_x(lparam), _signed_y(lparam)
            if self.resizing:
                cur = W.POINT()
                _user32.GetCursorPos(ctypes.byref(cur))
                dx = cur.x - self.resize_origin[0]
                dy = cur.y - self.resize_origin[1]
                target = self.resize_base * (1.0 + (dx + dy) / 700.0)
                target = max(0.6, min(2.2, target))
                now = time.time()
                if now - self.resize_last >= 0.016:
                    self.resize_last = now
                    self.app.preview_card_zoom(self, target)
                else:
                    self.resize_pending = target
                return 0
            if self.dragging:
                cur = W.POINT()
                _user32.GetCursorPos(ctypes.byref(cur))
                dx = cur.x - self.drag_origin[0]
                dy = cur.y - self.drag_origin[1]
                if not self.drag_started and abs(dx) + abs(dy) < 4:
                    return 0
                self.drag_started = True
                _user32.SetWindowPos(
                    self.hwnd, 0,
                    self.win_origin[0] + dx, self.win_origin[1] + dy,
                    0, 0, W.SWP_NOSIZE | W.SWP_NOZORDER | W.SWP_NOACTIVATE
                )
                self.app.update_drag_feedback(self)
                return 0
            name = self.hit(x, y)
            if name != self.hover:
                self.hover = name
                self.app.set_hover(name)
            return 0
        if msg == W.WM_LBUTTONUP:
            if self.resizing:
                self.resizing = False
                final_zoom = self.resize_pending or self.zoom
                self.resize_pending = 0.0
                self.resize_snapshot = None
                self.app.set_card_zoom(self, final_zoom)
                _user32.ReleaseCapture()
                self.app.save_layout()
                return 0
            if self.dragging:
                started = self.drag_started
                self.dragging = False
                self.drag_started = False
                _user32.ReleaseCapture()
                if started:
                    self.app.finish_drag(self)
                else:
                    self.app.cancel_drag(self)
                return 0
            if self.pressed:
                x, y = _signed_x(lparam), _signed_y(lparam)
                if self.hit(x, y) == self.pressed:
                    self.app.action(self.pressed)
                self.pressed = None
            return 0
        if msg == W.WM_CAPTURECHANGED:
            if self.dragging:
                self.app.cancel_drag(self)
            self.dragging = False
            self.drag_started = False
            self.resizing = False
            self.resize_pending = 0.0
            self.resize_snapshot = None
            self.pressed = None
            return 0
        if msg == W.WM_RBUTTONUP:
            self.app.show_card_menu(self)
            return 0
        if msg == W.WM_CLOSE:
            self.app.quit()
            return 0
        if msg == W.WM_DESTROY:
            CARD_WINDOWS.pop(self.hwnd, None)
            return 0
        return _user32.DefWindowProcW(self.hwnd, msg, wparam, lparam)


def card_wndproc(hwnd, msg, wparam, lparam):
    card = CARD_WINDOWS.get(hwnd)
    if card is None:
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    try:
        return card.handle(msg, wparam, lparam)
    except Exception:
        W.log("[cards] card wndproc 异常:\n" + traceback.format_exc())
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)


class LayeredOverlay:
    """没有交互的透明覆盖层：落点阴影、对齐参考线。"""

    def __init__(self, image: Image.Image):
        self.image = image
        hinst = W.kernel32.GetModuleHandleW(None)
        ex = (W.WS_EX_LAYERED | W.WS_EX_TOOLWINDOW | W.WS_EX_NOACTIVATE |
              W.WS_EX_TOPMOST | W.WS_EX_TRANSPARENT)
        w, h = image.size
        self.hwnd = _user32.CreateWindowExW(
            ex, OVERLAY_CLASS, "LumenCardOverlay", W.WS_POPUP,
            0, 0, w, h, None, None, hinst, None
        )
        if not self.hwnd:
            raise OSError(f"CreateWindowExW(overlay) 失败: {ctypes.get_last_error()}")
        self.visible = False
        self.present()
        _user32.ShowWindow(self.hwnd, W.SW_HIDE)

    def present(self) -> None:
        present_layered(self.hwnd, self.image)

    def set_image(self, image: Image.Image) -> None:
        resized = image.size != self.image.size
        self.image = image
        if resized:
            w, h = image.size
            _user32.SetWindowPos(
                self.hwnd, 0, 0, 0, w, h,
                W.SWP_NOMOVE | W.SWP_NOZORDER | W.SWP_NOACTIVATE
            )
        self.present()

    def move(self, x: int, y: int, insert_after=None) -> None:
        w, h = self.image.size
        target = insert_after if insert_after else W.HWND_TOPMOST
        _user32.SetWindowPos(
            self.hwnd, target, int(x), int(y), w, h,
            W.SWP_NOACTIVATE
        )

    def show(self) -> None:
        if not self.visible:
            _user32.ShowWindow(self.hwnd, W.SW_SHOWNOACTIVATE)
            self.visible = True

    def hide(self) -> None:
        if self.visible:
            _user32.ShowWindow(self.hwnd, W.SW_HIDE)
            self.visible = False


class GalleryWindow:
    """添加/隐藏组件的面板。"""

    WIDTH = 380
    HEIGHT = 548

    def __init__(self, app: "CardApp"):
        self.app = app
        self.visible = False
        self.hover = None
        self.pressed = None
        self.dragging = False
        self.drag_origin = (0, 0)
        self.win_origin = (0, 0)
        self.hit_regions: dict = {}
        self.rows: list = []
        hinst = W.kernel32.GetModuleHandleW(None)
        ex = (W.WS_EX_LAYERED | W.WS_EX_TOOLWINDOW | W.WS_EX_NOACTIVATE |
              W.WS_EX_TOPMOST)
        self.hwnd = _user32.CreateWindowExW(
            ex, GALLERY_CLASS, "LumenCardGallery", W.WS_POPUP,
            0, 0, self.WIDTH, self.HEIGHT, None, None, hinst, None
        )
        if not self.hwnd:
            raise OSError(f"CreateWindowExW(gallery) 失败: {ctypes.get_last_error()}")
        GALLERY_WINDOWS[self.hwnd] = self
        self.image = None
        self.render()
        self.present()
        _user32.ShowWindow(self.hwnd, W.SW_HIDE)

    def render(self) -> None:
        img = Image.new("RGBA", (self.WIDTH, self.HEIGHT), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle(
            (0, 0, self.WIDTH - 1, self.HEIGHT - 1), radius=20,
            fill=(25, 27, 34, 248), outline=(76, 81, 96, 255), width=1
        )
        d.text((22, 24), "添加组件", font=W.font(18), fill=W.FG)
        d.text((22, 52), "点击卡片显示/隐藏；位置可拖动调整",
               font=W.font(10), fill=W.FG_DIM)
        close_rect = (self.WIDTH - 48, 18, self.WIDTH - 22, 44)
        d.rounded_rectangle(
            close_rect, radius=8,
            fill=(55, 59, 72, 255) if self.hover == "close" else (38, 41, 50, 255)
        )
        d.text((close_rect[0] + 7, close_rect[1] + 3), "×",
               font=W.font(18), fill=W.FG_DIM)

        self.hit_regions = {"header": (0, 0, self.WIDTH, 72), "close_top": close_rect}
        self.rows = []
        y = 78
        for key, title, desc, available in GALLERY_ITEMS:
            row_h = 58 if available else 52
            row = (16, y, self.WIDTH - 16, y + row_h - 6)
            hovered = self.hover == f"toggle:{key}"
            if available:
                fill = (46, 50, 60, 255) if hovered else (36, 39, 48, 255)
            else:
                fill = (30, 32, 40, 255)
            d.rounded_rectangle(row, radius=12, fill=fill)
            dot = (row[0] + 16, row[1] + 15, row[0] + 42, row[1] + 41)
            dot_color = (86, 196, 255, 255) if available else (90, 94, 106, 255)
            d.rounded_rectangle(dot, radius=8, fill=dot_color)
            d.text((dot[0] + 9, dot[1] + 6), title[:1],
                   font=W.font(12), fill=(20, 24, 30, 255))
            d.text((row[0] + 52, row[1] + 8), title,
                   font=W.font(12), fill=W.FG if available else W.FG_FAINT)
            d.text((row[0] + 52, row[1] + 28), desc,
                   font=W.font(9), fill=W.FG_DIM if available else W.FG_FAINT)
            if available:
                card = self.app.card_by_key(key)
                shown = bool(card and card.visible)
                status = "已显示" if shown else "已隐藏"
                color = W.GOOD if shown else W.FG_FAINT
            else:
                status = "下一阶段"
                color = W.WARN
            tw = d.textlength(status, font=W.font(9))
            d.text((row[2] - tw - 14, row[1] + 17), status,
                   font=W.font(9), fill=color)
            if available:
                self.hit_regions[f"toggle:{key}"] = row
            self.rows.append((key, title, desc, available, row))
            y += row_h

        footer_y = self.HEIGHT - 52
        reset_rect = (16, footer_y, 128, footer_y + 34)
        close2_rect = (self.WIDTH - 128, footer_y, self.WIDTH - 16, footer_y + 34)
        for name, rect, label in (("reset", reset_rect, "重置布局"),
                                  ("close", close2_rect, "关闭")):
            hovered = self.hover == name
            d.rounded_rectangle(
                rect, radius=9,
                fill=(55, 59, 72, 255) if hovered else (38, 41, 50, 255)
            )
            tw = d.textlength(label, font=W.font(11))
            d.text((rect[0] + (rect[2] - rect[0] - tw) / 2, rect[1] + 9),
                   label, font=W.font(11), fill=W.FG)
            self.hit_regions[name] = rect
        self.image = img

    def present(self) -> None:
        present_layered(self.hwnd, self.image)

    def hit(self, px: int, py: int):
        for name, (x0, y0, x1, y1) in reversed(list(self.hit_regions.items())):
            if x0 <= px <= x1 and y0 <= py <= y1:
                return name
        return None

    def show(self) -> None:
        if not self.visible:
            left, top, right, bottom = _work_area()
            x = left + (right - left - self.WIDTH) // 2
            y = top + (bottom - top - self.HEIGHT) // 2
            _user32.SetWindowPos(
                self.hwnd, W.HWND_TOPMOST, x, y, self.WIDTH, self.HEIGHT,
                W.SWP_NOACTIVATE | W.SWP_SHOWWINDOW
            )
            self.visible = True
        self.render()
        self.present()
        _user32.ShowWindow(self.hwnd, W.SW_SHOWNOACTIVATE)

    def hide(self) -> None:
        self.visible = False
        _user32.ShowWindow(self.hwnd, W.SW_HIDE)

    def handle(self, msg, wparam, lparam):
        if msg == W.WM_LBUTTONDOWN:
            x, y = _signed_x(lparam), _signed_y(lparam)
            self.pressed = self.hit(x, y)
            if self.pressed == "header":
                cur = W.POINT()
                _user32.GetCursorPos(ctypes.byref(cur))
                self.drag_origin = (cur.x, cur.y)
                rect = W.RECT()
                _user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
                self.win_origin = (rect.left, rect.top)
                self.dragging = True
                _user32.SetCapture(self.hwnd)
            return 0
        if msg == W.WM_MOUSEMOVE:
            x, y = _signed_x(lparam), _signed_y(lparam)
            if self.dragging:
                cur = W.POINT()
                _user32.GetCursorPos(ctypes.byref(cur))
                _user32.SetWindowPos(
                    self.hwnd, 0,
                    self.win_origin[0] + cur.x - self.drag_origin[0],
                    self.win_origin[1] + cur.y - self.drag_origin[1],
                    0, 0, W.SWP_NOSIZE | W.SWP_NOZORDER | W.SWP_NOACTIVATE
                )
                return 0
            name = self.hit(x, y)
            if name != self.hover:
                self.hover = name
                self.render()
                self.present()
            return 0
        if msg == W.WM_LBUTTONUP:
            if self.dragging:
                self.dragging = False
                _user32.ReleaseCapture()
                return 0
            if self.pressed:
                x, y = _signed_x(lparam), _signed_y(lparam)
                if self.hit(x, y) == self.pressed:
                    self.app.gallery_action(self.pressed)
                self.pressed = None
            return 0
        if msg == W.WM_CLOSE:
            self.hide()
            return 0
        return _user32.DefWindowProcW(self.hwnd, msg, wparam, lparam)


def gallery_wndproc(hwnd, msg, wparam, lparam):
    gallery = GALLERY_WINDOWS.get(hwnd)
    if gallery is None:
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    try:
        return gallery.handle(msg, wparam, lparam)
    except Exception:
        W.log("[cards] gallery wndproc 异常:\n" + traceback.format_exc())
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def overlay_wndproc(hwnd, msg, wparam, lparam):
    return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)


GALLERY_WNDPROC = W.WNDPROC(gallery_wndproc)
OVERLAY_WNDPROC = W.WNDPROC(overlay_wndproc)


class CardHost:
    """隐藏的控制窗口：托盘、热键、定时器。"""

    def __init__(self, app: "CardApp"):
        self.app = app
        self.tray = None
        self.tray_icon = None
        self.tray_added = False
        hinst = W.kernel32.GetModuleHandleW(None)
        self.hwnd = _user32.CreateWindowExW(
            0, HOST_CLASS, "LumenCardsHost", W.WS_POPUP,
            0, 0, 0, 0, None, None, hinst, None
        )
        if not self.hwnd:
            raise OSError(f"CreateWindowExW(host) 失败: {ctypes.get_last_error()}")
        HOST_WINDOWS[self.hwnd] = self

    def add_tray(self) -> None:
        if self.tray_added:
            return
        self.tray_icon = W.make_hicon(W.tray_icon_image(32))
        nid = W.NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(W.NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = W.NIF_ICON | W.NIF_MESSAGE | W.NIF_TIP
        nid.uCallbackMessage = W.WM_APP_TRAY
        nid.hIcon = self.tray_icon
        nid.szTip = "桌面小组件 · 卡片原型"
        self.tray = nid
        self.tray_added = bool(W.shell32.Shell_NotifyIconW(W.NIM_ADD, ctypes.byref(nid)))

    def update_tip(self) -> None:
        if not self.tray_added:
            return
        self.tray.szTip = f"桌面小组件 · {len(self.app.cards)} 张卡 · 拖动摆放"
        W.shell32.Shell_NotifyIconW(W.NIM_MODIFY, ctypes.byref(self.tray))

    def remove_tray(self) -> None:
        if self.tray_added:
            W.shell32.Shell_NotifyIconW(W.NIM_DELETE, ctypes.byref(self.tray))
            self.tray_added = False
        if self.tray_icon:
            _user32.DestroyIcon(self.tray_icon)
            self.tray_icon = None

    def show_menu(self, card=None) -> None:
        menu = _user32.CreatePopupMenu()
        if not menu:
            return
        _user32.AppendMenuW(menu, W.MF_STRING, 2001,
                            "隐藏卡片" if self.app.visible else "显示卡片")
        _user32.AppendMenuW(menu, W.MF_STRING, 2002, "重置卡片位置")
        _user32.AppendMenuW(
            menu,
            W.MF_STRING | (W.MF_CHECKED if self.app.locked else 0),
            2003, "锁定布局"
        )
        _user32.AppendMenuW(menu, W.MF_STRING, 2005, "添加组件…")
        if card is not None:
            _user32.AppendMenuW(menu, W.MF_SEPARATOR, 0, None)
            _user32.AppendMenuW(menu, W.MF_STRING, 2006, "隐藏这张卡")
            _user32.AppendMenuW(menu, W.MF_STRING, 2007, "重置这张卡大小")
        _user32.AppendMenuW(menu, W.MF_SEPARATOR, 0, None)
        _user32.AppendMenuW(menu, W.MF_STRING, 2004, "退出")
        pos = W.POINT()
        _user32.GetCursorPos(ctypes.byref(pos))
        self.app.menu_open = True
        _user32.SetForegroundWindow(self.hwnd)
        cmd = _user32.TrackPopupMenu(
            menu, W.TPM_RIGHTBUTTON | W.TPM_RETURNCMD,
            pos.x, pos.y, 0, self.hwnd, None
        )
        _user32.PostMessageW(self.hwnd, 0, 0, 0)
        _user32.DestroyMenu(menu)
        self.app.menu_open = False
        if cmd == 2001:
            self.app.toggle_visible()
        elif cmd == 2002:
            self.app.reset_layout()
        elif cmd == 2003:
            self.app.toggle_lock()
        elif cmd == 2005:
            self.app.show_gallery()
        elif cmd == 2006 and card is not None:
            self.app.hide_card(card)
        elif cmd == 2007 and card is not None:
            self.app.reset_card_zoom(card)
        elif cmd == 2004:
            self.app.quit()
            return
        self.app.desktop_active_state = None
        self.app.sync_desktop_layer()

    def post_rerender(self) -> None:
        _user32.PostMessageW(self.hwnd, W.WM_APP_RERENDER, 0, 0)

    def handle(self, msg, wparam, lparam):
        if msg == W.WM_TIMER:
            self.app.tick()
            return 0
        if msg == W.WM_APP_RERENDER:
            self.app.refresh()
            return 0
        if msg == W.WM_APP_TRAY:
            if lparam in (W.WM_RBUTTONUP, W.WM_CONTEXTMENU):
                self.show_menu()
            elif lparam in (W.WM_LBUTTONUP, W.WM_LBUTTONDBLCLK):
                self.app.toggle_visible()
            return 0
        if msg == W.WM_HOTKEY:
            if wparam == 2:
                self.app.quit()
            else:
                self.app.reset_layout()
            return 0
        if msg == W.WM_APP_SHOW:
            self.app.show()
            return 0
        if msg == W.WM_DISPLAYCHANGE:
            self.app.clamp_cards()
            return 0
        if msg == W.WM_CLOSE:
            self.app.quit()
            return 0
        if msg == W.WM_DESTROY:
            HOST_WINDOWS.pop(self.hwnd, None)
            return 0
        return _user32.DefWindowProcW(self.hwnd, msg, wparam, lparam)


def host_wndproc(hwnd, msg, wparam, lparam):
    host = HOST_WINDOWS.get(hwnd)
    if host is None:
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    try:
        return host.handle(msg, wparam, lparam)
    except Exception:
        W.log("[cards] host wndproc 异常:\n" + traceback.format_exc())
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)


CARD_WNDPROC = W.WNDPROC(card_wndproc)
HOST_WNDPROC = W.WNDPROC(host_wndproc)


def _load_ics(source: str) -> str:
    if source.lower().startswith(("http://", "https://")):
        req = urllib.request.Request(source, headers={"User-Agent": "LumenWidgetCalendar/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read(2_000_000)
        return data.decode("utf-8", "replace")
    path = os.path.expandvars(os.path.expanduser(source))
    if not os.path.isabs(path):
        path = os.path.join(W.APP_DIR, path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read(2_000_000)


def _unfold_ics(text: str) -> list[str]:
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _parse_ics_dt(value: str):
    value = value.strip()
    if not value:
        return None
    if value.endswith("Z"):
        try:
            return dt.datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(
                tzinfo=dt.timezone.utc
            ).astimezone().replace(tzinfo=None)
        except ValueError:
            return None
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d"):
        try:
            parsed = dt.datetime.strptime(value, fmt)
            return parsed
        except ValueError:
            continue
    return None


def _ics_text(value: str) -> str:
    return (value.replace("\\n", " ").replace("\\N", " ")
            .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip())


def _parse_ics_events(text: str, days: int = 7) -> list[dict]:
    now = dt.datetime.now()
    horizon = now + dt.timedelta(days=days)
    events = []
    block = None
    for line in _unfold_ics(text):
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            block = {}
            continue
        if upper == "END:VEVENT":
            if not block:
                continue
            start = _parse_ics_dt(block.get("DTSTART", ""))
            if start is not None:
                title = _ics_text(block.get("SUMMARY", "")) or "（无标题）"
                all_day = "T" not in block.get("DTSTART", "")
                occurrences = [start]
                rule = block.get("RRULE", "")
                if rule:
                    parts = {}
                    for item in rule.split(";"):
                        if "=" in item:
                            k, v = item.split("=", 1)
                            parts[k.upper()] = v
                    freq = parts.get("FREQ", "").upper()
                    interval = max(1, int(parts.get("INTERVAL", "1") or 1))
                    count = min(20, int(parts.get("COUNT", "20") or 20))
                    step = None
                    if freq == "DAILY":
                        step = dt.timedelta(days=interval)
                    elif freq == "WEEKLY":
                        step = dt.timedelta(days=7 * interval)
                    if step:
                        cur, added = start, 0
                        while cur <= horizon and added < count:
                            occurrences.append(cur)
                            cur += step
                            added += 1
                for occ in occurrences:
                    if now - dt.timedelta(hours=1) <= occ <= horizon:
                        when = "全天" if all_day else occ.strftime("%m-%d %H:%M")
                        if occ.date() == now.date() and not all_day:
                            when = "今天 " + occ.strftime("%H:%M")
                        events.append({"when": when, "title": title, "ts": occ.timestamp()})
            block = None
            continue
        if block is not None and ":" in line:
            key, value = line.split(":", 1)
            name = key.split(";", 1)[0].upper()
            if name in ("DTSTART", "DTEND", "SUMMARY", "RRULE"):
                block[name] = value
    events.sort(key=lambda item: item["ts"])
    seen = set()
    result = []
    for event in events:
        key = (event["when"], event["title"])
        if key in seen:
            continue
        seen.add(key)
        result.append({"when": event["when"], "title": event["title"]})
        if len(result) >= 20:
            break
    return result


class ExtraHub:
    """音量 / 音乐 / 电量 / 日历的后台数据。"""

    def __init__(self, app):
        self.app = app
        self.volume = {"device": "", "master": None, "muted": False, "sessions": []}
        self.media = {}
        self.battery = []
        self.calendar = {
            "today": time.strftime("%m月%d日"),
            "events": [],
            "error": "未配置 calendar.ics",
        }
        self._stop = threading.Event()
        self._notify = None
        self.volume_proc = None
        self._volume_lock = threading.Lock()
        self.media_proc = None
        self._media_lock = threading.Lock()
        self.media_file = os.path.join(W.APP_DIR, "assets", "media-state.json")

    def start(self, on_change):
        self._notify = on_change
        threading.Thread(target=self._calendar_loop, args=(on_change,), daemon=True).start()
        threading.Thread(target=self._volume_loop, args=(on_change,), daemon=True).start()
        threading.Thread(target=self._media_loop, args=(on_change,), daemon=True).start()
        threading.Thread(target=self._battery_loop, args=(on_change,), daemon=True).start()

    def _calendar_loop(self, on_change):
        while not self._stop.is_set():
            try:
                self._refresh_calendar()
                on_change()
            except Exception as exc:
                W.log(f"[calendar] {exc!r}")
            self._stop.wait(900)

    def _volume_loop(self, on_change):
        while not self._stop.is_set():
            try:
                self._ensure_volume_bridge()
                proc = self.volume_proc
                if proc and proc.poll() is None:
                    proc.stdin.write(b"list\n")
                    proc.stdin.flush()
            except Exception as exc:
                W.log(f"[volume] {exc!r}")
                self._stop_volume_bridge()
            self._stop.wait(2)

    def _ensure_volume_bridge(self):
        if self.volume_proc and self.volume_proc.poll() is None:
            return
        exe = os.path.join(W.APP_DIR, "assets", "AudioBridge.exe")
        if not os.path.exists(exe):
            with self._volume_lock:
                self.volume = {
                    "device": "", "master": None, "muted": False,
                    "sessions": [], "error": "缺少 AudioBridge.exe",
                }
            return
        proc = subprocess.Popen(
            [exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, creationflags=0x08000000
        )
        self.volume_proc = proc
        threading.Thread(
            target=self._volume_reader, args=(proc,), daemon=True
        ).start()

    def _volume_reader(self, proc):
        for line in proc.stdout:
            try:
                data = json.loads(line.decode("utf-8", "replace"))
            except Exception:
                continue
            if not data.get("ok"):
                data = {"device": "", "master": None, "muted": False,
                        "sessions": [], "error": data.get("error") or "音量桥错误"}
            data["muted"] = bool(data.get("masterMuted"))
            with self._volume_lock:
                self.volume = data
            if self._notify and not self._stop.is_set():
                self._notify()

    def _volume_command(self, command: str):
        proc = self.volume_proc
        if not proc or proc.poll() is not None:
            return False
        try:
            proc.stdin.write((command + "\n").encode("utf-8"))
            proc.stdin.flush()
            return True
        except Exception:
            self._stop_volume_bridge()
            return False

    def _stop_volume_bridge(self):
        proc = self.volume_proc
        self.volume_proc = None
        if proc and proc.poll() is None:
            try:
                proc.stdin.write(b"quit\n")
                proc.stdin.flush()
            except Exception:
                pass
            try:
                proc.wait(timeout=1)
            except Exception:
                proc.kill()

    def volume_step(self, delta: float, target: str = "master", pid=None):
        with self._volume_lock:
            state = dict(self.volume)
        if target == "master":
            base = state.get("master")
            if base is None:
                return
            value = max(0.0, min(1.0, float(base) + delta))
            self._volume_command(f"master {value:.3f}")
        elif pid is not None:
            row = next((r for r in state.get("sessions", []) if r.get("pid") == pid), None)
            if not row:
                return
            value = max(0.0, min(1.0, float(row.get("volume") or 0) + delta))
            self._volume_command(f"set {pid} {value:.3f}")

    def volume_mute(self):
        with self._volume_lock:
            muted = bool(self.volume.get("muted"))
        self._volume_command(f"mastermute {0 if muted else 1}")

    def _refresh_volume(self):
        pass

    def _media_loop(self, on_change):
        while not self._stop.is_set():
            try:
                before = self.media
                self._refresh_media()
                if self.media != before and on_change and not self._stop.is_set():
                    on_change()
            except Exception as exc:
                W.log(f"[media] {exc!r}")
            self._stop.wait(1)

    def _read_media_file(self, on_change):
        path = self.media_file
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        with self._media_lock:
            self.media = data.get("media") or {}
            battery = data.get("battery")
            if isinstance(battery, list):
                self.battery = battery
        if on_change and not self._stop.is_set():
            on_change()

    def _ensure_media_bridge(self):
        if self.media_proc and self.media_proc.poll() is None:
            return
        script = os.path.join(W.APP_DIR, "assets", "MediaBridge.ps1")
        if not os.path.exists(script):
            with self._media_lock:
                self.media = {"error": "缺少 MediaBridge.ps1"}
            return
        powershell = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
        )
        proc = subprocess.Popen(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", script, "-OutFile", self.media_file],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=0x08000000
        )
        self.media_proc = proc

    def _media_reader(self, proc):
        pass

    def _stop_media_bridge(self):
        proc = self.media_proc
        self.media_proc = None
        if proc and proc.poll() is None:
            proc.kill()

    def media_action(self, action: str):
        threading.Thread(
            target=lambda: asyncio.run(self._media_control(action)),
            daemon=True
        ).start()

    async def _media_control(self, action: str):
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager
            )
        except Exception as exc:
            W.log(f"[media] winrt 不可用: {exc!r}")
            return
        try:
            manager = await Manager.request_async()
            sessions = list(manager.get_sessions())
            if not sessions:
                return
            session = sessions[0]
            if action == "next":
                await session.try_skip_next_async()
            elif action == "prev":
                await session.try_skip_previous_async()
            else:
                await session.try_toggle_play_pause_async()
        except Exception as exc:
            W.log(f"[media] control failed: {exc!r}")

    async def _read_media(self) -> dict:
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager
            )
        except Exception:
            return {"error": "未安装 winrt 依赖（运行 launch-cards.ps1 自动安装）"}
        manager = await Manager.request_async()
        sessions = list(manager.get_sessions())
        if not sessions:
            return {}
        session = sessions[0]
        props = await session.try_get_media_properties_async()
        info = session.get_playback_info()
        status = ""
        if info and info.playback_status is not None:
            status = getattr(info.playback_status, "name", str(info.playback_status))
            status = status.capitalize()
        return {
            "app": session.source_app_user_model_id,
            "title": props.title or "",
            "artist": props.artist or "",
            "album": props.album_title or "",
            "status": status,
        }

    def _refresh_media(self):
        self.media = asyncio.run(self._read_media())

    def _refresh_calendar(self):
        cfg = self.app.cfg.get("calendar") or {}
        source = (cfg.get("ics") or "").strip()
        if not source:
            self.calendar = {
                "today": time.strftime("%m月%d日"), "events": [],
                "error": "未配置 calendar.ics",
            }
            return
        text = _load_ics(source)
        events = _parse_ics_events(text, days=7)
        self.calendar = {
            "today": time.strftime("%m月%d日"),
            "events": events[:3],
            "error": "" if events else "最近 7 天没有事件",
        }

    def _battery_loop(self, on_change):
        while not self._stop.is_set():
            try:
                before = self.battery
                self._refresh_battery()
                if self.battery != before and on_change and not self._stop.is_set():
                    on_change()
            except Exception as exc:
                W.log(f"[battery] {exc!r}")
            self._stop.wait(60)

    def _refresh_battery(self):
        # 经典蓝牙没有通用电量 API；BTHLE 的 PnP 查询在这台机器上会卡住，
        # 先保持空列表，卡片明确显示“暂无可读电量”，不伪造百分比。
        self.battery = []


class CardApp:
    def __init__(self):
        self.cfg = W.load_config()
        self.hub = W.DataHub(self.cfg)
        res = self.cfg.get("resources", {})
        self.sys = W.SysStats(res.get("disk", "C:"), res.get("cpu_history", 60))
        self.sys.sample()
        self.dpi_scale = max(1.0, _user32.GetDpiForSystem() / 96.0)
        try:
            saved_scale = float(self.cfg.get("scale") or 1.0)
        except (TypeError, ValueError):
            saved_scale = 1.0
        self.user_scale = min(2.2, max(0.55, saved_scale))
        self.scale = self.dpi_scale * self.user_scale
        self.opacity = self.cfg.get("opacity_levels", [1.0])[0]
        cards_cfg = self.cfg.get("cards") or {}
        self.locked = bool(cards_cfg.get("locked", False))
        self.hidden_keys = set(cards_cfg.get("hidden") or [])
        self.zooms = {}
        for key, value in (cards_cfg.get("zooms") or {}).items():
            try:
                self.zooms[key] = max(0.6, min(2.2, float(value)))
            except (TypeError, ValueError):
                pass
        # v3 新增四个卡片，默认先收起来，等用户在“添加组件”里点开。
        if int(cards_cfg.get("version", 2) or 2) < 3:
            self.hidden_keys.update({"volume", "music", "battery", "calendar"})
        self.visible = True
        self.hover = None
        self.clickthrough = False
        self.clickthrough_until = 0.0
        self.last_minute = None
        self.last_tip = 0.0
        self.last_raise = 0.0
        self.desktop_only = bool(self.cfg.get("desktop_only", True))
        self.desktop_active_state = None
        self.menu_open = False
        self.cards: list[CardWindow] = []
        self.extra = ExtraHub(self)
        self.full_cache = {}
        self.drag_card = None
        self.pending_snap = None
        self.shadow = None
        self.guide_v = None
        self.guide_h = None
        self._shadow_cache = {}
        self._shadow_key = None
        self._guide_state = (None, None)
        self._drag_feedback_last = 0.0

        self._register_classes()
        self.host = CardHost(self)
        positions = self._load_positions()
        for key, rect, label in CARD_SPECS:
            x, y = positions[key]
            self.cards.append(CardWindow(
                self, key, rect, label, x, y, self.zooms.get(key, 1.0)
            ))
        for card in self.cards:
            card.set_visible(card.key not in self.hidden_keys)
        self._create_overlays()
        self.gallery = GalleryWindow(self)
        self.host.add_tray()
        self.host.update_tip()

        self.hub.start(self.host.post_rerender)
        self.extra.start(self.host.post_rerender)
        self._start_sampler()
        self.last_minute = time.strftime("%H:%M")

    def _register_classes(self) -> None:
        hinst = W.kernel32.GetModuleHandleW(None)
        for cls, proc in (
            (CARD_CLASS, CARD_WNDPROC),
            (HOST_CLASS, HOST_WNDPROC),
            (OVERLAY_CLASS, OVERLAY_WNDPROC),
            (GALLERY_CLASS, GALLERY_WNDPROC),
        ):
            wc = W.WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(W.WNDCLASSEXW)
            wc.lpfnWndProc = proc
            wc.hInstance = hinst
            wc.hCursor = _user32.LoadCursorW(None, W.IDC_SIZEALL)
            wc.lpszClassName = cls
            if not _user32.RegisterClassExW(ctypes.byref(wc)):
                err = ctypes.get_last_error()
                if err != 1410:
                    raise OSError(f"RegisterClassExW({cls}) 失败: {err}")

    # -- 对齐/落点阴影 -------------------------------------------------------
    def _create_overlays(self) -> None:
        left, top, right, bottom = _work_area()
        self.shadow = LayeredOverlay(Image.new("RGBA", (2, 2), (0, 0, 0, 0)))
        self.shadow.hide()
        self.guide_v = LayeredOverlay(_guide_image(bottom - top, True))
        self.guide_h = LayeredOverlay(_guide_image(right - left, False))
        self.guide_v.hide()
        self.guide_h.hide()

    def _shadow_image(self, card: CardWindow) -> tuple[Image.Image, int]:
        margin = max(6, int(round(12 * self.scale)))
        w, h = card.card_w, card.card_h
        img = Image.new("RGBA", (w + margin * 2, h + margin * 2), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle(
            (margin, margin, margin + w, margin + h),
            radius=max(8, int(round(W.RADIUS * self.scale)) + 4),
            fill=(0, 0, 0, 140)
        )
        img = img.filter(ImageFilter.GaussianBlur(5))
        # 落点轮廓：只看阴影容易糊，加一圈青色提示
        d = ImageDraw.Draw(img)
        d.rounded_rectangle(
            (margin, margin, margin + w, margin + h),
            radius=max(8, int(round(W.RADIUS * self.scale)) + 4),
            outline=(84, 228, 190, 120), width=1
        )
        return img, margin

    def begin_drag(self, card: CardWindow) -> None:
        self.drag_card = card
        self._drag_feedback_last = 0.0
        self._guide_state = (None, None)
        self.update_drag_feedback(card)

    def compute_snap(self, card: CardWindow):
        rect = W.RECT()
        _user32.GetWindowRect(card.hwnd, ctypes.byref(rect))
        x = rect.left + card.offset[0]
        y = rect.top + card.offset[1]
        w, h = card.card_w, card.card_h
        left, top, right, bottom = _work_area()
        center_x = left + (right - left - w) // 2
        center_y = top + (bottom - top - h) // 2

        xs = [(left, left), (right - w, right), (center_x, left + (right - left) // 2)]
        ys = [(top, top), (bottom - h, bottom), (center_y, top + (bottom - top) // 2)]
        for other in self.cards:
            if other is card or not other.visible:
                continue
            ox, oy = other.card_x, other.card_y
            ow, oh = other.card_w, other.card_h
            gap = max(4, int(round(CARD_GAP * self.scale)))
            # 只在两张卡「横向/纵向离得近」时才做这一轴的边缘对齐，
            # 否则隔半屏的卡也会把当前卡吸过去，手感很怪。
            if abs((y + h / 2) - (oy + oh / 2)) <= (h + oh) / 2 + 100:
                xs.extend([
                    (ox, ox),
                    (ox + ow, ox + ow),
                    (ox + ow - w, ox + ow),
                    (ox + (ow - w) // 2, ox + ow // 2),
                    (ox + ow + gap, ox + ow + gap),
                    (ox - w - gap, ox - gap),
                ])
            if abs((x + w / 2) - (ox + ow / 2)) <= (w + ow) / 2 + 100:
                ys.extend([
                    (oy, oy),
                    (oy + oh, oy + oh),
                    (oy + oh - h, oy + oh),
                    (oy + (oh - h) // 2, oy + oh // 2),
                    (oy + oh + gap, oy + oh + gap),
                    (oy - h - gap, oy - gap),
                ])

        def pick(pos, origin, candidates):
            best = None
            for target, guide in candidates:
                delta = target - pos
                if abs(delta) <= SNAP_MAGNET and (
                    best is None or abs(delta) < abs(best[0])
                ):
                    best = (delta, guide)
            if best:
                return pos + best[0], best[1]
            snapped = origin + int(round((pos - origin) / SNAP_GRID)) * SNAP_GRID
            return snapped, None

        sx, gx = pick(x, left, xs)
        sy, gy = pick(y, top, ys)
        return sx, sy, gx, gy

    def update_drag_feedback(self, card: CardWindow) -> None:
        if self.shadow is None:
            return
        now = time.time()
        if now - self._drag_feedback_last < 0.012:
            return
        self._drag_feedback_last = now
        sx, sy, gx, gy = self.compute_snap(card)
        self.pending_snap = (sx, sy)
        key = (card.card_w, card.card_h, round(card.scale, 3))
        cached = self._shadow_cache.get(key)
        if cached is None:
            cached = self._shadow_image(card)
            if len(self._shadow_cache) > 20:
                self._shadow_cache.clear()
            self._shadow_cache[key] = cached
        img, margin = cached
        if key != self._shadow_key:
            self._shadow_key = key
            self.shadow.set_image(img)
        self.shadow.move(sx - margin, sy - margin, insert_after=card.hwnd)
        self.shadow.show()
        left, top, right, bottom = _work_area()
        if gx != self._guide_state[0]:
            if gx is not None:
                self.guide_v.move(int(gx), top)
                self.guide_v.show()
            else:
                self.guide_v.hide()
        if gy != self._guide_state[1]:
            if gy is not None:
                self.guide_h.move(left, int(gy))
                self.guide_h.show()
            else:
                self.guide_h.hide()
        self._guide_state = (gx, gy)

    def finish_drag(self, card: CardWindow) -> None:
        if self.drag_card is not card:
            return
        sx, sy, _, _ = self.compute_snap(card)
        card.set_card_pos(sx, sy)
        self._hide_feedback()
        self.drag_card = None
        self.save_layout()

    def cancel_drag(self, card: CardWindow) -> None:
        if self.drag_card is card:
            self._hide_feedback()
            self.drag_card = None

    def _hide_feedback(self) -> None:
        self.pending_snap = None
        self._guide_state = (None, None)
        if self.shadow:
            self.shadow.hide()
        if self.guide_v:
            self.guide_v.hide()
        if self.guide_h:
            self.guide_h.hide()

    # -- 数据 ---------------------------------------------------------------
    def state(self) -> dict:
        state = self.hub.snapshot()
        state.update(self.sys.snapshot())
        return state

    def _full_for(self, scale: float, fast: bool = False):
        key = round(scale, 3)
        cached = self.full_cache.get(key)
        if cached is None:
            cached = W.render(
                self.state(), scale, self.opacity, self.hover,
                self.clickthrough, False, None, fast
            )
            self.full_cache[key] = cached
        return cached

    def refresh(self, fast: bool = False) -> None:
        if not self.visible or any(c.drag_started or c.resizing for c in self.cards):
            return
        self.full_cache = {}
        for card in self.cards:
            if not card.visible:
                continue
            if card.kind == "custom":
                image, offset, buttons = self.render_custom(
                    card.key, card.card_w, card.card_h, card.scale
                )
            else:
                image, offset, buttons = self.crop_card(card.rect, card.scale)
            card.update_image(image, offset, buttons)
        self.host.update_tip()

    def crop_card(self, rect, scale: float):
        cx, cy, cw, ch = rect
        full_image, full_buttons = self._full_for(scale)
        pad = int(W.SHADOW * scale)
        margin = max(2, int(round(CARD_MARGIN * scale)))
        left = max(0, pad + int(round(cx * scale)) - margin)
        top = max(0, pad + int(round(cy * scale)) - margin)
        right = min(full_image.width,
                    pad + int(round((cx + cw) * scale)) + margin)
        bottom = min(full_image.height,
                     pad + int(round((cy + ch) * scale)) + margin)
        image = full_image.crop((left, top, right, bottom))
        offset = (
            pad + int(round(cx * scale)) - left,
            pad + int(round(cy * scale)) - top,
        )
        buttons = {}
        for name, (x0, y0, x1, y1) in full_buttons.items():
            bx0 = pad + x0 * scale - left
            by0 = pad + y0 * scale - top
            bx1 = pad + x1 * scale - left
            by1 = pad + y1 * scale - top
            if bx1 >= 0 and by1 >= 0 and bx0 <= image.width and by0 <= image.height:
                buttons[name] = (bx0, by0, bx1, by1)
        return image, offset, buttons

    def render_custom(self, key: str, w: int, h: int, scale: float):
        fn = CUSTOM_RENDERERS.get(key)
        if fn is None:
            return Image.new("RGBA", (w, h), (0, 0, 0, 0)), (0, 0), {}
        return fn(self, w, h, scale)

    def set_card_zoom(self, card: CardWindow, zoom: float) -> None:
        zoom = max(0.6, min(2.2, float(zoom)))
        card.zoom = zoom
        card.scale = self.scale * zoom
        if card.kind == "custom":
            cw, ch = CUSTOM_SPECS[card.key]
            card.card_w = max(1, int(round(cw * card.scale)))
            card.card_h = max(1, int(round(ch * card.scale)))
            image, offset, buttons = self.render_custom(
                card.key, card.card_w, card.card_h, card.scale
            )
        else:
            card.card_w = max(1, int(round(card.rect[2] * card.scale)))
            card.card_h = max(1, int(round(card.rect[3] * card.scale)))
            image, offset, buttons = self.crop_card(card.rect, card.scale)
        card.update_image(image, offset, buttons)
        card.set_card_pos(card.card_x, card.card_y)

    def preview_card_zoom(self, card: CardWindow, zoom: float) -> None:
        """拖动缩放时先用位图拉伸预览，松手后再按新尺寸重绘。"""
        if card.resize_snapshot is None:
            return
        zoom = max(0.6, min(2.2, float(zoom)))
        ratio = zoom / max(0.01, card.resize_base)
        bw, bh = card.resize_base_card
        ox, oy = card.resize_base_offset
        card.zoom = zoom
        card.scale = self.scale * zoom
        card.card_w = max(1, int(round(bw * ratio)))
        card.card_h = max(1, int(round(bh * ratio)))
        card.offset = (max(0, int(round(ox * ratio))),
                       max(0, int(round(oy * ratio))))
        sw, sh = card.resize_snapshot.size
        card.image = card.resize_snapshot.resize(
            (max(1, int(round(sw * ratio))), max(1, int(round(sh * ratio)))),
            Image.BILINEAR
        )
        card.buttons = {}
        self.ensure_zorder(card)
        _user32.SetWindowPos(
            card.hwnd, self.current_zorder(),
            0, 0, card.image.width, card.image.height,
            W.SWP_NOMOVE | W.SWP_NOACTIVATE
        )
        card.set_card_pos(card.card_x, card.card_y)
        card.present()

    # -- 位置与布局 ---------------------------------------------------------
    def _default_positions(self) -> dict:
        left, top, right, _ = _work_area()
        panel = self.cfg.get("position")
        if isinstance(panel, (list, tuple)) and len(panel) == 2:
            px, py = int(panel[0]), int(panel[1])
        else:
            px = right - int(420 * self.scale) - 20
            py = top + 20
        px = max(left, min(px, right - int(420 * self.scale)))
        py = max(top, py)
        gap = max(4, int(round(CARD_GAP * self.scale)))
        weather_w = int(round(204 * self.scale))
        weather_h = int(round(188 * self.scale))
        extra_x = max(left, px - int((280 + CARD_GAP) * self.scale))
        music_y = py + int((200 + CARD_GAP) * self.scale)
        extra_y2 = py + int((200 + CARD_GAP + 200 + CARD_GAP) * self.scale)
        return {
            "weather": (px, py),
            "balance": (px + weather_w + gap, py),
            "system": (px, py + weather_h + gap),
            "volume": (extra_x, py),
            "music": (extra_x, music_y),
            "battery": (extra_x, extra_y2),
            "calendar": (extra_x + int((220 + CARD_GAP) * self.scale), extra_y2),
        }

    def _load_positions(self) -> dict:
        defaults = self._default_positions()
        saved = (self.cfg.get("cards") or {}).get("positions") or {}
        result = {}
        for key, _, _ in CARD_SPECS:
            value = saved.get(key)
            if isinstance(value, (list, tuple)) and len(value) == 2:
                result[key] = (int(value[0]), int(value[1]))
            else:
                result[key] = defaults[key]
        return result

    def save_layout(self) -> None:
        try:
            data = {}
            if os.path.exists(W.CONFIG_PATH):
                with open(W.CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data["cards"] = {
                "version": 3,
                "grid": SNAP_GRID,
                "locked": self.locked,
                "hidden": [c.key for c in self.cards if not c.visible],
                "zooms": {c.key: round(c.zoom, 3) for c in self.cards},
                "positions": {c.key: [c.card_x, c.card_y] for c in self.cards},
            }
            with open(W.CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            W.log(f"[cards] 保存布局失败: {exc!r}")

    def reset_layout(self) -> None:
        self.locked = False
        self.hidden_keys.clear()
        self.visible = True
        positions = self._default_positions()
        for card in self.cards:
            x, y = positions[card.key]
            card.set_card_pos(x, y)
        self.apply_visibility()
        self.save_layout()
        self.refresh()
        self.desktop_active_state = None
        self.sync_desktop_layer()

    def clamp_cards(self) -> None:
        for card in self.cards:
            card.set_card_pos(card.card_x, card.card_y)
        self.save_layout()
        self.refresh()

    def toggle_lock(self) -> None:
        self.locked = not self.locked
        self.save_layout()

    # -- 交互 ---------------------------------------------------------------
    def set_hover(self, name) -> None:
        if self.hover != name:
            self.hover = name
            self.refresh()

    def action(self, name) -> None:
        if name == "close":
            self.quit()
        elif name == "refresh":
            self.hub.refresh_now()
            threading.Thread(
                target=lambda: (self.hub._fetch_weather(),
                                self.hub._fetch_balance(),
                                self.host.post_rerender()),
                daemon=True
            ).start()
        elif name == "opacity":
            levels = self.cfg.get("opacity_levels", [1.0])
            idx = levels.index(self.opacity) if self.opacity in levels else 0
            self.opacity = levels[(idx + 1) % len(levels)]
            self.refresh()
        elif name == "clickthrough":
            self.clickthrough = not self.clickthrough
            seconds = float(self.cfg.get("clickthrough_seconds", 10) or 0)
            self.clickthrough_until = (
                time.time() + seconds if self.clickthrough and seconds > 0 else 0.0
            )
            for card in self.cards:
                ex = W.GET_LONG(card.hwnd, W.GWL_EXSTYLE)
                if self.clickthrough:
                    ex |= W.WS_EX_TRANSPARENT
                else:
                    ex &= ~W.WS_EX_TRANSPARENT
                W.SET_LONG(card.hwnd, W.GWL_EXSTYLE, ex)
            self.refresh()
        elif name == "vol_up":
            self.extra.volume_step(0.05)
        elif name == "vol_down":
            self.extra.volume_step(-0.05)
        elif name == "vol_mute":
            self.extra.volume_mute()
        elif name.startswith("volapp:"):
            _, pid, direction = name.split(":", 2)
            try:
                pid_value = int(pid)
            except ValueError:
                return
            self.extra.volume_step(0.05 if direction == "up" else -0.05,
                                   target="pid", pid=pid_value)
        elif name.startswith("media_"):
            self.extra.media_action(name.split("_", 1)[1])
        elif name == "desktop":
            W.log("[cards] 原型暂不支持贴桌面层")

    def card_by_key(self, key: str):
        for card in self.cards:
            if card.key == key:
                return card
        return None

    def apply_visibility(self) -> None:
        for card in self.cards:
            card.set_visible(self.visible and card.key not in self.hidden_keys)

    def toggle_card(self, key: str) -> bool:
        card = self.card_by_key(key)
        if card is None:
            return False
        if key in self.hidden_keys:
            self.hidden_keys.discard(key)
        else:
            self.hidden_keys.add(key)
        self.apply_visibility()
        self.save_layout()
        self.refresh()
        self.desktop_active_state = None
        self.sync_desktop_layer()
        if hasattr(self, "gallery") and self.gallery:
            self.gallery.render()
            self.gallery.present()
        return True

    def show_gallery(self) -> None:
        self.gallery.show()

    def gallery_action(self, name: str) -> None:
        if name.startswith("toggle:"):
            self.toggle_card(name.split(":", 1)[1])
        elif name == "reset":
            self.reset_layout()
            self.gallery.render()
            self.gallery.present()
        elif name in ("close", "close_top"):
            self.gallery.hide()

    def toggle_visible(self) -> None:
        self.visible = not self.visible
        self.apply_visibility()
        if self.visible:
            self.refresh()
        self.desktop_active_state = None
        self.sync_desktop_layer()
        self.host.update_tip()

    def show(self) -> None:
        if not self.visible:
            self.toggle_visible()
        self.desktop_active_state = None
        self.sync_desktop_layer()

    def show_menu(self) -> None:
        self.host.show_menu()

    def show_card_menu(self, card: CardWindow) -> None:
        self.host.show_menu(card)

    def hide_card(self, card: CardWindow) -> None:
        self.hidden_keys.add(card.key)
        self.apply_visibility()
        self.save_layout()
        self.refresh()
        self.desktop_active_state = None
        self.sync_desktop_layer()
        if getattr(self, "gallery", None):
            self.gallery.render()
            self.gallery.present()

    def reset_card_zoom(self, card: CardWindow) -> None:
        self.set_card_zoom(card, 1.0)
        self.save_layout()

    # -- 生命周期 -----------------------------------------------------------
    def tick(self) -> None:
        now = time.time()
        minute = time.strftime("%H:%M")
        if minute != self.last_minute:
            self.last_minute = minute
            self.refresh()
        if self.clickthrough_until and now >= self.clickthrough_until:
            self.action("clickthrough")
        if now - self.last_tip >= 10:
            self.last_tip = now
            self.host.update_tip()
        if now - self.last_raise >= 5:
            self.last_raise = now
            self.sync_desktop_layer()

    def current_zorder(self):
        return W.HWND_TOPMOST if self.desktop_active_state is not False else HWND_BOTTOM

    def set_card_topmost(self, card: CardWindow, on: bool) -> None:
        ex = W.GET_LONG(card.hwnd, W.GWL_EXSTYLE)
        if on:
            ex |= W.WS_EX_TOPMOST
        else:
            ex &= ~W.WS_EX_TOPMOST
        W.SET_LONG(card.hwnd, W.GWL_EXSTYLE, ex)
        _user32.SetWindowPos(
            card.hwnd, W.HWND_TOPMOST if on else HWND_BOTTOM, 0, 0, 0, 0,
            W.SWP_NOMOVE | W.SWP_NOSIZE | W.SWP_NOACTIVATE
        )

    def ensure_zorder(self, card: CardWindow) -> None:
        self.set_card_topmost(card, self.desktop_active_state is not False)

    def desktop_is_active(self) -> bool:
        if not self.desktop_only:
            return True
        fg = _user32.GetForegroundWindow()
        if not fg:
            return False
        if _user32.IsIconic(fg):
            return True
        rect = W.RECT()
        _user32.GetWindowRect(fg, ctypes.byref(rect))
        fw = max(0, rect.right - rect.left)
        fh = max(0, rect.bottom - rect.top)
        left, top, right, bottom = _work_area()
        area = max(1, (right - left) * (bottom - top))
        if fw * fh < area * 0.10:
            return True
        buf = ctypes.create_unicode_buffer(128)
        _user32.GetClassNameW(fg, buf, 128)
        return buf.value in DESKTOP_CLASSES

    def sync_desktop_layer(self) -> None:
        """桌面在前台时卡片置顶；普通窗口在前台时卡片退到最底层，不盖窗口。"""
        if not self.visible:
            return
        if self.drag_card or self.menu_open or any(c.resizing for c in self.cards):
            return
        active = self.desktop_is_active()
        if active == self.desktop_active_state:
            if active:
                for card in self.cards:
                    if card.visible:
                        _user32.ShowWindow(card.hwnd, W.SW_SHOWNOACTIVATE)
                        self.set_card_topmost(card, True)
            return
        self.desktop_active_state = active
        for card in self.cards:
            if not card.visible:
                continue
            _user32.ShowWindow(card.hwnd, W.SW_SHOWNOACTIVATE)
            self.set_card_topmost(card, active)

    def _start_sampler(self) -> None:
        interval = float(self.cfg.get("resources", {}).get("sample_seconds", 2.0) or 2.0)

        def loop():
            while True:
                time.sleep(max(0.5, interval))
                try:
                    self.sys.sample()
                    self.host.post_rerender()
                except Exception as exc:
                    W.log(f"[cards] 采样失败: {exc!r}")

        threading.Thread(target=loop, daemon=True).start()

    def quit(self) -> None:
        self.save_layout()
        self._hide_feedback()
        try:
            self.extra._stop.set()
            self.extra._stop_volume_bridge()
            self.extra._stop_media_bridge()
        except Exception:
            pass
        for card in self.cards:
            _user32.DestroyWindow(card.hwnd)
        self.cards = []
        for overlay in (self.shadow, self.guide_v, self.guide_h):
            if overlay:
                _user32.DestroyWindow(overlay.hwnd)
        if getattr(self, "gallery", None):
            _user32.DestroyWindow(self.gallery.hwnd)
        self.host.remove_tray()
        _user32.KillTimer(self.host.hwnd, 1)
        _user32.UnregisterHotKey(self.host.hwnd, 1)
        _user32.UnregisterHotKey(self.host.hwnd, 2)
        _user32.DestroyWindow(self.host.hwnd)
        _user32.PostQuitMessage(0)

    def run(self) -> int:
        _user32.SetTimer(self.host.hwnd, 1, 500, None)
        # 避开原版组件的 Ctrl+Alt+W / Ctrl+Alt+Q
        mods = 0x0002 | 0x0001 | 0x0004
        if not _user32.RegisterHotKey(self.host.hwnd, 1, mods, ord("W")):
            W.log("[cards] 复位热键注册失败")
        if not _user32.RegisterHotKey(self.host.hwnd, 2, mods, ord("Q")):
            W.log("[cards] 退出热键注册失败")
        self.refresh()
        W.log(f"[cards] 启动 {len(self.cards)} 张卡 scale={self.scale:.2f}")
        msg = W.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        return 0


def run() -> int:
    W.enable_dpi_awareness()
    global _MUTEX
    ctypes.set_last_error(0)
    _MUTEX = W.kernel32.CreateMutexW(None, False, "LumenDesktopWidgetCards")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        hwnd = _user32.FindWindowW(HOST_CLASS, None)
        if hwnd:
            _user32.PostMessageW(hwnd, W.WM_APP_SHOW, 0, 0)
        return 0
    try:
        open(W.LOG_PATH, "w", encoding="utf-8").close()
    except Exception:
        pass
    try:
        app = CardApp()
        return app.run()
    except Exception:
        W.log("[cards] 启动失败:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    sys.exit(run())
