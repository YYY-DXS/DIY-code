"""Lumen 译 入口。双击运行 / pythonw main.pyw。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tkinter as tk  # noqa: E402

from app import APP_NAME, win32  # noqa: E402
from app.theme import enable_dpi_awareness  # noqa: E402
from app.ui import LumenApp  # noqa: E402


def main() -> int:
    enable_dpi_awareness()
    if not win32.acquire_single_instance():
        # 两个实例会抢同一套全局快捷键和托盘图标，第二个直接提示退出
        win32.message_box(f"{APP_NAME} 已经在运行了", f"{APP_NAME} 已经在后台运行。\n\n看看系统托盘里的图标，单击它就能把窗口调出来。")
        return 0
    root = tk.Tk()
    LumenApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
