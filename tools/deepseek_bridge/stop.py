#!/usr/bin/env python3
"""停掉正在运行的同步桥服务。"""

import ctypes
import subprocess
import sys
import time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
PROCESS_TERMINATE = 0x0001


def listening_pids() -> set[str]:
    out = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True, check=False
    ).stdout
    return {
        line.split()[-1]
        for line in out.splitlines()
        if f":{PORT}" in line and "LISTENING" in line and line.split()
    }


def terminate(pid: str) -> bool:
    """优先用系统调用结束进程，taskkill 在受限环境下可能被拦。"""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
    if not handle:
        return False
    try:
        kernel32.TerminateProcess(handle, 1)
    finally:
        kernel32.CloseHandle(handle)
    return True


pids = listening_pids()
if not pids:
    print(f"端口 {PORT} 上没有正在运行的同步桥。")
    raise SystemExit(0)

for pid in sorted(pids):
    ok = terminate(pid)
    print(f"已停止同步桥（PID {pid}）" if ok else f"停止失败（PID {pid}）")

time.sleep(1)
left = listening_pids()
if left:
    print(f"⚠ 端口 {PORT} 仍在监听：{', '.join(sorted(left))}，可能需要管理员权限")
    raise SystemExit(1)
print(f"端口 {PORT} 已释放。")
