# -*- coding: utf-8 -*-
"""
桌面浮窗小组件 v2：真实天气 + DeepSeek 余额 + 系统资源监控。

三块内容各占一张卡片：上面一张宽的天气卡，下面两张并排（DeepSeek 余额 / 系统资源）。

技术要点（也是「像不像手机小组件」的分水岭）：
1. UpdateLayeredWindow + 32 位 BGRA 位图   -> 真·逐像素透明，圆角和柔光投影都是画出来的
2. WS_EX_LAYERED | TOOLWINDOW | NOACTIVATE -> 置顶浮层、不进 Alt+Tab、点击不抢焦点
3. 鼠标交互全部自己处理（拖拽 / 自绘按钮），不依赖系统标题栏，外形完全自由
4. 取数在后台线程，画完用 PostMessage 回 UI 线程，消息循环永不被网络阻塞
5. 系统资源用 ctypes 直接问 Windows 要（GetSystemTimes / GlobalMemoryStatusEx /
   GetDiskFreeSpaceExW），零第三方依赖、零管理员权限

数据来源：
    天气    Open-Meteo（免密钥），坐标取自 config.json
    余额    DeepSeek 官方 /user/balance 接口，需要 API Key
    资源    本机实时采样（CPU / 内存 / 磁盘）

用法：
    python widget.py                    启动浮窗
    python widget.py --preview p.png    只渲染一帧到 PNG（不开窗、不联网），用来调外观

操作：
    拖动卡片空白处移动；卡片右上角小按钮 = 刷新 / 透明度 / 桌面层 / 穿透 / 关闭
    Ctrl + Alt + W = 一键恢复正常（从「穿透」或「桌面层」状态救回来）
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes as wt
from collections import deque
import json
import math
import os
import random
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from PIL import Image, ImageDraw, ImageFilter, ImageFont

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
BALANCE_HISTORY = os.path.join(APP_DIR, "balance_history.json")
LOG_PATH = os.path.join(APP_DIR, "widget.log")
# 密钥还可以放这些地方：桌面上的 api.txt / 脚本旁边的 api.txt（放在 config.json 里也行）
API_KEY_FILES = [
    os.path.join(APP_DIR, "api.txt"),
    os.path.join(os.path.expanduser("~"), "Desktop", "api.txt"),
    os.path.join(os.path.expanduser("~"), "Documents", "api.txt"),
]


def log(msg: str) -> None:
    """后台程序没有控制台，出问题只能靠日志说话。"""
    line = f"{datetime.now():%H:%M:%S} {msg}"
    try:
        print(line)
    except Exception:
        pass
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _configure_streams() -> None:
    """pythonw 下 stdout 可能是 None，或者按 GBK 编码 —— 不能让一句 print 崩掉整个程序。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass


_configure_streams()

# --------------------------------------------------------------------------
# 一、Win32 基础
# --------------------------------------------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000

GWL_EXSTYLE = -20
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SW_SHOWNOACTIVATE = 4

ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
DIB_RGB_COLORS = 0

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_TIMER = 0x0113
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_SETCURSOR = 0x0020
WM_DISPLAYCHANGE = 0x007E
WM_HOTKEY = 0x0312
WM_APP = 0x8000
WM_APP_RERENDER = WM_APP + 1
WM_APP_TRAY = WM_APP + 3
WM_APP_SHOW = WM_APP + 4

MUTEX_NAME = "Local\\LumenDesktopWidget"
ERROR_ALREADY_EXISTS = 183

WM_LBUTTONDBLCLK = 0x0203
WM_CONTEXTMENU = 0x007B
WM_CAPTURECHANGED = 0x0215

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_CHECKED = 0x00000008
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100

SW_HIDE = 0
SW_SHOWNOACTIVATE = 4

IDC_SIZENWSE = 32642

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

VK_F9 = 0x78
VK_F10 = 0x79

# 复位 / 退出快捷键的候选列表：挨个试，谁没被占用就用谁。
# 之前只试一个 Ctrl+Alt+W，结果它被别的软件占了，穿透之后就没有退路了。
RESET_HOTKEYS = [
    (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("W"), "Ctrl+Alt+W"),
    (MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT, ord("W"), "Ctrl+Alt+Shift+W"),
    (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_F9, "Ctrl+Alt+F9"),
    (MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT, VK_F9, "Ctrl+Alt+Shift+F9"),
]
QUIT_HOTKEYS = [
    (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("Q"), "Ctrl+Alt+Q"),
    (MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT, ord("Q"), "Ctrl+Alt+Shift+Q"),
    (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_F10, "Ctrl+Alt+F10"),
]

IDC_HAND = 32649
IDC_SIZEALL = 32646
SPI_GETWORKAREA = 0x0030


class POINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wt.LONG), ("cy", wt.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG), ("right", wt.LONG), ("bottom", wt.LONG)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


class RGBQUAD(ctypes.Structure):
    _fields_ = [("rgbBlue", ctypes.c_ubyte), ("rgbGreen", ctypes.c_ubyte),
                ("rgbRed", ctypes.c_ubyte), ("rgbReserved", ctypes.c_ubyte)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON),
    ]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wt.HWND), ("message", wt.UINT), ("wParam", wt.WPARAM),
                ("lParam", wt.LPARAM), ("time", wt.DWORD), ("pt", POINT)]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wt.DWORD), ("dwMemoryLoad", wt.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    """shell32 的托盘图标结构体，字段顺序必须和 Windows 头文件一致。"""
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("hWnd", wt.HWND),
        ("uID", wt.UINT),
        ("uFlags", wt.UINT),
        ("uCallbackMessage", wt.UINT),
        ("hIcon", wt.HICON),
        ("szTip", wt.WCHAR * 128),
        ("dwState", wt.DWORD),
        ("dwStateMask", wt.DWORD),
        ("szInfo", wt.WCHAR * 256),
        ("uTimeoutOrVersion", wt.UINT),
        ("szInfoTitle", wt.WCHAR * 64),
        ("dwInfoFlags", wt.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wt.HICON),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wt.BOOL), ("xHotspot", wt.DWORD), ("yHotspot", wt.DWORD),
                ("hbmMask", wt.HBITMAP), ("hbmColor", wt.HBITMAP)]


def declare(fn, restype=None, argtypes=None):
    """把 Win32 函数签名写清楚 —— 64 位下不声明就等着句柄被截断。"""
    if restype is not None:
        fn.restype = restype
    if argtypes:
        fn.argtypes = list(argtypes)
    return fn


declare(user32.CreateWindowExW, wt.HWND,
        [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
         ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID])
declare(user32.DefWindowProcW, LRESULT, [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM])
declare(user32.GetDC, wt.HDC, [wt.HWND])
declare(user32.ReleaseDC, ctypes.c_int, [wt.HWND, wt.HDC])
declare(user32.LoadCursorW, wt.HANDLE, [wt.HINSTANCE, ctypes.c_void_p])
declare(user32.SetCursor, wt.HANDLE, [wt.HANDLE])
declare(user32.FindWindowW, wt.HWND, [wt.LPCWSTR, wt.LPCWSTR])
declare(user32.FindWindowExW, wt.HWND, [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR])
declare(user32.SetParent, wt.HWND, [wt.HWND, wt.HWND])
declare(user32.SetWindowPos, wt.BOOL, [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wt.UINT])
declare(user32.ShowWindow, wt.BOOL, [wt.HWND, ctypes.c_int])
declare(user32.GetWindowRect, wt.BOOL, [wt.HWND, ctypes.POINTER(RECT)])
declare(user32.GetCursorPos, wt.BOOL, [ctypes.POINTER(POINT)])
declare(user32.SetCapture, wt.HWND, [wt.HWND])
declare(user32.ReleaseCapture, wt.BOOL, [])
declare(user32.PostMessageW, wt.BOOL, [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM])
declare(user32.DestroyWindow, wt.BOOL, [wt.HWND])
declare(user32.PostQuitMessage, None, [ctypes.c_int])
declare(user32.SetTimer, ctypes.c_size_t, [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p])
declare(user32.KillTimer, wt.BOOL, [wt.HWND, ctypes.c_size_t])
declare(user32.RegisterHotKey, wt.BOOL, [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT])
declare(user32.UnregisterHotKey, wt.BOOL, [wt.HWND, ctypes.c_int])
declare(user32.GetMessageW, wt.BOOL, [ctypes.POINTER(MSG), wt.HWND, wt.UINT, wt.UINT])
declare(user32.TranslateMessage, wt.BOOL, [ctypes.POINTER(MSG)])
declare(user32.DispatchMessageW, LRESULT, [ctypes.POINTER(MSG)])
declare(user32.UpdateLayeredWindow, wt.BOOL,
        [wt.HWND, wt.HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE), wt.HDC,
         ctypes.POINTER(POINT), wt.DWORD, ctypes.POINTER(BLENDFUNCTION), wt.DWORD])
declare(user32.GetDpiForSystem, wt.UINT, [])
declare(user32.SystemParametersInfoW, wt.BOOL, [wt.UINT, wt.UINT, wt.LPVOID, wt.UINT])
declare(user32.SendMessageTimeoutW, LRESULT,
        [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT, ctypes.c_void_p])
declare(kernel32.GetSystemTimes, wt.BOOL,
        [ctypes.POINTER(wt.FILETIME), ctypes.POINTER(wt.FILETIME), ctypes.POINTER(wt.FILETIME)])
declare(kernel32.CreateMutexW, wt.HANDLE, [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR])
declare(kernel32.GlobalMemoryStatusEx, wt.BOOL, [ctypes.POINTER(MEMORYSTATUSEX)])
declare(kernel32.GetDiskFreeSpaceExW, wt.BOOL,
        [wt.LPCWSTR, ctypes.POINTER(ctypes.c_ulonglong),
         ctypes.POINTER(ctypes.c_ulonglong), ctypes.POINTER(ctypes.c_ulonglong)])
declare(shell32.Shell_NotifyIconW, wt.BOOL,
        [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)])
declare(user32.CreatePopupMenu, wt.HMENU, [])
declare(user32.AppendMenuW, wt.BOOL, [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR])
declare(user32.TrackPopupMenu, wt.BOOL, [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int,
                                         ctypes.c_int, wt.HWND, ctypes.c_void_p])
declare(user32.DestroyMenu, wt.BOOL, [wt.HMENU])
declare(user32.SetForegroundWindow, wt.BOOL, [wt.HWND])
declare(user32.CreateIconIndirect, wt.HICON, [ctypes.POINTER(ICONINFO)])
declare(user32.DestroyIcon, wt.BOOL, [wt.HICON])
declare(user32.ShowWindow, wt.BOOL, [wt.HWND, ctypes.c_int])
declare(gdi32.CreateBitmap, wt.HBITMAP,
        [ctypes.c_int, ctypes.c_int, wt.UINT, wt.UINT, ctypes.c_void_p])
declare(gdi32.DeleteObject, wt.BOOL, [wt.HGDIOBJ])
# 这几个也必须声明：GDI 句柄是 32 位值，符号扩展后可能超过 2^31，
# 不写 argtypes 时 ctypes 会按 C int 转换并抛 OverflowError —— 之前是偶发崩溃。
declare(gdi32.CreateCompatibleDC, wt.HDC, [wt.HDC])
declare(gdi32.DeleteDC, wt.BOOL, [wt.HDC])
declare(gdi32.SelectObject, wt.HGDIOBJ, [wt.HDC, wt.HGDIOBJ])
declare(gdi32.CreateDIBSection, wt.HBITMAP,
        [wt.HDC, ctypes.POINTER(BITMAPINFO), wt.UINT,
         ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD])
# 生成桌面快捷方式要用 Shell 的 COM 接口
declare(ole32.CoInitialize, ctypes.c_long, [ctypes.c_void_p])
declare(ole32.CoCreateInstance, ctypes.c_long,
        [ctypes.POINTER(GUID), ctypes.c_void_p, wt.DWORD,
         ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)])
declare(shell32.SHGetFolderPathW, ctypes.c_long,
        [wt.HWND, ctypes.c_int, wt.HANDLE, wt.DWORD, wt.LPWSTR])

SET_LONG = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
GET_LONG = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
declare(SET_LONG, ctypes.c_ssize_t, [wt.HWND, ctypes.c_int, ctypes.c_ssize_t])
declare(GET_LONG, ctypes.c_ssize_t, [wt.HWND, ctypes.c_int])


def enable_dpi_awareness() -> None:
    """不声明 DPI 感知，在缩放 125%/150% 的屏幕上整套 UI 会被系统拉糊。"""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except Exception:
        try:
            ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        except Exception:
            user32.SetProcessDPIAware()


# --------------------------------------------------------------------------
# 二、配置
# --------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "city": "杭州",
    "latitude": 30.2741,
    "longitude": 120.1551,
    "timezone": "Asia/Shanghai",
    "weather_refresh_minutes": 10,
    # 天气源：auto = 依次尝试 cma → qweather → open-meteo；也可以写死其中一个
    "weather": {
        "source": "auto",
        # 中国天气网的城市编码，杭州 = 101210101
        "cma_city_id": "101210101",
        # 和风天气：key 可以填这里，也可以放 env QWEATHER_KEY，或 api.txt 里备注「天气」的那行
        "qweather": {
            "api_host": "devapi.qweather.com",
            "key": "",
            "key_hint": "天气",
        },
    },
    "deepseek": {
        "api_key": "",
        "refresh_minutes": 5,
        "currency": "CNY",
        # api.txt 里有多把 Key 时，按备注里的这个词挑（默认挑「余额」那把）
        "key_hint": "余额",
    },
    "resources": {
        "disk": "C:",
        "sample_seconds": 2.0,
        "cpu_history": 60,
    },
    # 鼠标穿透自动解除的秒数。设成 0 = 永久穿透（那就只能靠快捷键救回来了）
    "clickthrough_seconds": 10,
    # 界面缩放：右下角拖动会改这个值，也可以直接写数字（0.55 ~ 2.2）
    "scale": 1.0,
    # 启动后先躲在托盘里，点托盘图标再显示
    "start_hidden": False,
    "opacity_levels": [1.0, 0.9, 0.78, 0.62],
    "position": None,
}


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for key, value in saved.items():
                if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                    cfg[key].update(value)
                else:
                    cfg[key] = value
        except Exception as exc:
            print(f"[config] 读取失败，用默认值: {exc}")
    return cfg


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"[config] 保存失败: {exc}")


def save_runtime_state(cfg: dict) -> None:
    """只把「位置 / 缩放」写回文件，别的字段保持磁盘上的现状。

    早先这里是整份内存配置覆盖回去，结果程序运行期间你在 config.json 里改的
    api_key 会被它在退出时冲掉 —— 只回写自己管的那两个字段就不会了。
    """
    try:
        data = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        if cfg.get("position") is not None:
            data["position"] = cfg["position"]
        if cfg.get("scale") is not None:
            data["scale"] = cfg["scale"]
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log(f"[config] 保存运行时状态失败: {exc}")


KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{12,}")
# 和风天气那种不是 sk- 开头的 key，用宽一点的规则，但只在带备注的行上认
LOOSE_KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{15,}")


def line_label(line: str, pattern=KEY_PATTERN) -> str:
    """把行里的密钥抠掉，剩下的就是备注（比如「余额」「天气」）。"""
    return pattern.sub("", line).strip(" \t-—－:：,，、\"'")


def find_labeled_key(hint: str, pattern=KEY_PATTERN) -> str:
    """在 api.txt 里找备注命中 hint 的那把 key。"""
    if not hint:
        return ""
    for path in API_KEY_FILES:
        for cand, line in read_key_file(path, pattern):
            label = line_label(line, pattern)
            if label and hint in label:
                return cand
    return ""


def read_key_file(path: str, pattern=KEY_PATTERN):
    """从一个密钥文件里取出所有 (key, 整行) —— 行里可以带中文备注，比如 sk-xxx——余额。"""
    try:
        if not os.path.exists(path):
            return []
        text = open(path, "r", encoding="utf-8-sig", errors="ignore").read()
    except Exception:
        return []
    found = []
    for line in text.splitlines():
        match = pattern.search(line)
        if match:
            found.append((match.group(0), line))
    return found


_D4 = (ctypes.c_ubyte * 8)(0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46)
CLSID_SHELLLINK = GUID(0x00021401, 0x0000, 0x0000, _D4)
IID_ISHELLLINKW = GUID(0x000214F9, 0x0000, 0x0000, _D4)
IID_IPERSISTFILE = GUID(0x0000010B, 0x0000, 0x0000, _D4)
CLSCTX_INPROC_SERVER = 1
CSIDL_DESKTOPDIRECTORY = 0x0010


def _com_fn(ptr, index, restype, *argtypes):
    """按 vtable 序号调 COM 方法（第 0 个参数是接口指针本身）。"""
    vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])


def desktop_dir() -> str:
    """桌面路径得问 Shell —— 有人把桌面重定向到 OneDrive 了，不能硬拼 ~\\Desktop。"""
    buf = ctypes.create_unicode_buffer(260)
    if shell32.SHGetFolderPathW(None, CSIDL_DESKTOPDIRECTORY, None, 0, buf) == 0 and buf.value:
        return buf.value
    return os.path.join(os.path.expanduser("~"), "Desktop")


def shortcut_path() -> str:
    return os.path.join(desktop_dir(), "桌面小组件.lnk")


def create_desktop_shortcut() -> str:
    """生成桌面快捷方式（IShellLink，带参数和图标）。失败返回空串。

    为什么由程序自己建：只有进程知道自己在用哪个解释器。Codex 换了运行时、
    路径变了，下次启动它会自己重建，快捷方式不会变成死链。
    """
    path = shortcut_path()
    pyw = sys.executable
    if pyw.lower().endswith("python.exe"):
        candidate = pyw[: -len("python.exe")] + "pythonw.exe"
        if os.path.exists(candidate):
            pyw = candidate
    icon = os.path.join(APP_DIR, "app.ico")
    ole32.CoInitialize(None)
    psl = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(CLSID_SHELLLINK), None, CLSCTX_INPROC_SERVER,
                                ctypes.byref(IID_ISHELLLINKW), ctypes.byref(psl))
    if hr != 0 or not psl:
        log(f"[shortcut] 创建 COM 对象失败 hr={hr}")
        return ""
    try:
        _com_fn(psl, 20, ctypes.c_long, ctypes.c_wchar_p)(psl, pyw)            # SetPath
        _com_fn(psl, 11, ctypes.c_long, ctypes.c_wchar_p)(
            psl, f'"{os.path.abspath(__file__)}"')                             # SetArguments
        _com_fn(psl, 9, ctypes.c_long, ctypes.c_wchar_p)(psl, APP_DIR)         # SetWorkingDirectory
        _com_fn(psl, 7, ctypes.c_long, ctypes.c_wchar_p)(
            psl, "桌面小组件：天气 / DeepSeek 余额 / 系统资源")                  # SetDescription
        if os.path.exists(icon):
            _com_fn(psl, 17, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int)(psl, icon, 0)
        _com_fn(psl, 15, ctypes.c_long, ctypes.c_int)(psl, 7)                  # SetShowCmd
        ppf = ctypes.c_void_p()
        _com_fn(psl, 0, ctypes.c_long, ctypes.POINTER(GUID),
                ctypes.POINTER(ctypes.c_void_p))(psl, ctypes.byref(IID_IPERSISTFILE),
                                                 ctypes.byref(ppf))
        if not ppf:
            log("[shortcut] 拿不到 IPersistFile")
            return ""
        try:
            hr = _com_fn(ppf, 6, ctypes.c_long, ctypes.c_wchar_p, wt.BOOL)(ppf, path, True)
            if hr != 0:
                log(f"[shortcut] 保存失败 hr={hr}")
                return ""
        finally:
            _com_fn(ppf, 2, ctypes.c_ulong)(ppf)
        return path
    finally:
        _com_fn(psl, 2, ctypes.c_ulong)(psl)


def deepseek_key(cfg: dict) -> str:
    """找 Key 的顺序：

    1. api.txt 里带备注、且备注命中 key_hint 的那把（默认找带「余额」的）——
       这是最明确的意图，优先于 config.json 的通用槽位
    2. config.json 的 deepseek.api_key
    3. 环境变量 DEEPSEEK_API_KEY
    4. api.txt 里的第一把

    api.txt 每行写成「sk-xxx——用途」即可。
    """
    hint = str(cfg.get("deepseek", {}).get("key_hint") or "余额").strip()
    labeled = find_labeled_key(hint)
    if labeled:
        return labeled
    key = (cfg.get("deepseek", {}).get("api_key") or "").strip()
    if key:
        return key
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if key:
        return key
    for path in API_KEY_FILES:
        found = read_key_file(path)
        if found:
            return found[0][0]
    return ""


def qweather_key(cfg: dict) -> str:
    """和风天气的 key：config → 环境变量 QWEATHER_KEY → api.txt 里备注带「天气」的行。"""
    qw = cfg.get("weather", {}).get("qweather", {})
    key = (qw.get("key") or "").strip()
    if key:
        return key
    key = (os.environ.get("QWEATHER_KEY") or "").strip()
    if key:
        return key
    return find_labeled_key(str(qw.get("key_hint") or "天气"), LOOSE_KEY_PATTERN)


# --------------------------------------------------------------------------
# 三、外观与版面
# --------------------------------------------------------------------------

# 版面：上面并排两张正方形卡片，下面一张通栏卡片 —— 整体接近正方形
CANVAS_W, CANVAS_H = 420, 396
SHADOW = 18
RADIUS = 34                 # 圆角，越大越圆润
RESIZE_ZONE = 26            # 右下角多少像素内算「缩放把手」
MIN_FONT_PX = 9             # 再小也不能小过 9 像素，否则小尺寸下看不清
COMPACT_BELOW = 0.85        # 有效缩放低于这个值就切「精简模式」

CARD_WEATHER = (0, 0, 204, 188)
CARD_BALANCE = (216, 0, 204, 188)
CARD_SYSTEM = (0, 200, 420, 196)
BUTTON_ORIGIN = (260, 366)

BG_TOP = (44, 46, 56)
BG_BOTTOM = (22, 23, 29)
FG = (245, 246, 250)
FG_DIM = (168, 173, 186)
FG_FAINT = (126, 131, 145)
GOOD = (120, 226, 152)
WARN = (255, 176, 88)
BAD = (248, 120, 120)
BAR_COOL = ((86, 204, 214), (120, 226, 152))
BAR_WARM = ((240, 196, 92), (250, 158, 80))
BAR_HOT = ((250, 138, 130), (226, 84, 96))

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhl.ttc",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
]
_font_cache: dict = {}


def font(size: int):
    size = max(9, int(size))
    if size in _font_cache:
        return _font_cache[size]
    for cand in FONT_CANDIDATES:
        if os.path.exists(cand):
            try:
                f = ImageFont.truetype(cand, size)
                _font_cache[size] = f
                return f
            except Exception:
                continue
    f = ImageFont.load_default()
    _font_cache[size] = f
    return f


def rounded_mask(size, radius) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1),
                                        radius=max(1, int(radius)), fill=255)
    return m


def vertical_gradient(size, top, bottom) -> Image.Image:
    grad = Image.new("RGB", (1, size[1]))
    for y in range(size[1]):
        t = y / max(1, size[1] - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return grad.resize(size, Image.BILINEAR)


def layer(base: Image.Image, draw_fn) -> Image.Image:
    """在独立图层上作画再合并。

    PIL 往 RGBA 图上直接画半透明颜色是「覆盖」不是「混合」，会画出透明窟窿，
    所以所有带 alpha 的线条和色块都必须走这条路。
    """
    tmp = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(tmp, "RGBA"))
    return Image.alpha_composite(base, tmp)


def fade(img: Image.Image, factor: float) -> Image.Image:
    out = img.copy()
    out.putalpha(img.getchannel("A").point(lambda v: max(0, min(255, int(v * factor)))))
    return out


def bar_colors(pct: float):
    if pct < 0.6:
        return BAR_COOL
    if pct < 0.85:
        return BAR_WARM
    return BAR_HOT


def aqi_color(value) -> tuple:
    """AQI 六级配色（国标）：优/良/轻度/中度/重度/严重。"""
    if value is None:
        return FG_FAINT
    if value <= 50:
        return (120, 226, 152)
    if value <= 100:
        return (216, 214, 110)
    if value <= 150:
        return (250, 176, 88)
    if value <= 200:
        return (248, 120, 120)
    return (198, 92, 190)


# --------------------------------------------------------------------------
# 小块贴图
#
# 所有图形都先画进一张小图再贴到画布上。早先是每个图形做一次「整画布合成」，
# 900×900 的尺寸下一帧要合十几个图层 —— 那就是卡顿的来源。改成贴图之后，
# 每帧只碰图形自己那一小块，开销跟画布大小基本无关了。
# --------------------------------------------------------------------------

SS = 4                      # 矢量图形超采样倍数，缩回来自带抗锯齿
SPARK_AREA = ((74, 200, 212), (92, 132, 146))     # 曲线下方渐变色
SPARK_LINE = (152, 238, 228, 235)


def blit(base, tile, x, y):
    """把小块按 alpha 正片叠底到画布上 —— 只在目标那一小块里合成，不动整张画布。"""
    x, y = int(round(x)), int(round(y))
    x, y = max(0, min(x, base.size[0] - 1)), max(0, min(y, base.size[1] - 1))
    alpha = tile.getchannel("A")
    if alpha.getextrema()[0] == 255:      # 完全不透明，直接贴，省一次合成
        base.paste(tile, (x, y))
        return base
    x0, y0 = max(0, x), max(0, y)
    x1 = min(base.size[0], x + tile.size[0])
    y1 = min(base.size[1], y + tile.size[1])
    if x1 <= x0 or y1 <= y0:
        return base
    region = base.crop((x0, y0, x1, y1))
    sub = tile.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    base.paste(Image.alpha_composite(region, sub), (x0, y0))
    return base


_TILE_CACHE = {}


def cached_tile(key, builder):
    """图标是同一批尺寸反复画的，缓存下来 —— 每帧省掉 9 次超采样+缩放。"""
    tile = _TILE_CACHE.get(key)
    if tile is None:
        tile = builder()
        if len(_TILE_CACHE) > 400:
            _TILE_CACHE.clear()
        _TILE_CACHE[key] = tile
    return tile


def tile_of(w, h):
    return Image.new("RGBA", (max(1, int(round(w))), max(1, int(round(h)))), (0, 0, 0, 0))


def supersampled(size, painter):
    """在 4 倍画布上画再缩回来：自带抗锯齿，而且完全不碰大画布。"""
    px = max(8, int(round(size * SS)))
    canvas = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    painter(ImageDraw.Draw(canvas), px)
    return canvas.resize((max(1, int(round(size))), max(1, int(round(size)))), Image.LANCZOS)


def draw_bar(img: Image.Image, x0: float, y0: float, x1: float, y1: float, pct: float) -> Image.Image:
    pct = max(0.0, min(1.0, pct))
    w, h = max(2.0, x1 - x0), max(2.0, y1 - y0)
    track = tile_of(w, h)
    ImageDraw.Draw(track).rounded_rectangle((0, 0, w - 1, h - 1), radius=h / 2,
                                            fill=(255, 255, 255, 30))
    blit(img, track, x0, y0)
    width = w * pct
    if width < 2:
        return img
    a, b = bar_colors(pct)
    fill = cached_tile(("barfill", int(width), int(h), a, b), lambda: _bar_fill(width, h, a, b))
    blit(img, fill, x0, y0)
    return img


def _bar_fill(width, height, a, b):
    """条形填充：逐像素渐变只做一次，之后按尺寸缓存复用。"""
    fill = Image.new("RGBA", (max(2, int(width)), max(2, int(height))))
    fd = ImageDraw.Draw(fill)
    for x in range(fill.size[0]):
        t = x / max(1, fill.size[0] - 1)
        fd.line((x, 0, x, fill.size[1]),
                fill=(int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t),
                      int(a[2] + (b[2] - a[2]) * t), 255))
    fill.putalpha(rounded_mask(fill.size, height / 2))
    return fill


def draw_sparkline(img: Image.Image, box_px, values, scale: float, color=None) -> Image.Image:
    """迷你折线 + 渐变面积。整块只在自己那个小矩形里合成。"""
    x0, y0, x1, y1 = [float(v) for v in box_px]
    bw, bh = int(round(x1 - x0)), int(round(y1 - y0))
    values = [float(v) for v in values]
    if len(values) == 1:            # 只有一个采样点也画成一条平线，图表不留空
        values = values * 2
    if not values or bw < 3 or bh < 3:
        return img
    n = len(values)
    pts = [(bw * i / (n - 1),
            bh - bh * max(0.0, min(100.0, float(v))) / 100.0) for i, v in enumerate(values)]
    top, bottom = color or SPARK_AREA
    pad = 3

    tile = tile_of(bw + pad * 2, bh + pad * 2)
    shifted = [(x + pad, y + pad) for x, y in pts]
    mask = Image.new("L", tile.size, 0)
    ImageDraw.Draw(mask).polygon(shifted + [(bw + pad, bh + pad), (pad, bh + pad)], fill=95)
    mask = mask.filter(ImageFilter.GaussianBlur(max(1.0, 1.2 * scale)))
    grad = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for yy in range(bh + 1):
        t = yy / max(1.0, bh)
        gd.line((0, yy + pad, tile.size[0], yy + pad),
                fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,))
    tile.paste(grad, (0, 0), mask)
    line = tile_of(*tile.size)
    ImageDraw.Draw(line).line(shifted, fill=SPARK_LINE,
                              width=max(1, int(1.6 * scale)), joint="curve")
    tile = Image.alpha_composite(tile, line)
    return blit(img, tile, x0 - pad, y0 - pad)


# --------------------------------------------------------------------------
# 四、图标（手绘矢量，不依赖 emoji 字体，任何机器都不会变豆腐块）
# --------------------------------------------------------------------------

WMO_TEXT = {
    0: "晴", 1: "基本晴", 2: "局部多云", 3: "阴",
    45: "雾", 48: "冻雾",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "阵雨", 81: "强阵雨", 82: "暴雨", 85: "阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷暴冰雹",
}


def weather_kind(code: int) -> str:
    if code in (0, 1):
        return "sun"
    if code == 2:
        return "suncloud"
    if code == 3:
        return "cloud"
    if code in (45, 48):
        return "fog"
    if code in (51, 53, 55, 56, 57):
        return "drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "thunder"
    return "cloud"


def draw_cloud(d, cx, cy, scale, color):
    w, h = 34 * scale, 15 * scale
    d.ellipse((cx - w * 0.50, cy - h * 0.42, cx + w * 0.50, cy + h * 0.58), fill=color)
    d.ellipse((cx - w * 0.30, cy - h * 0.95, cx + w * 0.10, cy + h * 0.35), fill=color)
    d.ellipse((cx - w * 0.02, cy - h * 1.25, cx + w * 0.42, cy + h * 0.35), fill=color)


def draw_weather_shapes(d, cx, cy, s, kind):
    """天气图标的矢量形状（在超采样画布上画，缩小后自带抗锯齿）。"""
    SUN = (255, 199, 92, 255)
    CLOUD = (214, 219, 230, 255)

    def sun(ox, oy, r, rays=True):
        if rays:
            for i in range(8):
                ang = i * math.pi / 4
                d.line((ox + math.cos(ang) * (r + 3 * s), oy + math.sin(ang) * (r + 3 * s),
                        ox + math.cos(ang) * (r + 8 * s), oy + math.sin(ang) * (r + 8 * s)),
                       fill=SUN, width=max(2, int(2.4 * s)))
        d.ellipse((ox - r, oy - r, ox + r, oy + r), fill=SUN)

    if kind == "sun":
        sun(cx, cy, 10 * s)
    elif kind == "suncloud":
        sun(cx + 9 * s, cy - 7 * s, 8 * s)
        draw_cloud(d, cx - 3 * s, cy + 6 * s, 0.95 * s, CLOUD)
    elif kind == "cloud":
        draw_cloud(d, cx, cy, 1.15 * s, CLOUD)
    elif kind == "fog":
        for dy, wide in ((-7, 0.9), (0, 1.2), (7, 1.0)):
            half = 18 * wide * s
            d.line((cx - half, cy + dy * s, cx + half, cy + dy * s),
                   fill=(206, 212, 224, 255), width=max(2, int(3 * s)))
    else:
        draw_cloud(d, cx - 2 * s, cy - 5 * s, 1.0 * s, CLOUD)
        if kind in ("rain", "drizzle"):
            n = 2 if kind == "drizzle" else 3
            length = (5 if kind == "drizzle" else 9) * s
            for i in range(n):
                ox, oy = cx - 10 * s + i * 10 * s, cy + 10 * s
                d.line((ox, oy, ox - 2 * s, oy + length),
                       fill=(126, 186, 255, 255), width=max(2, int(2.4 * s)))
        elif kind == "snow":
            for i in range(3):
                ox, oy, r = cx - 10 * s + i * 10 * s, cy + 12 * s, 2.1 * s
                d.ellipse((ox - r, oy - r, ox + r, oy + r), fill=(226, 238, 255, 255))
        else:
            d.polygon([(cx - 2 * s, cy + 6 * s), (cx + 6 * s, cy + 6 * s), (cx + 1 * s, cy + 14 * s),
                       (cx + 6 * s, cy + 14 * s), (cx - 6 * s, cy + 26 * s), (cx - 1 * s, cy + 16 * s),
                       (cx - 6 * s, cy + 16 * s)], fill=(255, 205, 92, 255))


def draw_weather_icon(base: Image.Image, cx, cy, size, kind) -> Image.Image:
    if not kind:
        return base
    tile = cached_tile(("weather", round(size, 1), kind), lambda: supersampled(
        size, lambda d, px: draw_weather_shapes(d, px / 2, px / 2, px / 44.0, kind)))
    return blit(base, tile, cx - size / 2, cy - size / 2)


def draw_mini_glyph(base: Image.Image, cx, cy, size, name, alpha=140) -> Image.Image:
    """信息行里的小图标（水滴 / 风 / 温度计）——用图标替掉「湿度」「风」这些字。"""
    col = (255, 255, 255, alpha)

    def paint(d, px):
        s = px / 15.0
        ox = oy = px / 2
        if name == "drop":
            d.ellipse((ox - 5 * s, oy - 1.5 * s, ox + 5 * s, oy + 5.5 * s), fill=col)
            d.polygon([(ox, oy - 6.5 * s), (ox + 4.6 * s, oy + 1 * s),
                       (ox - 4.6 * s, oy + 1 * s)], fill=col)
        elif name == "wind":
            for dy, length in ((-3.6, 1.0), (0.0, 1.3), (3.6, 0.75)):
                d.line((ox - 6 * s, oy + dy * s, ox - 6 * s + 12 * s * length, oy + dy * s),
                       fill=col, width=max(2, int(1.5 * s)))
        elif name == "thermo":
            d.rounded_rectangle((ox - 1.7 * s, oy - 6.5 * s, ox + 1.7 * s, oy + 1.5 * s),
                                radius=1.7 * s, outline=col, width=max(1, int(1.3 * s)))
            d.ellipse((ox - 3.2 * s, oy - 0.5 * s, ox + 3.2 * s, oy + 6 * s), fill=col)
    tile = cached_tile(("mini", round(size, 1), name, alpha), lambda: supersampled(size, paint))
    return blit(base, tile, cx - size / 2, cy - size / 2)


def draw_icon_glyph(base: Image.Image, cx, cy, size, name, alpha=210) -> Image.Image:
    col = (255, 255, 255, alpha)

    def paint(d, px):
        s = px / 22.0
        ox = oy = px / 2
        wid = max(2, int(1.9 * s))
        if name == "refresh":
            r = 7 * s
            d.arc((ox - r, oy - r, ox + r, oy + r), start=40, end=330, fill=col, width=wid)
            d.polygon([(ox + r - 1 * s, oy - 7.5 * s), (ox + r + 4.5 * s, oy - 4 * s),
                       (ox + r - 3 * s, oy - 1 * s)], fill=col)
        elif name == "opacity":
            r = 7.5 * s
            d.ellipse((ox - r, oy - r, ox + r, oy + r), outline=col, width=wid)
            d.pieslice((ox - r, oy - r, ox + r, oy + r), start=90, end=270, fill=col)
        elif name == "desktop":
            w, h = 8 * s, 6.5 * s
            d.rounded_rectangle((ox - w, oy - h, ox + w, oy + h), radius=1.6 * s,
                                outline=col, width=wid)
            d.line((ox - w * 0.45, oy + h + 2.6 * s, ox + w * 0.45, oy + h + 2.6 * s),
                   fill=col, width=wid)
        elif name == "clickthrough":
            r = 6.5 * s
            d.ellipse((ox - r, oy - r, ox + r, oy + r), outline=col, width=wid)
            d.line((ox - r * 0.9, oy + r * 0.9, ox + r * 0.9, oy - r * 0.9), fill=col, width=wid)
        elif name == "close":
            r = 5.5 * s
            d.line((ox - r, oy - r, ox + r, oy + r), fill=col, width=wid)
            d.line((ox - r, oy + r, ox + r, oy - r), fill=col, width=wid)
    tile = cached_tile(("glyph", round(size, 1), name, alpha), lambda: supersampled(size, paint))
    return blit(base, tile, cx - size / 2, cy - size / 2)


# --------------------------------------------------------------------------
# 托盘图标（Shell_NotifyIcon）
#
# 这个不只是好看：鼠标穿透打开后窗口不吃任何点击，托盘菜单就成了唯一
# 一定能用到的出口 —— 从托盘里「退出」或者「恢复正常」永远有效。
# --------------------------------------------------------------------------

def tray_icon_image(size: int = 32) -> Image.Image:
    """自己画托盘图标，省得依赖外部 .ico 文件。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, round(size / 16))
    d.rounded_rectangle((pad, pad, size - pad - 1, size - pad - 1),
                        radius=max(4, round(size / 4)), fill=(30, 32, 42, 255))
    left, right = pad + size * 0.16, size - pad - size * 0.16
    top, bottom = pad + size * 0.22, size - pad - size * 0.22
    values = [0.35, 0.62, 0.42, 0.78, 0.52, 0.86]
    pts = [(left + (right - left) * i / (len(values) - 1),
            bottom - (bottom - top) * v) for i, v in enumerate(values)]
    d.line(pts, fill=(120, 226, 152, 255), width=max(2, round(size / 10)), joint="curve")
    r = max(2, round(size / 9))
    d.ellipse((pts[-1][0] - r, pts[-1][1] - r, pts[-1][0] + r, pts[-1][1] + r),
              fill=(255, 199, 92, 255))
    return img


def make_hicon(img: Image.Image):
    """把 PIL 图像变成 HICON：32 位 BGRA 彩色位图 + 全零掩码。"""
    w, h = img.size
    bgra = img.convert("RGBA").tobytes("raw", "BGRA")
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = DIB_RGB_COLORS

    screen_dc = user32.GetDC(None)
    bits = ctypes.c_void_p()
    hcolor = gdi32.CreateDIBSection(screen_dc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                    ctypes.byref(bits), None, 0)
    if not hcolor:
        user32.ReleaseDC(None, screen_dc)
        return None
    ctypes.memmove(bits, bgra, len(bgra))
    row_bytes = ((w + 15) // 16) * 2          # 单色位图每行按 16 位对齐
    hmask = gdi32.CreateBitmap(w, h, 1, 1, ctypes.create_string_buffer(row_bytes * h))
    info = ICONINFO(True, 0, 0, hmask, hcolor)
    hicon = user32.CreateIconIndirect(ctypes.byref(info))
    gdi32.DeleteObject(hmask)
    gdi32.DeleteObject(hcolor)
    user32.ReleaseDC(None, screen_dc)
    return hicon


# --------------------------------------------------------------------------
# 五、系统资源采样（纯 ctypes，零依赖）
# --------------------------------------------------------------------------

def _ft_value(ft: wt.FILETIME) -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


class SysStats:
    """CPU / 内存 / 磁盘。CPU 用增量法：两次采样之间的差值。"""

    def __init__(self, disk: str = "C:", history: int = 60):
        self.disk = (disk or "C:").rstrip("\\") + "\\"
        points = max(10, int(history))
        self.cpu_history = deque(maxlen=points)
        self.mem_history = deque(maxlen=points)
        self.disk_history = deque(maxlen=points)
        self._prev = None
        self.cpu = 0.0
        self.mem_pct = 0.0
        self.mem_used_gb = 0.0
        self.mem_total_gb = 0.0
        self.disk_pct = 0.0
        self.disk_used_gb = 0.0
        self.disk_total_gb = 0.0

    def sample(self) -> None:
        self._sample_cpu()
        self._sample_memory()
        self._sample_disk()

    def _sample_cpu(self) -> None:
        idle, kernel, user = wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
        if not kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return
        cur = (_ft_value(idle), _ft_value(kernel) + _ft_value(user))
        if self._prev is not None:
            d_idle = cur[0] - self._prev[0]
            d_total = cur[1] - self._prev[1]
            if d_total > 0:
                self.cpu = max(0.0, min(100.0, 100.0 * (1.0 - d_idle / d_total)))
                self.cpu_history.append(self.cpu)
                if len(self.cpu_history) == 1:
                    self.cpu_history.appendleft(self.cpu)
        self._prev = cur

    def _sample_memory(self) -> None:
        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return
        total, avail = float(st.ullTotalPhys), float(st.ullAvailPhys)
        if total > 0:
            self.mem_pct = 100.0 * (total - avail) / total
            self.mem_used_gb = (total - avail) / (1024 ** 3)
            self.mem_total_gb = total / (1024 ** 3)
            self.mem_history.append(self.mem_pct)
            if len(self.mem_history) == 1:        # 先垫一个点，曲线不用等一分钟才出现
                self.mem_history.appendleft(self.mem_pct)

    def _sample_disk(self) -> None:
        avail_user, total, free = (ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong())
        if not kernel32.GetDiskFreeSpaceExW(self.disk, ctypes.byref(avail_user),
                                            ctypes.byref(total), ctypes.byref(free)):
            return
        t, f = float(total.value), float(free.value)
        if t > 0:
            self.disk_pct = 100.0 * (t - f) / t
            self.disk_used_gb = (t - f) / (1024 ** 3)
            self.disk_total_gb = t / (1024 ** 3)
            self.disk_history.append(self.disk_pct)
            if len(self.disk_history) == 1:
                self.disk_history.appendleft(self.disk_pct)

    def snapshot(self) -> dict:
        return {
            "cpu": self.cpu,
            "cpu_history": list(self.cpu_history),
            "mem_history": list(self.mem_history),
            "disk_history": list(self.disk_history),
            "mem_pct": self.mem_pct,
            "mem_used_gb": self.mem_used_gb,
            "mem_total_gb": self.mem_total_gb,
            "disk_pct": self.disk_pct,
            "disk_used_gb": self.disk_used_gb,
            "disk_total_gb": self.disk_total_gb,
            "disk_name": self.disk.rstrip("\\"),
        }


# --------------------------------------------------------------------------
# 六、网络数据（天气 + DeepSeek 余额）
# --------------------------------------------------------------------------

def _get_json(url: str, headers: dict | None = None, timeout: float = 8.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "lumen-widget/2.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def net_hint(exc: Exception) -> str:
    """把常见的网络错误翻译成一句人话，省得对着 WinError 发懵。"""
    code = getattr(exc, "winerror", None)
    reason = getattr(exc, "reason", None)      # urllib 会把 OSError 塞在 reason 里
    if code is None:
        code = getattr(reason, "winerror", None)
    if code is None:
        for attr in ("errno", "args"):
            value = getattr(reason, attr, None)
            if isinstance(value, int):
                code = value
                break
    if code == 10013:
        return "（本进程被限制了网络访问权限，通常是运行环境/防火墙策略导致）"
    if code in (10061, 10051, 10050):
        return "（连接被拒绝，先看代理或防火墙）"
    if code in (11001, 11004):
        return "（域名解析失败，检查 DNS）"
    if isinstance(exc, TimeoutError):
        return "（连接超时）"
    return ""


# --------------------------------------------------------------------------
# 天气源（多源可切换）
#
#   cma        中国天气网，数据来自中国气象局。免密钥、字段全，但接口不是公开文档化的，
#              所以做了三个端点互相兜底，任何一个通了就行。
#   qweather   和风天气。要 key（免费额度够个人用），数据稳定、有官方文档，
#              国内做天气基本都用它；key 可以写在 config、环境变量或 api.txt。
#   open-meteo 兜底用的国外开放源，免密钥。
#
# 三个源解析出来的字段统一成同一套键，render() 不关心数据从哪来。
# --------------------------------------------------------------------------

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) lumen-widget/2.0"
CMA_HEADERS = {
    "User-Agent": UA,
    "Referer": "http://www.weather.com.cn/",
    "Accept": "*/*",
}

QW_CODE_HINT = {
    "204": "该城市没有数据",
    "400": "请求参数有误",
    "401": "Key 认证失败",
    "402": "超过访问次数或余额不足",
    "403": "没有权限访问该接口",
    "404": "查询的城市不存在",
    "429": "请求过于频繁",
}

TEXT_KIND_RULES = [
    (("雷",), "thunder"),
    (("雪", "霰", "冰粒", "冻雨"), "snow"),
    (("雨",), "rain"),
    (("雾", "霾", "浮尘", "扬沙", "沙尘"), "fog"),
    (("阴",), "cloud"),
    (("多云",), "suncloud"),
    (("晴",), "sun"),
]


def _decode(raw: bytes) -> str:
    """中国天气网有的端点回 GBK，有的回 UTF-8，两个都试。"""
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _http_bytes(url: str, headers: dict | None = None, timeout: float = 8.0) -> bytes:
    req = urllib.request.Request(url, headers={**CMA_HEADERS, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _get_json_any(url: str, headers: dict | None = None, timeout: float = 8.0) -> dict:
    return json.loads(_decode(_http_bytes(url, headers, timeout)))


def _extract_json(text: str) -> dict:
    """中国天气网的 d1 系列返回的是 'var dataSK = {...};' 这种 JS 赋值。"""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("响应里没有 JSON")
    return json.loads(text[start:end + 1])


def _num(value):
    if value is None:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _int(value):
    number = _num(value)
    return int(round(number)) if number is not None else None


def _wind_ms(value):
    """把 '7km/h' / '2' 这类写法统一成 m/s。"""
    number = _num(value)
    if number is None:
        return None
    text = str(value).lower()
    if "km/h" in text or "kmh" in text:
        return round(number / 3.6, 1)
    if "m/s" in text:
        return round(number, 1)
    return None


def kind_from_text(text) -> str | None:
    text = str(text or "")
    for keys, kind in TEXT_KIND_RULES:
        if any(k in text for k in keys):
            return kind
    return None


def _clean(payload: dict) -> dict:
    """统一字段：把空字符串和 None 都去掉，方便上层「谁有就用谁」。"""
    out = {}
    for key, value in payload.items():
        if value is None or value == "":
            continue
        out[key] = value
    return out


# ---- 各源的解析（纯函数，方便单独测） ------------------------------------

def parse_cma_sk2d(data: dict) -> dict:
    return _clean({
        "temp": _int(data.get("temp")),
        "humidity": _int(str(data.get("SD") or data.get("sd") or "").rstrip("%")),
        "wind": _wind_ms(data.get("wse")),
        "wind_dir": (data.get("WD") or "").strip(),
        "desc": (data.get("weather") or "").strip(),
        "kind": kind_from_text(data.get("weather")),
        "temp_max": _int(data.get("tem1") or data.get("tem2")),
        "temp_min": _int(data.get("tem2") or data.get("tem1")),
        "aqi": _int(data.get("aqi")),
        "city": (data.get("cityname") or "").strip(),
        "obs_time": (data.get("time") or "").strip(),
    })


def parse_cma_sk(data: dict) -> dict:
    info = data.get("weatherinfo") or data
    return _clean({
        "temp": _int(info.get("temp")),
        "humidity": _int(str(info.get("SD") or "").rstrip("%")),
        "wind_dir": (info.get("WD") or "").strip(),
        "city": (info.get("city") or "").strip(),
        "obs_time": (info.get("time") or "").strip(),
    })


def parse_cma_cityinfo(data: dict) -> dict:
    info = data.get("weatherinfo") or data
    t1, t2 = _int(info.get("temp1")), _int(info.get("temp2"))
    lo, hi = (min(t1, t2), max(t1, t2)) if (t1 is not None and t2 is not None) else (None, None)
    desc = (info.get("weather") or "").strip()
    return _clean({
        "temp_max": hi,
        "temp_min": lo,
        "desc": desc,
        "kind": kind_from_text(desc),
        "city": (info.get("city") or "").strip(),
    })


def parse_qweather_now(data: dict) -> dict:
    now = data.get("now") or {}
    desc = (now.get("text") or "").strip()
    wind = _num(now.get("windSpeed"))
    return _clean({
        "temp": _int(now.get("temp")),
        "feels": _int(now.get("feelsLike")),
        "humidity": _int(now.get("humidity")),
        "wind": round(wind / 3.6, 1) if wind is not None else None,   # 和风给的是 km/h
        "wind_dir": (now.get("windDir") or "").strip(),
        "desc": desc,
        "kind": kind_from_text(desc),
        "obs_time": (now.get("obsTime") or "")[11:16],
    })


def parse_qweather_daily(data: dict) -> dict:
    days = data.get("daily") or []
    if not days:
        return {}
    today = days[0]
    uv = _int(today.get("uvIndex"))
    return _clean({
        "temp_max": _int(today.get("tempMax")),
        "temp_min": _int(today.get("tempMin")),
        "uv": uv,
        "desc_day": (today.get("textDay") or "").strip(),
    })


def parse_openmeteo(data: dict) -> dict:
    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    code = _int(cur.get("weather_code"))
    return _clean({
        "temp": _int(cur.get("temperature_2m")),
        "feels": _int(cur.get("apparent_temperature")),
        "humidity": _int(cur.get("relative_humidity_2m")),
        "wind": _num(cur.get("wind_speed_10m")),
        "code": code,
        "desc": WMO_TEXT.get(code, "未知") if code is not None else None,
        "kind": weather_kind(code) if code is not None else None,
        "temp_max": _int((daily.get("temperature_2m_max") or [None])[0]),
        "temp_min": _int((daily.get("temperature_2m_min") or [None])[0]),
        "rain_prob": _int((daily.get("precipitation_probability_max") or [None])[0]),
    })


# ---- 各源的取数 ----------------------------------------------------------

def fetch_cma(cfg: dict) -> dict:
    """中国天气网（中国气象局数据）：三个端点互补，能拿到多少算多少。"""
    city_id = str(cfg.get("weather", {}).get("cma_city_id") or "101210101").strip()
    stamp = int(time.time() * 1000)
    out, errors = {}, []

    try:
        raw = _http_bytes(f"http://d1.weather.com.cn/sk_2d/{city_id}.html?_={stamp}")
        out.update(parse_cma_sk2d(_extract_json(_decode(raw))))
    except Exception as exc:
        errors.append(f"sk_2d: {exc}")

    if out.get("temp") is None or not out.get("desc"):
        try:
            raw = _http_bytes(f"http://www.weather.com.cn/data/sk/{city_id}.html")
            out.update(parse_cma_sk(_extract_json(_decode(raw))))
        except Exception as exc:
            errors.append(f"sk: {exc}")

    if out.get("temp_max") is None or out.get("temp_min") is None:
        try:
            raw = _http_bytes(f"http://www.weather.com.cn/data/cityinfo/{city_id}.html")
            for key, value in parse_cma_cityinfo(_extract_json(_decode(raw))).items():
                out.setdefault(key, value)
        except Exception as exc:
            errors.append(f"cityinfo: {exc}")

    if out.get("temp") is None:
        raise RuntimeError("三个接口都没取到：" + "；".join(errors))
    out["source"] = "中国气象局"
    return out


def fetch_qweather(cfg: dict) -> dict:
    qw = cfg.get("weather", {}).get("qweather", {})
    key = qweather_key(cfg)
    if not key:
        raise RuntimeError("没有配置和风天气 Key")
    host = (qw.get("api_host") or "devapi.qweather.com").strip().strip("/")
    loc = str(cfg.get("weather", {}).get("cma_city_id") or "101210101").strip()
    base = f"https://{host}/v7/weather"

    data = _get_json_any(f"{base}/now?location={loc}&key={key}&lang=zh")
    code = str(data.get("code", ""))
    if code != "200":
        raise RuntimeError(f"和风返回 code={code} {QW_CODE_HINT.get(code, '')}".strip())
    out = parse_qweather_now(data)

    try:
        daily = _get_json_any(f"{base}/3d?location={loc}&key={key}&lang=zh")
        if str(daily.get("code", "")) == "200":
            for key_name, value in parse_qweather_daily(daily).items():
                out.setdefault(key_name, value)
    except Exception as exc:
        log(f"[weather] 和风 3 日预报没取到: {exc}")

    out["source"] = "和风天气"
    return out


def fetch_openmeteo(cfg: dict) -> dict:
    url = ("https://api.open-meteo.com/v1/forecast"
           f"?latitude={cfg['latitude']}&longitude={cfg['longitude']}"
           "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
           "weather_code,wind_speed_10m"
           "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
           "&forecast_days=1"
           f"&timezone={urllib.parse.quote(cfg.get('timezone', 'Asia/Shanghai'))}")
    out = parse_openmeteo(_get_json_any(url))
    if out.get("temp") is None:
        raise RuntimeError("Open-Meteo 没返回温度")
    out["source"] = "Open-Meteo"
    return out


def weather_providers(cfg: dict):
    """按配置给出要尝试的源（顺序即优先级）。"""
    wanted = str(cfg.get("weather", {}).get("source") or "auto").strip().lower()
    table = {
        "cma": ("中国气象局", fetch_cma),
        "qweather": ("和风天气", fetch_qweather),
        "open-meteo": ("Open-Meteo", fetch_openmeteo),
        "openmeteo": ("Open-Meteo", fetch_openmeteo),
    }
    if wanted in table:
        return [table[wanted]]
    return [table["cma"], table["qweather"], table["open-meteo"]]


def _first(seq):
    """Open-Meteo 的 daily 字段是数组，取今天那一个。"""
    if not seq:
        return None
    try:
        return int(round(float(seq[0])))
    except (TypeError, ValueError):
        return None


class DataHub:
    """后台线程取数，UI 线程只读快照 —— 网络再慢也卡不住界面。"""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._next_weather = 0.0
        self._next_balance = 0.0
        self.state = {
            "city": cfg.get("city", "杭州"),
            "temp": None, "feels": None, "humidity": None, "wind": None,
            "code": None, "desc": "读取中…", "offline": False, "updated": None,
            "kind": None, "aqi": None, "weather_source": None,
            "temp_max": None, "temp_min": None, "rain_prob": None,
            "balance_ok": None, "balance_total": None, "balance_granted": None,
            "balance_topped": None, "balance_currency": cfg["deepseek"].get("currency", "CNY"),
            "balance_note": "读取中…", "balance_delta": None,
            "balance_updated": None, "balance_available": None,
            "balance_interval": int(float(cfg.get("deepseek", {}).get("refresh_minutes", 5) or 5)),
        }

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.state)

    def update(self, **kw) -> None:
        with self.lock:
            self.state.update(kw)

    def start(self, on_change) -> None:
        threading.Thread(target=self._loop, args=(on_change,), daemon=True).start()

    def refresh_now(self) -> None:
        self._next_weather = 0.0
        self._next_balance = 0.0

    def _loop(self, on_change) -> None:
        while not self._stop.is_set():
            now = time.time()
            if now >= self._next_weather:
                self._fetch_weather()
                minutes = float(self.cfg.get("weather_refresh_minutes", 10) or 10)
                self._next_weather = time.time() + max(1.0, minutes) * 60
            if now >= self._next_balance:
                self._fetch_balance()
                minutes = float(self.cfg.get("deepseek", {}).get("refresh_minutes", 5) or 5)
                self._next_balance = time.time() + max(1.0, minutes) * 60
            on_change()
            self._stop.wait(20)

    # -- 天气 -------------------------------------------------------------
    def _fetch_weather(self) -> None:
        """按配置的源依次尝试，谁先成功用谁；全挂了才退到示例数据。"""
        for name, fetcher in weather_providers(self.cfg):
            try:
                data = fetcher(self.cfg)
            except Exception as exc:
                log(f"[weather] {name} 失败: {exc} {net_hint(exc)}")
                continue
            if data.get("temp") is None:
                log(f"[weather] {name} 返回里没有温度，换下一个源")
                continue
            data["offline"] = False
            data["updated"] = datetime.now().strftime("%H:%M")
            self.update(**data)
            log(f"[weather] 成功：{data.get('source')} · {data.get('temp')}° "
                f"{data.get('desc', '')}".strip())
            return
        log("[weather] 所有源都失败了")
        if self.snapshot().get("temp") is None:
            self.update(**demo_weather())
        self.update(offline=True, updated=datetime.now().strftime("%H:%M"))

    # -- DeepSeek 余额 ----------------------------------------------------
    def _fetch_balance(self) -> None:
        key = deepseek_key(self.cfg)
        if not key:
            self.update(balance_ok=False, balance_note="未配置 API Key", balance_available=None)
            return
        try:
            data = _get_json("https://api.deepseek.com/user/balance",
                             {"Authorization": f"Bearer {key}", "Accept": "application/json"})
        except urllib.error.HTTPError as exc:
            note = "Key 无效或已过期" if exc.code in (401, 403) else f"HTTP {exc.code}"
            self.update(balance_ok=False, balance_note=note)
            log(f"[balance] 请求失败: HTTP {exc.code}（{note}）")
            return
        except Exception as exc:
            self.update(balance_ok=False, balance_note="网络不可用")
            log(f"[balance] 请求失败: {exc} {net_hint(exc)}")
            return

        infos = data.get("balance_infos") or []
        want = (self.cfg.get("deepseek", {}).get("currency") or "CNY").upper()
        info = next((i for i in infos if str(i.get("currency", "")).upper() == want), None)
        if info is None and infos:
            info = infos[0]
        if not info:
            self.update(balance_ok=False, balance_note="未返回余额信息")
            return

        total = float(info.get("total_balance", 0) or 0)
        self.update(balance_ok=True, balance_available=bool(data.get("is_available", True)),
                    balance_total=total,
                    balance_granted=float(info.get("granted_balance", 0) or 0),
                    balance_topped=float(info.get("topped_up_balance", 0) or 0),
                    balance_currency=str(info.get("currency", want)),
                    balance_delta=self._record_balance(total),
                    balance_note="", balance_updated=datetime.now().strftime("%H:%M"))

    def _record_balance(self, total: float):
        """把余额随时间存下来，才能算出「近 24 小时花了多少」。"""
        now = time.time()
        hist = []
        try:
            if os.path.exists(BALANCE_HISTORY):
                with open(BALANCE_HISTORY, "r", encoding="utf-8") as f:
                    hist = json.load(f)
        except Exception:
            hist = []
        hist = [h for h in hist if isinstance(h, list) and len(h) == 2 and h[0] > now - 7 * 86400]
        hist.append([now, total])
        try:
            with open(BALANCE_HISTORY, "w", encoding="utf-8") as f:
                json.dump(hist[-2000:], f)
        except Exception:
            pass
        base = None
        for ts, val in hist:
            if ts <= now - 3600:        # 至少一小时前的样本才当基准
                base = val
            else:
                break
        return None if base is None else round(base - total, 4)   # 正数 = 已消耗


# --------------------------------------------------------------------------
# 七、绘制
# --------------------------------------------------------------------------

def human_money(value, currency: str = "CNY") -> str:
    symbol = "¥" if str(currency).upper() in ("CNY", "RMB") else "$"
    if value is None:
        return f"{symbol} --"
    if abs(value) >= 1000:
        return f"{symbol}{value:,.0f}"
    return f"{symbol}{value:,.2f}"


def gb(value: float) -> str:
    """容量显示：整数就不带小数点，能省一个字是一个字。"""
    if value >= 100:
        text = f"{value:.0f}"
    elif value >= 10:
        text = f"{value:.1f}"
    else:
        text = f"{value:.2f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


_CHROME_CACHE = {}


def chrome_image(size, scale: float, cards, fast: bool = False):
    """投影 + 卡片底 + 顶部高光是静态的，缓存起来每帧只复制一份。

    早先每帧都在重建：30 个大圆角矩形画投影 + 3 张逐像素渐变卡片，
    大尺寸下光是这一步就要几十毫秒 —— 卡顿感主要来自这里。
    """
    key = (size, round(scale, 3), fast)
    cached = _CHROME_CACHE.get(key)
    if cached is None:
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        pad = int(SHADOW * scale)
        # 拖动缩放时用简版投影：正式那版是 10 层圆角矩形，重建一次要几十毫秒，
        # 每换一个尺寸都重建就等于每帧卡一下。松手后再补上完整效果。
        layers = (3, 6, 9) if fast else range(10, 0, -1)

        def P(x, y):
            return (pad + x * scale, pad + y * scale)

        def shadow_fn(d):
            for cx, cy, cw, ch in cards:
                for i in layers:
                    grow = int(i * 2.4 * scale)
                    d.rounded_rectangle((*P(cx - grow, cy - grow + 5),
                                         *P(cx + cw + grow, cy + ch + grow + 5)),
                                        radius=int(RADIUS * scale) + grow,
                                        fill=(0, 0, 0, max(3, int(9 - i * 0.6))))
        img = layer(img, shadow_fn)
        for cx, cy, cw, ch in cards:
            card = vertical_gradient((int(cw * scale), int(ch * scale)),
                                     BG_TOP, BG_BOTTOM).convert("RGBA")
            card.putalpha(rounded_mask(card.size, RADIUS * scale))
            img.paste(card, (int(pad + cx * scale), int(pad + cy * scale)), card)
        if not fast:
            img = layer(img, lambda d: [
                d.line((*P(cx + 14, cy + 1), *P(cx + cw - 14, cy + 1)),
                       fill=(255, 255, 255, 24), width=max(1, int(scale)))
                for cx, cy, cw, ch in cards])
        if len(_CHROME_CACHE) > 4:
            _CHROME_CACHE.clear()
        _CHROME_CACHE[key] = img
        cached = img
    return cached.copy()


def render(state: dict, scale: float, opacity: float, hover, clickthrough: bool,
           desktop_layer: bool, hint, fast: bool = False) -> tuple:
    pad = int(SHADOW * scale)
    w = int(CANVAS_W * scale) + pad * 2
    h = int(CANVAS_H * scale) + pad * 2
    cards = (CARD_WEATHER, CARD_BALANCE, CARD_SYSTEM)

    def P(x, y):
        return (pad + x * scale, pad + y * scale)

    def f(size):
        return font(size * scale)

    # 缩得太小就把次要信息收起来，保证「一眼看到关键数字」
    compact = scale < COMPACT_BELOW

    # ---- 静态底图（投影 + 卡片 + 高光）走缓存，每帧只复制一份
    img = chrome_image((w, h), scale, cards, fast)
    dl = ImageDraw.Draw(img, "RGBA")

    # ================= 卡片 1：天气（左上）=================
    wx, wy = CARD_WEATHER[0], CARD_WEATHER[1]
    dl.text(P(wx + 18, wy + 30), state.get("city", "杭州"), font=f(15), fill=FG, anchor="lm")
    dl.text(P(wx + 186, wy + 30), datetime.now().strftime("%H:%M"), font=f(12),
            fill=FG_DIM, anchor="rm")
    dl.text(P(wx + 18, wy + (94 if compact else 84)),
            "—" if state.get("temp") is None else f"{state['temp']}°",
            font=f(48 if compact else 42), fill=FG, anchor="lm")
    kind = state.get("kind")
    if not kind and state.get("code") is not None:
        kind = weather_kind(int(state["code"]))
    if kind:
        img = draw_weather_icon(img, *P(wx + 150, wy + (88 if compact else 80)),
                                (46 if compact else 40) * scale, kind)
        dl = ImageDraw.Draw(img, "RGBA")
    dl.text(P(wx + 18, wy + (140 if compact else 122)), state.get("desc", ""),
            font=f(14 if compact else 13), fill=FG, anchor="lm")
    low_line = wy + (170 if compact else 148)
    if state.get("temp_max") is not None and state.get("temp_min") is not None:
        dl.text(P(wx + 18, low_line), f"{state['temp_max']}° / {state['temp_min']}°",
                font=f(12 if compact else 11), fill=FG_DIM, anchor="lm")
    # 空气质量 / 降水概率两种尺寸都显示（这是健康相关的关键信息）
    if state.get("aqi") is not None:
        dl.text(P(wx + 186, low_line), f"AQI {state['aqi']}", font=f(11 if compact else 10),
                fill=aqi_color(state["aqi"]), anchor="rm")
    elif state.get("rain_prob") is not None:
        dl.text(P(wx + 186, low_line), f"雨 {state['rain_prob']}%", font=f(11 if compact else 10),
                fill=FG_FAINT, anchor="rm")
    if not compact:
        def metric(x, glyph_name, text):
            """小图标 + 数字，比写「湿度 93%」省一半字。"""
            nonlocal img, dl
            img = draw_mini_glyph(img, *P(wx + x, wy + 170), 15 * scale, glyph_name)
            dl = ImageDraw.Draw(img, "RGBA")
            dl.text(P(wx + x + 11, wy + 170), text, font=f(10), fill=FG_FAINT, anchor="lm")
            return x + 11 + dl.textlength(text, font=f(10)) / scale + 11

        if state.get("offline"):
            dl.text(P(wx + 18, wy + 170), "离线 · 示例", font=f(10), fill=WARN, anchor="lm")
        else:
            x = 18.0
            if state.get("humidity"):
                x = metric(x, "drop", f"{state['humidity']}%")
            if state.get("wind") is not None:
                x = metric(x, "wind", f"{state['wind']}")
            if state.get("feels") is not None:
                metric(x, "thermo", f"{state['feels']}°")

    # ================= 卡片 2：DeepSeek 余额 =================
    bx, by = CARD_BALANCE[0], CARD_BALANCE[1]
    currency = state.get("balance_currency") or "CNY"
    dl.text(P(bx + 18, by + 30), "DeepSeek", font=f(12), fill=FG, anchor="lm")
    if state.get("balance_ok") is None:
        status, status_color = "读取中", FG_FAINT
    elif not state.get("balance_ok"):
        status, status_color = "不可用", BAD
    elif state.get("balance_available") is False:
        status, status_color = "余额不足", BAD
    else:
        status, status_color = "可用", GOOD
    dl.text(P(bx + 186, by + 30), status, font=f(9), fill=status_color, anchor="rm")

    if state.get("balance_ok"):
        dl.text(P(bx + 18, by + (98 if compact else 84)),
                human_money(state.get("balance_total"), currency),
                font=f(30 if compact else 26), fill=FG, anchor="lm")
        delta = state.get("balance_delta")
        if delta is None:
            delta_txt, delta_color = "24h 采样中…", FG_FAINT
        elif delta > 0.0001:
            delta_txt, delta_color = f"24h -{human_money(delta, currency)}", WARN
        else:
            delta_txt, delta_color = "24h 无变化", GOOD
        if compact:
            dl.text(P(bx + 18, by + 142), delta_txt, font=f(10), fill=delta_color, anchor="lm")
        else:
            dl.text(P(bx + 18, by + 112),
                    f"赠 {human_money(state.get('balance_granted'), currency)}"
                    f" · 充 {human_money(state.get('balance_topped'), currency)}",
                    font=f(9), fill=FG_FAINT, anchor="lm")
            dl.text(P(bx + 18, by + 140), delta_txt, font=f(9), fill=delta_color, anchor="lm")
            dl.text(P(bx + 186, by + 140), state.get("balance_updated") or "—", font=f(8),
                    fill=(100, 106, 120), anchor="rm")
    else:
        dl.text(P(bx + 18, by + (98 if compact else 88)), "未接入",
                font=f(22 if compact else 18), fill=FG_FAINT, anchor="lm")
        if not compact:
            dl.text(P(bx + 18, by + 116), state.get("balance_note") or "等待数据",
                    font=f(10), fill=WARN, anchor="lm")
            dl.text(P(bx + 18, by + 140), "填 config.json", font=f(8),
                    fill=(100, 106, 120), anchor="lm")

    # ================= 卡片 3：系统资源 =================
    cx0, cy0 = CARD_SYSTEM[0], CARD_SYSTEM[1]
    columns = [
        ("CPU", "", f"{state.get('cpu', 0):.0f}%", state.get("cpu", 0),
         state.get("cpu_history") or []),
        ("内存", f"{gb(state.get('mem_used_gb', 0))}/{gb(state.get('mem_total_gb', 0))}G",
         f"{state.get('mem_pct', 0):.0f}%", state.get("mem_pct", 0),
         state.get("mem_history") or []),
        (f"磁盘 {state.get('disk_name', 'C:')}",
         f"{gb(state.get('disk_used_gb', 0))}/{gb(state.get('disk_total_gb', 0))}G",
         f"{state.get('disk_pct', 0):.0f}%", state.get("disk_pct", 0),
         state.get("disk_history") or []),
    ]
    for index, (label, extra, pct_txt, pct, history) in enumerate(columns):
        col = cx0 + 16 + index * 134
        center = col + 60
        # 文字全部居中：标签、大号百分比、下面的绝对值
        dl.text(P(center, cy0 + 32), label, font=f(11), fill=FG_DIM, anchor="mm")
        dl.text(P(center, cy0 + 64), pct_txt, font=f(24), fill=FG, anchor="mm")
        img = draw_bar(img, *P(col, cy0 + 86), *P(col + 120, cy0 + 92), pct / 100.0)
        dl = ImageDraw.Draw(img, "RGBA")
        # 折线图任何尺寸都画（精简模式也保留），这是「一直显示」的关键
        # 精简模式下没有下面那行绝对值，曲线就占大一点，小尺寸也看得清
        top, bottom = (cy0 + 96, cy0 + 132) if compact else (cy0 + 98, cy0 + 126)
        img = draw_sparkline(img, (*P(col, top), *P(col + 120, bottom)), history, scale)
        dl = ImageDraw.Draw(img, "RGBA")
        if not compact and extra:
            dl.text(P(center, cy0 + 142), extra, font=f(9),
                    fill=(104, 110, 124), anchor="mm")

    # 左下角：实况时间 + 数据来源（有提示时让位给提示）
    obs = state.get("obs_time")
    stamp = f"实况 {obs}" if obs else f"更新 {state.get('updated') or '—'}"
    source = state.get("weather_source") or state.get("source") or ""
    dl.text(P(cx0 + 18, cy0 + 178), hint or (f"{stamp} · {source}" if source else stamp),
            font=f(9), fill=WARN if hint else FG_FAINT, anchor="lm")

    # 右下角缩放把手：三道斜线，一看就知道能拖（小块贴图，不做整画布合成）
    def build_grip():
        pad = 6 * scale
        tw = int(20 * scale)
        tile = tile_of(tw, tw)
        d = ImageDraw.Draw(tile)
        gx = gy = tw - pad
        for i in (1, 2, 3):
            step = i * 5 * scale
            d.line((gx - step, gy, gx, gy - step), fill=(255, 255, 255, 70),
                   width=max(1, int(1.4 * scale)))
        return tile

    grip = cached_tile(("grip", round(scale, 3)), build_grip)
    target = P(CANVAS_W - 7, CANVAS_H - 7)
    img = blit(img, grip, target[0] - (grip.size[0] - 6 * scale), target[1] - (grip.size[1] - 6 * scale))
    dl = ImageDraw.Draw(img, "RGBA")

    # ================= 按钮 =================
    buttons = {}
    bsize, gap = 22, 8
    names = ["refresh", "opacity", "desktop", "clickthrough", "close"]
    x, y0 = BUTTON_ORIGIN
    for name in names:
        rect = (x, y0, x + bsize, y0 + bsize)
        active = (name == "desktop" and desktop_layer) or (name == "clickthrough" and clickthrough)
        if name == hover or active:
            img = layer(img, lambda d, r=rect, a=active: d.rounded_rectangle(
                (*P(r[0], r[1]), *P(r[2], r[3])), radius=int(7 * scale),
                fill=(255, 255, 255, 66 if a else 34)))
        img = draw_icon_glyph(img, *P(rect[0] + bsize / 2, rect[1] + bsize / 2),
                              bsize * scale, name, alpha=255 if active else 200)
        buttons[name] = rect
        x += bsize + gap

    dl = ImageDraw.Draw(img, "RGBA")

    if opacity < 0.999:
        img = fade(img, opacity)
    return img, buttons


# --------------------------------------------------------------------------
# 八、窗口
# --------------------------------------------------------------------------

class Widget:
    TIMER_ID = 1
    HOTKEY_ID = 1
    HOTKEY_ID_QUIT = 2
    HOTKEY_ID_QUIT = 2

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.hub = DataHub(cfg)
        res = cfg.get("resources", {})
        self.sys = SysStats(res.get("disk", "C:"), res.get("cpu_history", 60))
        self.sys.sample()          # 第一次只做基准，CPU 需要两次采样才有意义
        self.dpi_scale = max(1.0, user32.GetDpiForSystem() / 96.0)
        try:
            saved_scale = float(cfg.get("scale") or 1.0)
        except (TypeError, ValueError):
            saved_scale = 1.0
        self.user_scale = min(2.2, max(0.55, saved_scale))
        self.scale = self.dpi_scale * self.user_scale
        self.resizing = False
        self.resize_origin = (0, 0)
        self.resize_base = 1.0
        self.resize_last = 0.0
        self.resize_pending = None
        self.resize_snapshot = None
        self.visible = not bool(cfg.get("start_hidden", False))
        self.tray = NOTIFYICONDATAW()
        self.tray_icon = None
        self.tray_added = False
        self._last_tray_click = 0.0
        self.hover = None
        self.hover_last = 0.0
        self.hover_pending = False
        self.pressed = None
        self.dragging = False
        self.drag_origin = (0, 0)
        self.win_origin = (0, 0)
        self.opacity_index = 0
        self.opacity = cfg.get("opacity_levels", [1.0])[0]
        self.clickthrough = False
        self.clickthrough_until = 0.0
        self.desktop_layer = False
        self.reset_hotkey = None
        self.quit_hotkey = None
        self._hotkeys_done = False
        self.desktop_layer = False
        self.reset_hotkey = None
        self.quit_hotkey = None
        self._hotkeys_done = False
        self.hint = None
        self.hint_until = 0.0
        self.last_minute = None
        self._lock = threading.Lock()
        self.image, self.buttons = render(self._state(), self.scale, self.opacity,
                                          None, False, False, None)
        self._wndproc_ref = WNDPROC(self._wndproc)
        self.hwnd = self._create_window()
        self._apply_style()
        self._present()

    def _state(self) -> dict:
        state = self.hub.snapshot()
        state.update(self.sys.snapshot())
        return state

    # -- 创建 -------------------------------------------------------------
    def _create_window(self):
        hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, IDC_SIZEALL)
        wc.lpszClassName = "LumenDesktopWidget"
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err != 1410:        # ERROR_CLASS_ALREADY_EXISTS
                raise OSError(f"RegisterClassExW 失败: {err}")
        w, h = self.image.size
        x, y = self._initial_position(w, h)
        ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST
        hwnd = user32.CreateWindowExW(ex, "LumenDesktopWidget", "LumenWidget", WS_POPUP,
                                      x, y, w, h, None, None, hinst, None)
        if not hwnd:
            raise OSError(f"CreateWindowExW 失败: {ctypes.get_last_error()}")
        # 关键一步：没有 WS_VISIBLE 的窗口即使画好了也不会显示。
        # SW_SHOWNOACTIVATE 保证显示的同时不抢焦点。
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h,
                            SWP_NOACTIVATE | SWP_SHOWWINDOW)
        if not self.visible:            # 只驻留托盘，不占桌面
            user32.ShowWindow(hwnd, SW_HIDE)
        return hwnd

    def _initial_position(self, w, h):
        pos = self.cfg.get("position")
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            return int(pos[0]), int(pos[1])
        r = RECT()
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0)
        margin = int(20 * self.scale)
        return r.right - w - margin, r.top + margin

    def _apply_style(self):
        """置顶、不进 Alt+Tab、点击不抢焦点 —— 这三件事决定了它像不像系统组件。"""
        ex = GET_LONG(self.hwnd, GWL_EXSTYLE)
        ex |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        ex = ex | WS_EX_TRANSPARENT if self.clickthrough else ex & ~WS_EX_TRANSPARENT
        SET_LONG(self.hwnd, GWL_EXSTYLE, ex)
        if not self.desktop_layer:
            user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        self._register_hotkeys()

    def _register_hotkeys(self):
        """挨个试候选快捷键，把真正注册成功的那个记下来 ——
        不能给用户一个假的承诺（上一版就是 Ctrl+Alt+W 被别的软件占了，
        穿透之后谁也救不回窗口）。"""
        if self._hotkeys_done:
            return
        self._hotkeys_done = True
        for mods, vk, label in RESET_HOTKEYS:
            if user32.RegisterHotKey(self.hwnd, self.HOTKEY_ID, mods, vk):
                self.reset_hotkey = label
                break
        for mods, vk, label in QUIT_HOTKEYS:
            if (mods, vk) == (RESET_HOTKEYS[0][0], RESET_HOTKEYS[0][1]):
                continue
            if user32.RegisterHotKey(self.hwnd, self.HOTKEY_ID_QUIT, mods, vk):
                self.quit_hotkey = label
                break
        print(f"[hotkey] 复位键={self.reset_hotkey or '注册失败'} "
              f"退出键={self.quit_hotkey or '注册失败'}")
        log(f"[hotkey] 复位键={self.reset_hotkey or '注册失败'} "
            f"退出键={self.quit_hotkey or '注册失败'}")

    # -- 系统托盘 ---------------------------------------------------------
    def _tray_tip(self) -> str:
        state = self._state()
        tip = (f"桌面小组件 · CPU {state.get('cpu', 0):.0f}%"
               f" · 内存 {state.get('mem_pct', 0):.0f}%")
        if self.clickthrough:
            tip += " · 穿透中"
        if not self.visible:
            tip += " · 已隐藏"
        return tip[:120]

    def _add_tray(self):
        """托盘图标是所有自救办法里最可靠的一个：窗口再怎么样，它都在。"""
        if self.tray_added:
            return
        self.tray_icon = make_hicon(tray_icon_image(32))
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP
        nid.uCallbackMessage = WM_APP_TRAY
        nid.hIcon = self.tray_icon
        nid.szTip = self._tray_tip()
        self.tray = nid
        ok = shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        self.tray_added = bool(ok)
        log(f"[tray] {'已加入系统托盘' if ok else '加入失败（当前桌面可能没有任务栏）'}")

    def _update_tray_tip(self):
        if not self.tray_added:
            return
        self.tray.szTip = self._tray_tip()
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self.tray))

    def _remove_tray(self):
        if self.tray_added:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.tray))
            self.tray_added = False
        if self.tray_icon:
            user32.DestroyIcon(self.tray_icon)
            self.tray_icon = None

    def _show_menu(self):
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        user32.AppendMenuW(menu, MF_STRING, 1001,
                           "隐藏浮窗" if self.visible else "显示浮窗")
        user32.AppendMenuW(menu, MF_STRING, 1002, "重置位置与大小")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if self._autostart_enabled() else 0),
                           1003, "开机自动启动")
        user32.AppendMenuW(menu, MF_STRING, 1005, "创建桌面快捷方式")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, 1004, "退出")
        pos = POINT()
        user32.GetCursorPos(ctypes.byref(pos))
        user32.SetForegroundWindow(self.hwnd)
        cmd = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
                                    pos.x, pos.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, 0, 0, 0)     # 官方推荐收尾，否则菜单可能赖着不走
        user32.DestroyMenu(menu)
        if cmd == 1001:
            self._toggle_visible()
        elif cmd == 1002:
            self._reset_layout()
        elif cmd == 1003:
            self._toggle_autostart()
        elif cmd == 1005:
            self._make_shortcut()
        elif cmd == 1004:
            user32.DestroyWindow(self.hwnd)

    def _toggle_visible(self):
        self.visible = not self.visible
        if self.visible:
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
            self._redraw()
        else:
            user32.ShowWindow(self.hwnd, SW_HIDE)
        self._update_tray_tip()
        log(f"[tray] 浮窗{'已显示' if self.visible else '已隐藏'}")

    def _reset_layout(self):
        self.user_scale = 1.0
        self.scale = self.dpi_scale
        self.opacity_index = 0
        self.opacity = self.cfg.get("opacity_levels", [1.0])[0]
        self.clickthrough = False
        self.clickthrough_until = 0.0
        if self.desktop_layer:
            user32.SetParent(self.hwnd, None)
            self.desktop_layer = False
        self._redraw()
        w, h = self.image.size
        r = RECT()
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0)
        margin = int(20 * self.dpi_scale)
        x, y = r.right - w - margin, r.top + margin
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, w, h,
                            SWP_NOACTIVATE | SWP_SHOWWINDOW)
        self.visible = True
        self.cfg["position"] = [x, y]
        self.cfg["scale"] = self.user_scale
        save_runtime_state(self.cfg)
        self._apply_style()
        self._toast("已恢复默认位置与大小", 3)

    # -- 开机自启（往启动文件夹放一个 .vbs，比 .bat 干净：不会闪黑框）------
    @staticmethod
    def _startup_vbs_path() -> str:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs",
                            "Startup", "桌面小组件.vbs")

    def _autostart_enabled(self) -> bool:
        return os.path.exists(self._startup_vbs_path())

    def _make_shortcut(self):
        path = create_desktop_shortcut()
        if path:
            self._toast("桌面快捷方式已就绪", 4)
        else:
            self._toast("创建快捷方式失败，看 widget.log", 4)
        log(f"[shortcut] {path or '创建失败'}")

    def _toggle_autostart(self):
        path = self._startup_vbs_path()
        try:
            if os.path.exists(path):
                os.remove(path)
                self._toast("已取消开机自启", 3)
            else:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                pyw = sys.executable.replace("python.exe", "pythonw.exe")
                script = os.path.abspath(__file__)
                with open(path, "w", encoding="mbcs", errors="replace") as f:
                    f.write('CreateObject("WScript.Shell").Run """%s"" ""%s""", 0, False\n'
                            % (pyw, script))
                self._toast("已设为开机自启", 3)
        except Exception as exc:
            log(f"[autostart] 失败: {exc!r}")
            self._toast("开机自启设置失败", 3)

    # -- 缩放 -------------------------------------------------------------
    def _set_user_scale(self, value: float, fast: bool = False):
        # 吸附到 0.05 的整数倍：一来缩放步进手感更稳，二来尺寸重复命中底图缓存
        value = round(float(value) / 0.05) * 0.05
        value = min(2.2, max(0.55, value))
        if abs(value - self.user_scale) < 0.002:
            return
        self.user_scale = value
        self.scale = self.dpi_scale * value
        self._redraw(fast=fast)        # render 按新 scale 出图
        w, h = self.image.size
        user32.SetWindowPos(self.hwnd, 0, 0, 0, w, h,
                            SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE)

    def _resize_preview(self, value: float):
        """拖动缩放时的预览：把当前那一帧整体拉伸到新尺寸。

        比每帧重建底图快一个数量级（跟浏览器拖窗口、手机缩放手势是一个思路），
        松手后再按新的尺寸完整重画一次，所以最终画面是清晰的。
        """
        target = min(2.2, max(0.55, round(float(value) / 0.05) * 0.05))
        if abs(target - self.user_scale) < 0.001:
            return
        self.user_scale = target
        self.scale = self.dpi_scale * target
        pad = int(SHADOW * self.scale)
        w = int(CANVAS_W * self.scale) + pad * 2
        h = int(CANVAS_H * self.scale) + pad * 2
        if self.resize_snapshot is not None:
            self.image = self.resize_snapshot.resize((w, h), Image.BILINEAR)
            self._present()
        user32.SetWindowPos(self.hwnd, 0, 0, 0, w, h,
                            SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE)

    def _register_hotkeys(self):
        """挨个试候选快捷键，把真正注册成功的那个记下来，免得给用户一个假的承诺。"""
        if self._hotkeys_done:
            return
        self._hotkeys_done = True
        for mods, vk, label in RESET_HOTKEYS:
            if user32.RegisterHotKey(self.hwnd, self.HOTKEY_ID, mods, vk):
                self.reset_hotkey = label
                break
        for mods, vk, label in QUIT_HOTKEYS:
            if (mods & ~MOD_SHIFT) == (RESET_HOTKEYS[0][0] & ~MOD_SHIFT) and vk == RESET_HOTKEYS[0][1]:
                continue
            if user32.RegisterHotKey(self.hwnd, self.HOTKEY_ID_QUIT, mods, vk):
                self.quit_hotkey = label
                break
        print(f"[hotkey] 复位键={self.reset_hotkey or '注册失败'} 退出键={self.quit_hotkey or '注册失败'}")

    # -- 呈现 -------------------------------------------------------------
    def _present(self):
        img = self.image
        w, h = img.size
        bgra = img.convert("RGBA").tobytes("raw", "BGRA")

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h          # 负数 = 自顶向下
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = DIB_RGB_COLORS

        screen_dc = user32.GetDC(None)
        mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        bits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(mem_dc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                      ctypes.byref(bits), None, 0)
        ctypes.memmove(bits, bgra, len(bgra))
        old = gdi32.SelectObject(mem_dc, hbmp)

        rect = RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        dst, size, src = POINT(rect.left, rect.top), SIZE(w, h), POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(self.hwnd, screen_dc, ctypes.byref(dst), ctypes.byref(size),
                                   mem_dc, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA)
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)

    def _redraw(self, fast: bool = False):
        with self._lock:
            now = time.time()
            if self.clickthrough and self.clickthrough_until:
                left = max(0, int(math.ceil(self.clickthrough_until - now)))
                hint = f"穿透中 · {left}s 后自动解除"
            elif self.clickthrough:
                hint = "穿透中 · 永久模式"
            elif self.hint and now < self.hint_until:
                hint = self.hint
            else:
                hint = None
            self.image, self.buttons = render(self._state(), self.scale, self.opacity,
                                              self.hover, self.clickthrough,
                                              self.desktop_layer, hint, fast)
            self._present()
        self._update_tray_tip()

    def _clickthrough_off(self, auto: bool = False):
        """把鼠标穿透关掉 —— 这是防呆关键：穿透过就点不到任何按钮了。"""
        if not self.clickthrough:
            return
        self.clickthrough = False
        self.clickthrough_until = 0.0
        self._apply_style()
        self.hint, self.hint_until = None, 0.0
        self._redraw()
        if auto:
            self._toast("穿透已自动解除，鼠标回来了", 3)

    # -- 交互 -------------------------------------------------------------
    def _hit(self, px, py):
        pad = int(SHADOW * self.scale)
        lx, ly = (px - pad) / self.scale, (py - pad) / self.scale
        if lx >= CANVAS_W - RESIZE_ZONE and ly >= CANVAS_H - RESIZE_ZONE:
            return "__resize__"          # 右下角是缩放把手
        for name, (x0, y0, x1, y1) in self.buttons.items():
            if x0 <= lx <= x1 and y0 <= ly <= y1:
                return name
        return None

    def _toast(self, text, seconds=4.0):
        self.hint, self.hint_until = text, time.time() + seconds
        self._redraw()

    def _action(self, name):
        if name == "close":
            user32.DestroyWindow(self.hwnd)
        elif name == "refresh":
            self._toast("正在刷新…", 1.5)
            self.hub.refresh_now()
            threading.Thread(target=lambda: (self.hub._fetch_weather(),
                                             self.hub._fetch_balance(),
                                             self._post_rerender()), daemon=True).start()
        elif name == "opacity":
            levels = self.cfg.get("opacity_levels", [1.0])
            self.opacity_index = (self.opacity_index + 1) % len(levels)
            self.opacity = levels[self.opacity_index]
            self._redraw()
        elif name == "clickthrough":
            self.clickthrough = not self.clickthrough
            seconds = float(self.cfg.get("clickthrough_seconds", 10) or 0)
            self.clickthrough_until = (time.time() + seconds) if (self.clickthrough and seconds > 0) else 0.0
            self._apply_style()
            self._redraw()
            if self.clickthrough:
                if self.clickthrough_until:
                    self._toast(f"已穿透 · {int(seconds)} 秒后自动解除", 3)
                else:
                    self._toast("已穿透（永久）· 只能靠快捷键恢复", 5)
        elif name == "desktop":
            self._toggle_desktop_layer()

    def _toggle_desktop_layer(self):
        """挂到桌面 WorkerW 图层：变成会被普通窗口盖住的桌面挂件。"""
        if not self.desktop_layer:
            target = self._find_workerw()
            if target:
                user32.SetParent(self.hwnd, target)
                self.desktop_layer = True
                self._toast("已贴桌面层 · Ctrl+Alt+W 恢复", 6)
            else:
                self._toast("没找到桌面层，保持置顶", 4)
        else:
            user32.SetParent(self.hwnd, None)
            self.desktop_layer = False
            self._apply_style()
        self._redraw()

    @staticmethod
    def _find_workerw():
        progman = user32.FindWindowW("Progman", None)
        if progman:
            user32.SendMessageTimeoutW(progman, 0x052C, 0, 0, 0, 1000, None)
        found = []

        def cb(hwnd, _):
            if user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None):
                sibling = user32.FindWindowExW(0, hwnd, "WorkerW", None)
                if sibling:
                    found.append(sibling)
            return True
        user32.EnumWindows(WNDENUMPROC(cb), 0)
        return found[0] if found else None

    def _reset_state(self):
        """一键兜底：穿透 / 桌面层 / 透明度全部归位，永远找得回来。"""
        self.clickthrough = False
        self.clickthrough_until = 0.0
        if self.desktop_layer:
            user32.SetParent(self.hwnd, None)
            self.desktop_layer = False
        self.opacity_index = 0
        self.opacity = self.cfg.get("opacity_levels", [1.0])[0]
        self._apply_style()
        self._toast("已恢复正常模式", 3)

    def _post_rerender(self):
        user32.PostMessageW(self.hwnd, WM_APP_RERENDER, 0, 0)

    # -- 系统资源采样线程 --------------------------------------------------
    def _start_sampler(self):
        interval = float(self.cfg.get("resources", {}).get("sample_seconds", 2.0) or 2.0)

        def loop():
            while True:
                time.sleep(max(0.5, interval))
                try:
                    self.sys.sample()
                    self._post_rerender()
                except Exception as exc:
                    print(f"[sys] 采样失败: {exc}")
        threading.Thread(target=loop, daemon=True).start()

    # -- 消息循环 ---------------------------------------------------------
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TIMER:
                if self.hover_pending and time.time() - self.hover_last >= 0.05:
                    self.hover_pending = False
                    self.hover_last = time.time()
                    self._redraw()
                if self.clickthrough and self.clickthrough_until:
                    if time.time() >= self.clickthrough_until:
                        self._clickthrough_off(auto=True)
                    else:
                        self._redraw()          # 让倒计时数字动起来
                minute = datetime.now().strftime("%H:%M")
                if minute != self.last_minute:
                    self.last_minute = minute
                    self._redraw()
                elif self.hint and time.time() >= self.hint_until:
                    self.hint = None
                    self._redraw()
                return 0
            if msg == WM_APP_RERENDER:
                self._redraw()
                return 0
            if msg == WM_APP_TRAY:
                if lparam in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._show_menu()
                elif lparam in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    # 双击会产生 UP + DBLCLK + UP 三条消息，不去抖就会连翻好几次
                    now = time.time()
                    if now - self._last_tray_click > 0.5:
                        self._last_tray_click = now
                        self._toggle_visible()
                return 0
            if msg == WM_APP_SHOW:
                # 有人又点了一次快捷方式：把浮窗叫出来，而不是开第二个
                was_hidden = not self.visible
                if was_hidden:
                    self._toggle_visible()
                else:
                    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                    self._toast("已在桌面上了", 2)
                return 0
            if msg == WM_HOTKEY:
                if wparam == self.HOTKEY_ID_QUIT:
                    user32.DestroyWindow(self.hwnd)
                else:
                    self._reset_state()
                return 0
            if msg == 0x0215:           # WM_CAPTURECHANGED：鼠标被别人抢走时，别把拖拽状态留在 True
                self.dragging = False
                self.pressed = None
                return 0
            if msg == WM_SETCURSOR:
                pos, rect = POINT(), RECT()
                user32.GetCursorPos(ctypes.byref(pos))
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                name = self._hit(pos.x - rect.left, pos.y - rect.top)
                if name == "__resize__":
                    cursor = IDC_SIZENWSE
                elif name:
                    cursor = IDC_HAND
                else:
                    cursor = IDC_SIZEALL
                user32.SetCursor(user32.LoadCursorW(None, cursor))
                return 1
            if msg == WM_MOUSEMOVE:
                x = ctypes.c_short(lparam & 0xFFFF).value
                y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                if self.resizing:
                    cur = POINT()
                    user32.GetCursorPos(ctypes.byref(cur))
                    delta = (cur.x - self.resize_origin[0]) + (cur.y - self.resize_origin[1])
                    target = self.resize_base * (1.0 + delta / 700.0)
                    # 拖动缩放时限制到 10fps：不然每个鼠标移动事件都重建整张底图，
                    # 手感就是一顿一顿的。松手时再补上最后一帧。
                    now = time.time()
                    if now - self.resize_last >= 0.03:
                        self.resize_last = now
                        self._resize_preview(target)               # 拉伸预览，够快
                    else:
                        self.resize_pending = target
                    return 0
                if self.dragging:
                    cur = POINT()
                    user32.GetCursorPos(ctypes.byref(cur))
                    user32.SetWindowPos(hwnd, 0,
                                        self.win_origin[0] + cur.x - self.drag_origin[0],
                                        self.win_origin[1] + cur.y - self.drag_origin[1],
                                        0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
                    return 0
                name = self._hit(x, y)
                if name != self.hover:
                    self.hover = name
                    # 鼠标扫过一排按钮会连发好几个事件，节流一下免得一顿一顿
                    now = time.time()
                    if now - getattr(self, "hover_last", 0.0) >= 0.05:
                        self.hover_last = now
                        self._redraw()
                    else:
                        self.hover_pending = True
                return 0
            if msg == WM_LBUTTONDOWN:
                x = ctypes.c_short(lparam & 0xFFFF).value
                y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                self.pressed = self._hit(x, y)
                if self.pressed == "__resize__":
                    cur = POINT()
                    user32.GetCursorPos(ctypes.byref(cur))
                    self.resize_origin = (cur.x, cur.y)
                    self.resize_base = self.user_scale
                    self.resize_snapshot = self.image      # 拉伸预览用这一帧
                    self.resizing = True
                    user32.SetCapture(hwnd)
                    return 0
                if self.pressed is None:
                    cur, rect = POINT(), RECT()
                    user32.GetCursorPos(ctypes.byref(cur))
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    self.drag_origin = (cur.x, cur.y)
                    self.win_origin = (rect.left, rect.top)
                    self.dragging = True
                    user32.SetCapture(hwnd)
                return 0
            if msg == WM_LBUTTONUP:
                if self.resizing:
                    self.resizing = False
                    user32.ReleaseCapture()
                    if self.resize_pending is not None:
                        self._set_user_scale(self.resize_pending)
                        self.resize_pending = None
                    self.resize_snapshot = None
                    self._redraw()          # 松手后按新尺寸完整重画一次
                    rect = RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    self.cfg["scale"] = round(self.user_scale, 3)
                    self.cfg["position"] = [rect.left, rect.top]
                    save_runtime_state(self.cfg)
                    log(f"[resize] 缩放到 {self.user_scale:.2f}，窗口 {self.image.size}")
                elif self.dragging:
                    self.dragging = False
                    user32.ReleaseCapture()
                    rect = RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    self.cfg["position"] = [rect.left, rect.top]
                    save_runtime_state(self.cfg)
                elif self.pressed:
                    x = ctypes.c_short(lparam & 0xFFFF).value
                    y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                    if self._hit(x, y) == self.pressed:
                        self._action(self.pressed)
                self.pressed = None
                return 0
            if msg == WM_RBUTTONUP:
                self._reset_state()
                return 0
            if msg == WM_DISPLAYCHANGE:
                self._redraw()
                return 0
            if msg in (WM_CLOSE, WM_DESTROY):
                rect = RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                self.cfg["position"] = [rect.left, rect.top]
                self.cfg["scale"] = round(self.user_scale, 3)
                save_runtime_state(self.cfg)
                if msg == WM_CLOSE:
                    user32.DestroyWindow(hwnd)
                else:
                    self._remove_tray()
                    user32.KillTimer(hwnd, self.TIMER_ID)
                    user32.UnregisterHotKey(hwnd, self.HOTKEY_ID)
                    user32.UnregisterHotKey(hwnd, self.HOTKEY_ID_QUIT)
                    log("退出")
                    user32.PostQuitMessage(0)
                return 0
                return 0
        except Exception as exc:        # 窗口过程里抛异常会直接崩掉，兜住并打印
            print(f"[wndproc] {msg:#06x}: {exc!r}")
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # -- 启动 -------------------------------------------------------------
    def run(self):
        user32.SetTimer(self.hwnd, self.TIMER_ID, 500, None)
        self._start_sampler()
        self.hub.start(self._post_rerender)
        self._add_tray()
        log(f"启动：缩放={self.user_scale:.2f} DPI比例={self.dpi_scale:.2f} "
            f"可见={self.visible} 托盘={self.tray_added}")
        # 桌面上没有快捷方式就自己建一个（只有程序知道自己的解释器在哪）
        if not os.path.exists(shortcut_path()):
            log(f"[shortcut] 自动创建：{create_desktop_shortcut() or '失败'}")
        if self.reset_hotkey:
            self._toast(f"拖动 · 右下角缩放 · 复位 {self.reset_hotkey}", 8)
        else:
            self._toast("拖动 · 右下角缩放（复位快捷键被占用）", 8)
        self._redraw()
            self._toast(f"就绪 · 复位 {self.reset_hotkey}"
                        + (f" · 退出 {self.quit_hotkey}" if self.quit_hotkey else ""), 5)
        else:
            self._toast("复位快捷键被占用：穿透 10 秒后会自动解除", 6)
        self._redraw()
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        return 0


def demo_weather() -> dict:
    """联网失败时的兜底数值（卡片上会标「离线 · 示例数据」）。"""
    return {
        "temp": 24, "feels": 26, "humidity": 58, "wind": 1.9, "wind_dir": "东风",
        "code": 2, "kind": "suncloud", "desc": "多云",
        "temp_max": 28, "temp_min": 18, "rain_prob": 20, "aqi": 62,
        "source": "示例",
    }


def demo_state() -> dict:
    """预览和离线兜底用的完整假数据。"""
    def series(base, wobble, drift=0.0):
        return [max(1.0, min(99.0, base + wobble * math.sin(i / 6.5)
                                 + drift * i / 60.0 + random.uniform(-wobble / 3, wobble / 3)))
                for i in range(60)]

    history = series(26, 9, 14)          # CPU：起伏明显
    mem_history = series(61, 2.5)        # 内存：平缓
    disk_history = series(78, 0.6)       # 磁盘：几乎不动
    return {
        "city": "杭州", **demo_weather(), "offline": False,
        "weather_source": "中国气象局",
        "updated": datetime.now().strftime("%H:%M"),
        "balance_ok": True, "balance_total": 110.0, "balance_granted": 10.0,
        "balance_topped": 100.0, "balance_currency": "CNY", "balance_delta": 1.23,
        "balance_available": True, "balance_note": "",
        "balance_updated": datetime.now().strftime("%H:%M"), "balance_interval": 5,
        "cpu": 34.2, "cpu_history": history,
        "mem_history": mem_history, "disk_history": disk_history,
        "mem_pct": 61.8, "mem_used_gb": 9.9, "mem_total_gb": 16.0,
        "disk_pct": 78.4, "disk_used_gb": 401.0, "disk_total_gb": 512.0, "disk_name": "C:",
    }


def preview(path: str, scale: float = 2.0, state: dict | None = None) -> None:
    """离线渲染一帧到 PNG，用来调外观（不开窗、不联网）。"""
    img, _ = render(state or demo_state(), scale, 1.0, "refresh", False, False, None)
    img.save(path)
    print(f"已写出预览: {path} ({img.size[0]}x{img.size[1]})")


def probe_weather(cfg: dict) -> int:
    """逐个天气源试一遍并打印结果 —— 在你自己机器上跑，就能确定哪条路通。"""
    print("=" * 68)
    print("天气源探测")
    print(f"城市编码（中国天气网 / 和风天气共用）: {cfg.get('weather', {}).get('cma_city_id')}")
    print(f"配置里指定的源: {cfg.get('weather', {}).get('source')}")
    print(f"和风天气 Key: {'已配置' if qweather_key(cfg) else '（没有，和风这一路会直接跳过）'}")
    print("=" * 68)
    print()
    sources = [
        ("中国气象局 cma（免密钥）", fetch_cma),
        ("和风天气 qweather（需 Key）", fetch_qweather),
        ("Open-Meteo（国外兜底）", fetch_openmeteo),
    ]
    for title, fetcher in sources:
        started = time.time()
        try:
            data = fetcher(cfg)
            cost = time.time() - started
            if data.get("temp") is None:
                print(f"[字段不全] {title}  ({cost:.2f}s)")
            else:
                print(f"[成功] {title}  ({cost:.2f}s)")
            detail = ", ".join(f"{k}={v}" for k, v in data.items())
            print(f"         {detail}")
        except Exception as exc:
            cost = time.time() - started
            print(f"[失败] {title}  ({cost:.2f}s)")
            print(f"         {exc} {net_hint(exc)}".rstrip())
        print()
    print("=" * 68)
    print("哪一行显示 [成功]，就把 config.json 里的 weather.source 设成它的名字：")
    print("  cma / qweather / open-meteo ；想让它自动挑就保持 auto")
    return 0


def main(argv) -> int:
    if "--probe" in argv:
        return probe_weather(load_config())
    if "--preview" in argv:
        idx = argv.index("--preview")
        out = argv[idx + 1] if len(argv) > idx + 1 else os.path.join(APP_DIR, "preview.png")
        preview(out)
        return 0
    enable_dpi_awareness()
    # 单实例：已经开着就把已有那个叫到前台来，不重复启动
    ctypes.set_last_error(0)
    kernel32.CreateMutexW(None, False, MUTEX_NAME)
    already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    if already:
        existing = user32.FindWindowW("LumenDesktopWidget", None)
        if existing:
            user32.PostMessageW(existing, WM_APP_SHOW, 0, 0)
            return 0
    try:
        open(LOG_PATH, "w", encoding="utf-8").close()      # 每次启动清空日志
    except Exception:
        pass
    try:
        widget = Widget(load_config())
        log("浮窗已启动")
        return widget.run()
    except Exception:
        # pythonw 没有控制台，崩了也要在日志里留下证据
        log("[fatal] 启动失败:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception:
        log("[fatal] " + traceback.format_exc())
        sys.exit(1)
