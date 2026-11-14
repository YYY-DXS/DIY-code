"""划词翻译浮窗：贴着鼠标出现，带流式译文、复制、回到主窗口。"""

from __future__ import annotations

import os
import threading
import tkinter as tk

from . import engines, win32
from .theme import COLORS, Fonts
from .widgets import RoundedButton, StatusDot

MAX_SOURCE_CHARS = 400


class SelectionPopup(tk.Toplevel):
    """无边框浮窗。第一次 show 之后一直复用，避免反复创建窗口闪烁。"""

    WIDTH = 470
    HEIGHT = 344

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.cancel = threading.Event()
        self._busy = False
        self._last_text = ""
        self._last_result = ""
        self._dragging = False
        self._drag_offset = (0, 0)
        self._has_focus = True

        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=COLORS["border_hi"])
        self.attributes("-topmost", True)
        try:
            self.attributes("-toolwindow", True)
        except tk.TclError:
            pass

        inner = tk.Frame(self, bg=COLORS["surface"])
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.inner = inner

        self._build_header(inner)
        self._build_source(inner)
        self._build_result(inner)
        self._build_footer(inner)

        self.bind("<Escape>", lambda _e: self.hide())
        self.bind("<FocusOut>", self._on_focus_out)

    # ------------------------------------------------------------ 布局
    def _build_header(self, parent: tk.Frame) -> None:
        bar = tk.Frame(parent, bg=COLORS["surface"], height=34)
        bar.pack(fill="x", padx=12, pady=(10, 0))
        bar.pack_propagate(False)
        self.dot = StatusDot(bar, COLORS["accent"])
        self.dot.pack(side="left", pady=(8, 0))
        self.title_label = tk.Label(bar, text="划词翻译", bg=COLORS["surface"], fg=COLORS["text_dim"], font=(Fonts.ui, 10, "bold"))
        title = self.title_label
        title.pack(side="left", padx=(7, 0), pady=(6, 0))
        self.engine_label = tk.Label(bar, text="", bg=COLORS["surface"], fg=COLORS["text_mute"], font=Fonts.ui_sm)
        self.engine_label.pack(side="right", pady=(6, 0))

        close = tk.Canvas(bar, width=22, height=22, bg=COLORS["surface"], bd=0, highlightthickness=0, cursor="hand2")
        close.pack(side="right", padx=(8, 0), pady=(6, 0))
        close.create_line(7, 7, 15, 15, fill=COLORS["text_mute"], width=1)
        close.create_line(15, 7, 7, 15, fill=COLORS["text_mute"], width=1)
        close.bind("<Button-1>", lambda _e: self.hide())
        close.bind("<Enter>", lambda _e: close.itemconfigure("all", fill=COLORS["err"]))
        close.bind("<Leave>", lambda _e: close.itemconfigure("all", fill=COLORS["text_mute"]))

        for widget in (bar, title):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)

        tk.Frame(parent, bg=COLORS["border"], height=1).pack(fill="x", padx=12, pady=(8, 0))

    def _build_source(self, parent: tk.Frame) -> None:
        box = tk.Frame(parent, bg=COLORS["surface"])
        box.pack(fill="x", padx=12, pady=(8, 6))
        self.source_label = tk.Label(
            box,
            text="",
            bg=COLORS["surface"],
            fg=COLORS["text_mute"],
            font=Fonts.ui_sm,
            justify="left",
            anchor="w",
            wraplength=self.WIDTH - 48,
        )
        self.source_label.pack(fill="x")

    def _build_result(self, parent: tk.Frame) -> None:
        wrap = tk.Frame(parent, bg=COLORS["surface2"], highlightthickness=1, highlightbackground=COLORS["border"])
        wrap.pack(fill="both", expand=True, padx=12)
        self.result_text = tk.Text(
            wrap,
            bg=COLORS["surface2"],
            fg=COLORS["text"],
            relief="flat",
            bd=0,
            highlightthickness=0,
            wrap="word",
            font=(Fonts.ui, 12),
            padx=10,
            pady=8,
            spacing1=2,
            spacing3=4,
            selectbackground=COLORS["accent_dk"],
            selectforeground=COLORS["accent_hi"],
            height=3,
        )
        self.result_text.pack(fill="both", expand=True)
        self.result_text.tag_configure("hint", foreground=COLORS["text_mute"])
        self.result_text.tag_configure("error", foreground=COLORS["err"])
        self.result_text.configure(state="disabled")

    def _build_footer(self, parent: tk.Frame) -> None:
        bar = tk.Frame(parent, bg=COLORS["surface"])
        bar.pack(fill="x", padx=12, pady=(8, 10))
        self.status = tk.Label(bar, text="", bg=COLORS["surface"], fg=COLORS["text_mute"], font=Fonts.ui_sm)
        self.status.pack(side="left")
        RoundedButton(bar, "复制", self.copy_result, variant="ghost", width=58, height=27, font=Fonts.ui_sm).pack(side="right")
        RoundedButton(bar, "主窗口", self.open_main, variant="subtle", width=70, height=27, font=Fonts.ui_sm).pack(
            side="right", padx=(0, 6)
        )
        RoundedButton(bar, "重译", self.retranslate, variant="subtle", width=58, height=27, font=Fonts.ui_sm).pack(
            side="right", padx=(0, 6)
        )

    # ------------------------------------------------------------ 拖动
    def _drag_start(self, event) -> None:
        self._dragging = True
        self._drag_offset = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())

    def _drag_move(self, event) -> None:
        if self._dragging:
            self.geometry(f"+{event.x_root - self._drag_offset[0]}+{event.y_root - self._drag_offset[1]}")

    def _on_focus_out(self, _event=None) -> None:
        # 不抢焦点的浮窗走"鼠标点到别处关闭"，这条不适用
        if self._has_focus and getattr(self.app.cfg, "popup_auto_close", True):
            self.after(180, self._close_if_unfocused)

    def _close_if_unfocused(self) -> None:
        if not self.winfo_exists() or not self.winfo_viewable():
            return
        focused = self.focus_displayof()
        if focused is None:
            return
        try:
            if focused.winfo_toplevel() is self:
                return
        except Exception:
            pass
        self.hide()

    # ------------------------------------------------------------ 显示 / 翻译
    def show_at_cursor(self, steal_focus: bool = True) -> None:
        left, top, right, bottom = win32.work_area()
        x, y = win32.cursor_position()
        x = min(max(x - 40, left + 8), right - self.WIDTH - 8)
        y = min(max(y + 18, top + 8), bottom - self.HEIGHT - 8)
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        # 自动划词弹窗不抢焦点：否则你紧接着打字会被浮窗吃掉。
        # 这种模式下由鼠标钩子负责"点到别处就关"。
        self._has_focus = bool(steal_focus)
        if steal_focus:
            self.focus_force()

    def hide(self) -> None:
        self.cancel.set()
        self.withdraw()

    def show_translation(
        self,
        text: str,
        detected_from: str | None = None,
        steal_focus: bool = True,
        title: str = "划词翻译",
    ) -> None:
        text = text.strip()
        if not text:
            return
        self.cancel.set()  # 取消上一次
        self.cancel = threading.Event()
        self._last_text = text
        self._last_result = ""

        source = text if len(text) <= MAX_SOURCE_CHARS else text[:MAX_SOURCE_CHARS] + " …"
        self.title_label.configure(text=title)
        self.source_label.configure(text=source.replace("\n", " "))
        self._set_result("翻译中…", tag="hint")
        self.engine_label.configure(text=engines.EngineRunner(self.app.cfg).label)
        self.status.configure(text="", fg=COLORS["text_mute"])
        self.dot.set_color(COLORS["accent"])
        self.dot.start_pulse()
        self.show_at_cursor(steal_focus=steal_focus)

        cfg = self.app.cfg
        if getattr(cfg, "popup_smart_target", True):
            dst = "en" if engines.looks_chinese(text) else cfg.target_lang
            if dst == cfg.target_lang and engines.looks_chinese(text) and cfg.target_lang == "en":
                dst = "zh-CN"
        else:
            dst = cfg.target_lang
        src = detected_from or "auto"

        self._busy = True
        threading.Thread(target=self._worker, args=(text, src, dst), daemon=True).start()

    def retranslate(self) -> None:
        if self._last_text:
            self.show_translation(self._last_text)

    def show_error(self, message: str, title: str = "划词翻译") -> None:
        """识别/翻译失败时也给个浮窗，别让人以为没反应。"""

        self._busy = False
        self._last_text = ""
        self._last_result = ""
        self.title_label.configure(text=title)
        self.source_label.configure(text="")
        self.dot.stop_pulse()
        self.dot.set_color(COLORS["err"])
        self.engine_label.configure(text="")
        self.status.configure(text="失败", fg=COLORS["err"])
        self.show_at_cursor(steal_focus=True)
        self._set_result(message, tag="error")

    def show_pair(self, original: str, translated: str, title: str = "划词翻译", engine_label: str = "") -> None:
        """直接把「原文 + 译文」摆上去（AI 视觉模式已经两边都有了）。"""

        self.cancel.set()
        self.cancel = threading.Event()
        self._busy = False
        self._last_text = original.strip() or translated.strip()
        self._last_result = translated.strip()
        self.title_label.configure(text=title)
        source = self._last_text if len(self._last_text) <= MAX_SOURCE_CHARS else self._last_text[:MAX_SOURCE_CHARS] + " …"
        self.source_label.configure(text=source.replace("\n", " "))
        self.engine_label.configure(text=engine_label or f"AI · {self.app.cfg.ai_model}")
        self.status.configure(text=f"{len(translated)} 字符", fg=COLORS["text_mute"])
        self.dot.stop_pulse()
        self.dot.set_color(COLORS["ok"])
        self.show_at_cursor(steal_focus=True)
        self._set_result(translated)
        if os.environ.get("LUMEN_DEBUG"):
            import sys

            print(f"[popup-geom] {self.winfo_geometry()}", file=sys.stderr, flush=True)
            print(
                f"[popup-done] {engine_label or 'pair'} len={len(translated)} {translated[:50]!r}",
                file=sys.stderr,
                flush=True,
            )

    def contains_point(self, x: int, y: int) -> bool:
        if not self.winfo_exists() or not self.winfo_viewable():
            return False
        px, py = self.winfo_rootx(), self.winfo_rooty()
        return px <= x <= px + self.winfo_width() and py <= y <= py + self.winfo_height()

    def copy_result(self) -> None:
        text = self._last_result
        if not text:
            return
        self.app.copy_to_clipboard(text)
        self.status.configure(text="已复制", fg=COLORS["ok"])

    def open_main(self) -> None:
        self.hide()
        self.app.show_window()
        if self._last_text:
            self.app.input_text.delete("1.0", "end")
            self.app.input_text.insert("1.0", self._last_text)
            self.app._on_input_change()
            if self._last_result:
                self.app.output_text.delete("1.0", "end")
                self.app.output_text.insert("1.0", self._last_result)

    # ------------------------------------------------------------ 后台
    def _worker(self, text: str, src: str, dst: str) -> None:
        runner = engines.EngineRunner(self.app.cfg)
        try:
            result = runner.translate(text, src, dst, cancel=self.cancel, on_delta=self._on_delta)
        except engines.EngineError as exc:
            self.app._post(lambda: self._on_error(str(exc), cancelled=str(exc) == "已取消"))
            return
        except Exception as exc:
            self.app._post(lambda: self._on_error(f"{type(exc).__name__}: {exc}"))
            return
        self.app._post(lambda: self._on_done(result))

    def _on_delta(self, partial: str) -> None:
        self.app._post(lambda: self._set_result(partial))

    def _on_done(self, result: engines.Result) -> None:
        self._busy = False
        self.dot.stop_pulse()
        self.dot.set_color(COLORS["ok"])
        self._last_result = result.text
        self._set_result(result.text)
        self.engine_label.configure(text=result.engine)
        self.status.configure(text=f"{result.latency_ms} ms · {len(result.text)} 字符", fg=COLORS["text_mute"])
        if os.environ.get("LUMEN_DEBUG"):
            import sys

            print(
                f"[popup-done] {result.engine} {result.latency_ms}ms len={len(result.text)} {result.text[:50]!r}",
                file=sys.stderr,
                flush=True,
            )
        self.app.remember_translation(result, self._last_text, result.engine)

    def _on_error(self, message: str, cancelled: bool = False) -> None:
        self._busy = False
        self.dot.stop_pulse()
        if cancelled:
            return
        self.dot.set_color(COLORS["err"])
        self._set_result("翻译失败\n" + message, tag="error")
        self.status.configure(text="失败", fg=COLORS["err"])

    def _set_result(self, text: str, tag: str | None = None) -> None:
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", text, tag or ())
        self.result_text.configure(state="disabled")
