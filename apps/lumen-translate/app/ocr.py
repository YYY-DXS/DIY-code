"""Windows 自带 OCR 的封装（走 PowerShell + WinRT，不装任何东西）。

PowerShell 冷启动要 3 秒以上，所以这里维护一个**常驻助手进程**：
应用启动时后台预热，之后每张图只要 100~400 毫秒。
"""

from __future__ import annotations

import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HELPER = Path(__file__).with_name("ocr_helper.ps1")
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Windows OCR 会在每个汉字之间插空格，还可能在标点前留空格
_CJK = r"\u3000-\u303f\u4e00-\u9fff\uff00-\uffef"
_CJK_SPACE = re.compile(rf"(?<=[{_CJK}])[ \t]+(?=[{_CJK}])")
_SPACE_BEFORE_CJK_PUNCT = re.compile(rf"[ \t]+(?=[\u3000-\u303f\uff01-\uff65])")


def clean_text(raw: str) -> str:
    """把 OCR 的原始输出收拾成人能读的样子。

    Windows 的中文 OCR 会输出"桌 面 翻 译"，逐字之间带空格；英文单词之间
    的空格必须保留。所以只删"汉字/中文标点之间"的空格。
    """

    lines: list[str] = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.strip()
        if not line:
            lines.append("")
            continue
        line = _CJK_SPACE.sub("", line)
        line = _SPACE_BEFORE_CJK_PUNCT.sub("", line)
        lines.append(line)
    # 去掉首尾空行，中间连续空行压成一个
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    out: list[str] = []
    for line in lines:
        if not line and out and not out[-1]:
            continue
        out.append(line)
    return "\n".join(out)


def powershell_path() -> str | None:
    """找 powershell.exe：优先 Windows PowerShell 5.1（默认是 FullLanguage）。"""

    for name in ("powershell.exe", "powershell", "pwsh.exe", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    return None


class OcrEngine:
    """常驻 OCR 助手进程。线程安全（内部加锁），失败会自动重启一次。"""

    def __init__(self, language: str = "", timeout: float = 15.0):
        self.language = language
        self.timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._lines: queue.Queue[str] = queue.Queue()
        self.ready = threading.Event()
        self.started = False
        self.error = ""
        self.language_tag = ""
        self._reader: threading.Thread | None = None

    # -- 生命周期 --------------------------------------------------------
    def start(self) -> bool:
        if self.started:
            return True
        if not HELPER.exists():
            self.error = f"找不到 OCR 助手脚本：{HELPER}"
            return False
        exe = powershell_path()
        if not exe:
            self.error = "找不到 PowerShell，没法调用 Windows OCR"
            return False
        args = [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HELPER), "-Serve"]
        if self.language:
            args += ["-Language", self.language]
        try:
            self._proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as exc:
            self.error = f"启动 OCR 助手失败：{exc}"
            return False
        self._reader = threading.Thread(target=self._pump, daemon=True, name="lumen-ocr-reader")
        self._reader.start()
        if not self.ready.wait(self.timeout):
            self.error = self.error or "OCR 助手启动超时"
            self.stop()
            return False
        self.started = True
        return True

    def _pump(self) -> None:
        """把助手进程的每一行输出塞进队列（读管道没法设置超时，只能另开线程）。"""

        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.rstrip("\r\n")
            if line.startswith("ready"):
                self.language_tag = line[5:].strip()
                self.ready.set()
                continue
            if line.startswith("err") and not self.started:
                # 启动阶段就报错（比如没有 OCR 语言包）：别让 start() 干等超时
                self.error = line[3:].strip()
                self.ready.set()
                continue
            self._lines.put(line)
        self._lines.put("__eof__")
        self.ready.set()  # 进程没了也别让 start() 死等

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        self.started = False
        self.ready.clear()
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.write("quit\n")
                proc.stdin.flush()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # -- 识别 ------------------------------------------------------------
    def recognize(self, image_path: str | Path, out_path: str | Path | None = None) -> str:
        """OCR 一张图片，返回清理过的文本。"""

        image_path = Path(image_path)
        out_path = Path(out_path) if out_path else image_path.with_suffix(".ocr.txt")
        with self._lock:
            for attempt in (1, 2):
                if not self.started or self._proc is None or self._proc.poll() is not None:
                    # 第一次或进程死了：重启（并把队列里残留的行丢掉）
                    self._drain()
                    if not self.start():
                        raise OcrError(self.error or "OCR 助手没能启动")
                try:
                    return self._request(image_path, out_path)
                except OcrTimeout:
                    if attempt == 2:
                        raise
                    self.stop()
            raise OcrError("OCR 失败")

    def _request(self, image_path: Path, out_path: Path) -> str:
        assert self._proc is not None and self._proc.stdin is not None
        if out_path.exists():
            try:
                out_path.unlink()
            except OSError:
                pass
        try:
            self._proc.stdin.write(f"{image_path}|{out_path}\n")
            self._proc.stdin.flush()
        except Exception as exc:
            raise OcrError(f"OCR 助手写入失败：{exc}") from exc

        deadline = time.time() + self.timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise OcrTimeout("OCR 超时")
            try:
                line = self._lines.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue
            if line == "__eof__":
                raise OcrError("OCR 助手进程退出了")
            if line.startswith("ok"):
                break
            if line.startswith("err"):
                raise OcrError(line[4:].strip() or "OCR 失败")
            # ready / 其它杂音，忽略
        try:
            raw = out_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise OcrError(f"读不到 OCR 结果文件：{exc}") from exc
        finally:
            try:
                out_path.unlink()
            except OSError:
                pass
        return clean_text(raw)

    def _drain(self) -> None:
        while True:
            try:
                self._lines.get_nowait()
            except queue.Empty:
                return

    # -- 自检用 ----------------------------------------------------------
    @staticmethod
    def available_languages(timeout: float = 30.0) -> list[str]:
        exe = powershell_path()
        if not exe:
            return []
        result = subprocess.run(
            [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HELPER), "-ListLanguages"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]


class OcrError(RuntimeError):
    pass


class OcrTimeout(OcrError):
    pass
