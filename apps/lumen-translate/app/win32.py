"""Windows 原生能力：全局快捷键、系统托盘、剪贴板、模拟按键、光标位置。

全部用 ctypes 直接调 Win32，不依赖 pywin32 / pystray 之类的第三方库。
非 Windows 平台上所有函数安全降级（返回 False / None），方便在别的系统上跑测试。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

IS_WINDOWS = sys.platform == "win32"

# ------------------------------------------------------------------ 常量
WM_APP = 0x8000
WM_TRAY = WM_APP + 1
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010
NIIF_INFO = 0x00000001

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_C = 0x43

TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
MF_CHECKED = 0x0008
MF_GRAYED = 0x0001

# 低层鼠标钩子
WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207

# 模拟鼠标
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000

# 终端类窗口，自动划词时默认跳过（免得误发 Ctrl+C 打断正在跑的命令）
CONSOLE_CLASSES = (
    "ConsoleWindowClass",
    "CASCADIA_HOSTING_WINDOW_CLASS",
    "mintty",
    "WindowsTerminal",
)

VK_NAMES: dict[str, int] = {
    "space": 0x20,
    "enter": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "`": 0xC0,
    "-": 0xBD,
    "=": 0xBB,
    "[": 0xDB,
    "]": 0xDD,
    "\\": 0xDC,
    ";": 0xBA,
    "'": 0xDE,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
}
for _i in range(1, 25):
    VK_NAMES[f"f{_i}"] = 0x70 + _i - 1
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK_NAMES[_c] = ord(_c.upper())
for _d in "0123456789":
    VK_NAMES[_d] = ord(_d)


# ------------------------------------------------------------------ 结构体
if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSEX(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", wintypes.HICON),
        ]

    class NOTIFYICONDATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128),
            ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD),
            ("szInfo", wintypes.WCHAR * 256),
            ("uVersion", wintypes.UINT),
            ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD),
            ("guidItem", ctypes.c_byte * 16),
            ("hBalloonIcon", wintypes.HICON),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", wintypes.POINT),
            ("mouseData", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    # 64 位下必须逐个声明原型：不写 argtypes/restype 的话，ctypes 会按 32 位整数
    # 处理返回值，句柄和指针会被截断（GlobalLock 立刻返回 0）。
    def _declare() -> None:
        BOOL = wintypes.BOOL
        HANDLE = ctypes.c_void_p
        LPVOID = ctypes.c_void_p

        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        kernel32.GetCurrentProcessId.restype = wintypes.DWORD
        kernel32.GetModuleHandleW.restype = HANDLE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GlobalAlloc.restype = HANDLE
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalLock.restype = LPVOID
        kernel32.GlobalLock.argtypes = [HANDLE]
        kernel32.GlobalUnlock.restype = BOOL
        kernel32.GlobalUnlock.argtypes = [HANDLE]

        user32.DefWindowProcW.restype = LRESULT
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.RegisterClassExW.restype = wintypes.ATOM
        user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEX)]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, LPVOID,
        ]
        user32.DestroyWindow.restype = BOOL
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.LoadImageW.restype = HANDLE
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.LoadIconW.restype = HANDLE
        user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
        user32.DestroyIcon.restype = BOOL
        user32.DestroyIcon.argtypes = [HANDLE]
        user32.CreatePopupMenu.restype = wintypes.HMENU
        user32.AppendMenuW.restype = BOOL
        user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
        user32.TrackPopupMenu.restype = ctypes.c_int
        user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, LPVOID]
        user32.DestroyMenu.restype = BOOL
        user32.DestroyMenu.argtypes = [wintypes.HMENU]
        user32.SetForegroundWindow.restype = BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.GetCursorPos.restype = BOOL
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.PostMessageW.restype = BOOL
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostQuitMessage.restype = None
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        user32.PostThreadMessageW.restype = BOOL
        user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.GetMessageW.restype = ctypes.c_int
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.TranslateMessage.restype = BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = LRESULT
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.RegisterHotKey.restype = BOOL
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.UnregisterHotKey.restype = BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SendInput.restype = wintypes.UINT
        # 参数用 c_void_p：这样传 byref(数组) 和传数组指针都能接受
        user32.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
        user32.OpenClipboard.restype = BOOL
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.CloseClipboard.restype = BOOL
        user32.EmptyClipboard.restype = BOOL
        user32.GetClipboardData.restype = HANDLE
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.SetClipboardData.restype = HANDLE
        user32.SetClipboardData.argtypes = [wintypes.UINT, HANDLE]
        user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.SystemParametersInfoW.restype = BOOL
        user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, LPVOID, wintypes.UINT]
        user32.GetSystemMetrics.restype = ctypes.c_int
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        user32.UnhookWindowsHookEx.restype = BOOL
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        user32.CallNextHookEx.restype = LRESULT
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetDoubleClickTime.restype = wintypes.UINT
        user32.SetCursorPos.restype = BOOL
        user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]

        shell32.Shell_NotifyIconW.restype = BOOL
        shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATA)]

    _declare()


# ------------------------------------------------------------------ 快捷键
@dataclass
class HotkeyBinding:
    spec: str          # "ctrl+alt+t"
    callback: Callable[[], None]
    id: int = 0
    modifiers: int = 0
    vk: int = 0
    registered: bool = False
    error: str = ""


def parse_hotkey(spec: str) -> tuple[int, int]:
    """'ctrl+alt+t' -> (modifiers, virtual-key)。不合法就抛 ValueError。"""

    parts = [p.strip().lower() for p in spec.replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise ValueError("快捷键不能为空")
    modifiers = 0
    key = ""
    for part in parts:
        if part in ("ctrl", "control"):
            modifiers |= MOD_CONTROL
        elif part == "alt":
            modifiers |= MOD_ALT
        elif part == "shift":
            modifiers |= MOD_SHIFT
        elif part in ("win", "super", "meta"):
            modifiers |= MOD_WIN
        elif part in VK_NAMES:
            if key:
                raise ValueError(f"一个快捷键只能有一个主键：{spec}")
            key = part
        else:
            raise ValueError(f"认不出来的按键：{part}")
    if not key:
        raise ValueError(f"缺少主键（字母 / 数字 / F1-F24）：{spec}")
    if modifiers == 0:
        raise ValueError(f"必须带至少一个修饰键（ctrl / alt / shift / win）：{spec}")
    return modifiers | MOD_NOREPEAT, VK_NAMES[key]


_PRETTY = {
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
    "win": "Win",
    "super": "Win",
    "meta": "Win",
}


def format_hotkey(spec: str) -> str:
    """统一成 Ctrl+Alt+T 这种显示写法。"""

    out = []
    for part in [p.strip().lower() for p in spec.split("+") if p.strip()]:
        out.append(_PRETTY.get(part, part.upper() if len(part) == 1 else part.capitalize()))
    return "+".join(out) if out else spec


class HotkeyListener(threading.Thread):
    """在独立线程里注册并泵消息，收到 WM_HOTKEY 就回调。

    RegisterHotKey(hwnd=NULL) 把热键绑在当前线程的消息队列上，
    所以注册和 GetMessage 必须在同一个线程里完成。
    """

    def __init__(self, bindings: list[HotkeyBinding], on_error: Callable[[str], None] | None = None):
        super().__init__(daemon=True, name="lumen-hotkeys")
        self.bindings = bindings
        self.on_error = on_error
        self.thread_id: int | None = None
        self.ready = threading.Event()
        self._by_id: dict[int, HotkeyBinding] = {}
        # 注意：不能叫 _stop，那是 threading.Thread 自己的方法，覆盖掉会炸
        self._stopping = False

    def run(self) -> None:
        if not IS_WINDOWS:
            self.ready.set()
            return
        self.thread_id = kernel32.GetCurrentThreadId()
        index = 1
        for binding in self.bindings:
            try:
                binding.modifiers, binding.vk = parse_hotkey(binding.spec)
            except ValueError as exc:
                binding.error = str(exc)
                if self.on_error:
                    self.on_error(f"快捷键 {binding.spec} 无效：{exc}")
                continue
            binding.id = 0xB000 + index
            index += 1
            if user32.RegisterHotKey(None, binding.id, binding.modifiers, binding.vk):
                binding.registered = True
                self._by_id[binding.id] = binding
            else:
                code = ctypes.get_last_error()
                binding.error = "已被别的程序占用" if code == 1409 else f"注册失败（错误码 {code}）"
                if self.on_error:
                    self.on_error(f"快捷键 {format_hotkey(binding.spec)} {binding.error}")
        self.ready.set()

        msg = wintypes.MSG()
        while not self._stopping and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                binding = self._by_id.get(int(msg.wParam))
                if binding is not None:
                    try:
                        binding.callback()
                    except Exception:
                        pass
        for binding in self._by_id.values():
            user32.UnregisterHotKey(None, binding.id)
        self._by_id.clear()

    def stop(self) -> None:
        self._stopping = True
        if IS_WINDOWS and self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)

    def poke(self, hotkey_id: int) -> None:
        """自检用：假装收到了某个热键消息，走一遍回调派发。"""

        binding = self._by_id.get(hotkey_id)
        if binding is not None:
            binding.callback()


# ------------------------------------------------------------------ 托盘
class TrayIcon(threading.Thread):
    """系统托盘图标：左键唤起主窗口，右键弹菜单。

    Shell_NotifyIcon 需要一个真实窗口接收回调消息，所以这里建一个隐藏窗口，
    并在自己的线程里泵消息 —— 右键菜单的 TrackPopupMenu 会阻塞这个线程，
    正好不干扰 Tk 主线程。
    """

    CLASS_NAME = "LumenTrayWndV1"

    def __init__(
        self,
        icon_path: str | Path,
        tooltip: str,
        on_activate: Callable[[], None],
        menu_provider: Callable[[], list[tuple | None]],
    ):
        super().__init__(daemon=True, name="lumen-tray")
        self.icon_path = str(icon_path)
        self.tooltip = tooltip[:127]
        self.on_activate = on_activate
        self.menu_provider = menu_provider
        self.hwnd = None
        self.hicon = None
        self.ready = threading.Event()
        self.ok = False
        self.error = ""
        self._nid = None
        self._wndproc_ref = None

    def run(self) -> None:
        if not IS_WINDOWS:
            self.error = "非 Windows 平台不支持托盘"
            self.ready.set()
            return
        try:
            self._create_window()
            self._add_icon()
            self.ok = True
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self.ready.set()
            return
        self.ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _create_window(self) -> None:
        hinstance = kernel32.GetModuleHandleW(None)
        self._wndproc_ref = WNDPROC(self._wndproc)
        wc = WNDCLASSEX()
        wc.cbSize = ctypes.sizeof(WNDCLASSEX)
        wc.style = 0
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinstance
        wc.lpszClassName = self.CLASS_NAME
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            code = ctypes.get_last_error()
            if code != 1410:  # 1410 = 类已注册，重复注册不算错
                raise OSError(f"RegisterClassExW 失败：{code}")
        self.hwnd = user32.CreateWindowExW(0, self.CLASS_NAME, "Lumen", 0, 0, 0, 0, 0, None, None, hinstance, None)
        if not self.hwnd:
            raise OSError(f"CreateWindowExW 失败：{ctypes.get_last_error()}")

    def _load_icon(self):
        if Path(self.icon_path).exists():
            handle = user32.LoadImageW(None, self.icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if handle:
                return handle
        return user32.LoadIconW(None, wintypes.LPCWSTR(32512))  # IDI_APPLICATION

    def _add_icon(self) -> None:
        self.hicon = self._load_icon()
        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self.hicon
        nid.szTip = self.tooltip
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            raise OSError("Shell_NotifyIcon(NIM_ADD) 失败")
        self._nid = nid

    def notify(self, title: str, text: str) -> None:
        """托盘气泡提示。"""

        if not IS_WINDOWS or not self.ok:
            return
        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_INFO
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = NIIF_INFO
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _wndproc(self, hwnd, msg, wparam, lparam) -> int:
        if msg == WM_TRAY:
            event = int(lparam) & 0xFFFF
            if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                try:
                    self.on_activate()
                except Exception:
                    pass
            elif event == WM_RBUTTONUP:
                self._show_menu()
            return 0
        if msg == WM_COMMAND:
            self._invoke(int(wparam) & 0xFFFF)
            return 0
        if msg == WM_DESTROY:
            if self._nid is not None:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
                self._nid = None
            if self.hicon:
                user32.DestroyIcon(self.hicon)
                self.hicon = None
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self) -> None:
        menu = user32.CreatePopupMenu()
        for item in self.menu_provider() or []:
            if item is None:
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                continue
            cmd_id, label = int(item[0]), item[1]
            checked = bool(item[2]) if len(item) > 2 else False
            enabled = bool(item[3]) if len(item) > 3 else True
            flags = MF_STRING | (MF_CHECKED if checked else 0) | (0 if enabled else MF_GRAYED)
            user32.AppendMenuW(menu, flags, cmd_id, label)
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        user32.SetForegroundWindow(self.hwnd)
        chosen = user32.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON, point.x, point.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, 0, 0, 0)  # 让菜单正常收起
        user32.DestroyMenu(menu)
        if chosen:
            self._invoke(int(chosen))

    def _invoke(self, cmd_id: int) -> None:
        for item in self.menu_provider() or []:
            if item is None:
                continue
            if int(item[0]) == cmd_id:
                action = item[4] if len(item) > 4 else None
                if callable(action):
                    try:
                        action()
                    except Exception:
                        pass
                return

    def stop(self) -> None:
        if IS_WINDOWS and self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)


# ------------------------------------------------------------------ 剪贴板
def _open_clipboard(retries: int = 12) -> bool:
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.03)
    return False


def read_clipboard_text() -> str:
    if not IS_WINDOWS or not _open_clipboard():
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return ctypes.c_wchar_p(pointer).value or ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def write_clipboard_text(text: str) -> bool:
    if not IS_WINDOWS or not _open_clipboard():
        return False
    try:
        user32.EmptyClipboard()
        size = (len(text) + 1) * ctypes.sizeof(ctypes.c_wchar)
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            return False
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, ctypes.create_unicode_buffer(text), size)
        kernel32.GlobalUnlock(handle)
        user32.SetClipboardData(CF_UNICODETEXT, handle)
        return True
    finally:
        user32.CloseClipboard()


def clipboard_sequence() -> int:
    return int(user32.GetClipboardSequenceNumber()) if IS_WINDOWS else 0


# ------------------------------------------------------------------ 其它
def send_ctrl_c() -> bool:
    """给当前前台窗口发一次 Ctrl+C，把选中文本送进剪贴板。"""

    if not IS_WINDOWS:
        return False
    events = (INPUT * 4)()
    keys = (
        (VK_CONTROL, 0),
        (VK_C, 0),
        (VK_C, KEYEVENTF_KEYUP),
        (VK_CONTROL, KEYEVENTF_KEYUP),
    )
    for index, (vk, flags) in enumerate(keys):
        events[index].type = INPUT_KEYBOARD
        events[index].ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=None)
    sent = user32.SendInput(4, ctypes.byref(events), ctypes.sizeof(INPUT))
    return sent == 4


def cursor_position() -> tuple[int, int]:
    if not IS_WINDOWS:
        return (200, 200)
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


# 单实例用的互斥体句柄，必须一直持有，否则会被回收
_instance_mutex = None


def acquire_single_instance(name: str = "LumenTranslate_SingleInstance_v1") -> bool:
    """返回 False 表示已经有一个 Lumen 在跑了。

    一个实例独占全局快捷键和托盘图标，重复启动会静默抢不到热键，
    所以宁可第二次启动时直接提示，也别让人以为是坏了。
    """

    global _instance_mutex
    if not IS_WINDOWS:
        return True
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    # 必须先清零：CreateMutexW 成功时不会重置 last error，直接读会拿到
    # 之前某次调用的残留值（碰巧是 183 就会误判成"已经在运行"）
    ctypes.set_last_error(0)
    _instance_mutex = kernel32.CreateMutexW(None, False, name)
    if not _instance_mutex:
        return True  # 创建失败就别拦着用户
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def message_box(title: str, text: str, flags: int = 0x40) -> None:
    """简单的系统消息框（MB_ICONINFORMATION | MB_OK）。"""

    if not IS_WINDOWS:
        return
    user32.MessageBoxW.restype = ctypes.c_int
    user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    user32.MessageBoxW(None, text, title, flags)


def foreground_window_title() -> str:
    if not IS_WINDOWS:
        return ""
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def work_area() -> tuple[int, int, int, int]:
    """主屏工作区 (left, top, right, bottom)，用来把浮窗摆在不越界的位置。"""

    if not IS_WINDOWS:
        return (0, 0, 1920, 1080)

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    rect = RECT()
    if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
        return rect.left, rect.top, rect.right, rect.bottom
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def virtual_screen() -> tuple[int, int, int, int]:
    """整个虚拟桌面（多显示器合并）的 (left, top, width, height)。"""

    if not IS_WINDOWS:
        return (0, 0, 1920, 1080)
    left = user32.GetSystemMetrics(76)    # SM_XVIRTUALSCREEN
    top = user32.GetSystemMetrics(77)     # SM_YVIRTUALSCREEN
    width = user32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
    height = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    if width <= 0 or height <= 0:
        return (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    return (left, top, width, height)


def window_class_name(hwnd) -> str:
    if not IS_WINDOWS or not hwnd:
        return ""
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def window_pid(hwnd) -> int:
    if not IS_WINDOWS or not hwnd:
        return 0
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def window_at(x: int, y: int):
    """屏幕坐标处最上层的窗口句柄。"""

    if not IS_WINDOWS:
        return 0
    return user32.WindowFromPoint(wintypes.POINT(x, y))


def current_process_id() -> int:
    return int(kernel32.GetCurrentProcessId()) if IS_WINDOWS else 0


class SelectionMouseHook(threading.Thread):
    """低层鼠标钩子：识别"按住左键拖选一段后松手"和"双击选中一个词"。

    钩子回调跑在自己的线程里，必须立刻返回，所以只做状态判断，
    真正的取词交给上层去开线程。
    """

    def __init__(
        self,
        on_select: Callable[[int, int], None],
        on_click: Callable[[int, int], None] | None = None,
        min_drag: int = 6,
        double_click: bool = True,
        skip_own_process: bool = True,
        skip_console: bool = True,
    ):
        super().__init__(daemon=True, name="lumen-mousehook")
        self.on_select = on_select
        # on_click 对每一次左键松手都会回调（不论是否够得上划词条件），
        # 上层用它来"点到别处就收起浮窗"。
        self.on_click = on_click
        self.min_drag = max(0, int(min_drag))
        self.double_click = double_click
        self.skip_own_process = skip_own_process
        self.skip_console = skip_console
        self.ready = threading.Event()
        self.ok = False
        self.error = ""
        self.hook = None
        self.thread_id: int | None = None
        self._proc_ref = None
        self._stopping = False
        self._own_pid = current_process_id()
        # 手势状态
        self._pressed = False
        self._down_point = (0, 0)
        self._max_distance = 0.0
        self._suppressed = False
        self._click_count = 0
        self._last_down_time = 0
        self._last_down_point = (0, 0)
        self.last_reason = ""   # 自检/调试用：最近一次为什么触发或为什么被忽略
        # 调试计数：一次手势里收到了多少 down / 带按键的 move / up
        self.stat_down = 0
        self.stat_move = 0
        self.stat_up = 0

    # -- 线程 ------------------------------------------------------------
    def run(self) -> None:
        if not IS_WINDOWS:
            self.error = "非 Windows 平台不支持"
            self.ready.set()
            return
        self.thread_id = kernel32.GetCurrentThreadId()
        self._proc_ref = HOOKPROC(self._callback)
        self.hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc_ref, kernel32.GetModuleHandleW(None), 0)
        if not self.hook:
            self.error = f"SetWindowsHookExW 失败（错误码 {ctypes.get_last_error()}）"
            self.ready.set()
            return
        self.ok = True
        self.ready.set()
        msg = wintypes.MSG()
        while not self._stopping and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if self.hook:
            user32.UnhookWindowsHookEx(self.hook)
            self.hook = None

    def stop(self) -> None:
        self._stopping = True
        if IS_WINDOWS and self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)

    # -- 钩子回调 --------------------------------------------------------
    def _callback(self, code, wparam, lparam):
        if code == 0:
            try:
                event = int(wparam)
                info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                if event == WM_LBUTTONDOWN:
                    self._on_down(info.pt.x, info.pt.y)
                elif event == WM_MOUSEMOVE:
                    self._on_move(info.pt.x, info.pt.y)
                elif event == WM_LBUTTONUP:
                    self._on_up(info.pt.x, info.pt.y)
                elif event in (WM_RBUTTONDOWN, WM_MBUTTONDOWN):
                    self._reset()
            except Exception:
                pass
        return user32.CallNextHookEx(self.hook, code, wparam, lparam)

    def _reset(self) -> None:
        self._pressed = False
        self._max_distance = 0.0
        self._suppressed = False

    def _on_down(self, x: int, y: int) -> None:
        now = time.time()
        elapsed = (now - self._last_down_time) * 1000
        near = abs(x - self._last_down_point[0]) <= 4 and abs(y - self._last_down_point[1]) <= 4
        if self._last_down_time and elapsed <= user32.GetDoubleClickTime() and near:
            self._click_count = min(self._click_count + 1, 3)
        else:
            self._click_count = 1
        self._last_down_time = now
        self._last_down_point = (x, y)

        self._pressed = True
        self.stat_down += 1
        self._down_point = (x, y)
        self._max_distance = 0.0
        self._suppressed = self._should_skip(x, y)

    def _on_move(self, x: int, y: int) -> None:
        if not self._pressed:
            return
        self.stat_move += 1
        dx = x - self._down_point[0]
        dy = y - self._down_point[1]
        distance = (dx * dx + dy * dy) ** 0.5
        if distance > self._max_distance:
            self._max_distance = distance

    def _on_up(self, x: int, y: int) -> None:
        if not self._pressed:
            return
        self.stat_up += 1
        dragged = self._max_distance >= self.min_drag
        multi_clicked = self.double_click and self._click_count >= 2
        suppressed = self._suppressed
        distance = self._max_distance
        self._reset()
        # 注意：这里不能把 _click_count 清零。连击次数靠"按下"事件之间的时间/距离
        # 判定，清零会让第二次按下永远只数到 1（双击就永远不触发）。

        if self.on_click is not None:
            try:
                self.on_click(x, y)
            except Exception:
                pass
        if suppressed:
            self.last_reason = "忽略：这是我们自己窗口里的操作"
            return
        if not (dragged or multi_clicked):
            self.last_reason = f"忽略：只是点击（位移 {distance:.1f}px）"
            return
        self.last_reason = f"触发：{'拖选' if dragged else ''}{'双击' if multi_clicked and not dragged else ''}"
        try:
            self.on_select(x, y)
        except Exception:
            pass

    def _should_skip(self, x: int, y: int) -> bool:
        """按下点落在我们自己窗口/终端里就不参与自动划词。"""

        hwnd = window_at(x, y)
        if not hwnd:
            return False
        if self.skip_own_process and window_pid(hwnd) == self._own_pid:
            return True
        if self.skip_console and window_class_name(hwnd) in CONSOLE_CLASSES:
            return True
        return False


def set_cursor_position(x: int, y: int) -> bool:
    return bool(user32.SetCursorPos(int(x), int(y))) if IS_WINDOWS else False


def move_mouse_absolute(x: int, y: int) -> bool:
    """用 SendInput 把光标挪到屏幕绝对坐标。

    注意：SetCursorPos 只是直接改光标位置，**不会**产生低层鼠标钩子事件，
    所以任何要测钩子的地方都得用这个函数。
    坐标按屏幕物理像素理解；调用方应先 SetProcessDpiAwareness，否则
    GetSystemMetrics 返回的是缩放后的尺寸，归一化坐标会算歪。
    """

    if not IS_WINDOWS:
        return False
    screen_w = user32.GetSystemMetrics(0) or 1920
    screen_h = user32.GetSystemMetrics(1) or 1080
    nx = int(round(int(x) * 65535 / max(screen_w - 1, 1)))
    ny = int(round(int(y) * 65535 / max(screen_h - 1, 1)))
    events = (INPUT * 1)()
    events[0].type = 0  # INPUT_MOUSE
    events[0].mi = MOUSEINPUT(
        dx=nx, dy=ny, mouseData=0, dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, time=0, dwExtraInfo=None
    )
    return user32.SendInput(1, ctypes.byref(events), ctypes.sizeof(INPUT)) == 1


def send_mouse(flags: int) -> bool:
    """发一条鼠标事件（按下/抬起），用于自检模拟拖选。"""

    if not IS_WINDOWS:
        return False
    events = (INPUT * 1)()
    events[0].type = 0  # INPUT_MOUSE
    events[0].mi = MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=None)
    return user32.SendInput(1, ctypes.byref(events), ctypes.sizeof(INPUT)) == 1


class ClipboardWatcher(threading.Thread):
    """轮询剪贴板序号，变化时把新文本回调出去（自动划词用）。"""

    def __init__(self, on_change: Callable[[str], None], interval: float = 0.25):
        super().__init__(daemon=True, name="lumen-clipboard")
        self.on_change = on_change
        self.interval = interval
        self.paused = False
        self.last_sequence = clipboard_sequence()
        self.last_text = ""
        self._stopping = False

    def run(self) -> None:
        while not self._stopping:
            time.sleep(self.interval)
            if self.paused:
                continue
            sequence = clipboard_sequence()
            if sequence == self.last_sequence:
                continue
            self.last_sequence = sequence
            text = read_clipboard_text().strip()
            if not text or text == self.last_text:
                continue
            self.last_text = text
            try:
                self.on_change(text)
            except Exception:
                pass

    def note_own_write(self, text: str) -> None:
        """我们自己写剪贴板时记一笔，免得被自己的复制动作触发。"""

        self.last_sequence = clipboard_sequence()
        self.last_text = text.strip()

    def stop(self) -> None:
        self._stopping = True


def selftest_structures() -> list[tuple[str, bool, str]]:
    """结构体尺寸自检：ctypes 定义写错了通常在这里现形。"""

    if not IS_WINDOWS:
        return [("非 Windows，跳过结构体检查", True, "")]
    pointer = ctypes.sizeof(ctypes.c_void_p)
    out: list[tuple[str, bool, str]] = []
    size = ctypes.sizeof(INPUT)
    out.append((f"INPUT 结构体尺寸（{pointer} 位）", size == (40 if pointer == 8 else 28), str(size)))
    nid_size = ctypes.sizeof(NOTIFYICONDATA)
    out.append(("NOTIFYICONDATA 尺寸合理", nid_size > 900, str(nid_size)))
    out.append(("NOTIFYICONDATA 字段偏移递增", NOTIFYICONDATA.hIcon.offset > NOTIFYICONDATA.uCallbackMessage.offset, str(NOTIFYICONDATA.hIcon.offset)))
    out.append(("KEYBDINPUT 已按指针对齐", ctypes.sizeof(KEYBDINPUT) == (24 if pointer == 8 else 16), str(ctypes.sizeof(KEYBDINPUT))))
    hook_size = ctypes.sizeof(MSLLHOOKSTRUCT)
    out.append(("MSLLHOOKSTRUCT 尺寸", hook_size == (32 if pointer == 8 else 24), str(hook_size)))
    out.append(("终端窗口类名表非空", len(CONSOLE_CLASSES) >= 3, str(len(CONSOLE_CLASSES))))
    return out
