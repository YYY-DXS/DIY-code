"""主窗口：双栏对照、流式输出、引擎切换、设置与历史。"""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import os
from tkinter import ttk

from . import APP_NAME
from . import config as config_mod
from . import capture, engines, history, icon, ocr, win32
from .floatwin import SelectionPopup
from .theme import COLORS, Fonts, apply_dark_titlebar, apply_ttk_theme
from .widgets import (
    Card,
    GradientRule,
    GridBackdrop,
    RoundedButton,
    StatusDot,
    SwapButton,
    ToggleSwitch,
    lerp_color,
    rounded_points,
)


def dark_entry(master: tk.Misc, textvariable: tk.StringVar, width: int = 30, show: str | None = None) -> tk.Entry:
    entry = tk.Entry(
        master,
        textvariable=textvariable,
        width=width,
        bg=COLORS["surface2"],
        fg=COLORS["text"],
        insertbackground=COLORS["accent"],
        relief="flat",
        highlightthickness=1,
        highlightbackground=COLORS["border"],
        highlightcolor=COLORS["accent_dk"],
        font=Fonts.ui_md,
        show=show or "",
    )
    entry.configure(disabledbackground=COLORS["surface3"], disabledforeground=COLORS["text_mute"])
    return entry


def section_label(master: tk.Misc, text: str) -> tk.Label:
    return tk.Label(master, text=text, bg=master["bg"], fg=COLORS["text_mute"], font=Fonts.ui_sm, anchor="w")


class LumenApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        Fonts.init(root)
        self.cfg = config_mod.load()
        self.cancel = threading.Event()
        self._busy = False
        self._auto_after: str | None = None
        self._last_src = ""
        self._stream_buffer = ""
        self._stream_lock = threading.Lock()
        self._stream_dirty = False
        self._ui_queue: queue.Queue = queue.Queue()

        root.title(APP_NAME)
        root.configure(bg=COLORS["bg"])
        root.minsize(920, 600)
        root.geometry(self.cfg.geometry or "1120x720")
        apply_ttk_theme(root)
        self._apply_icon()

        self.source_names = [f"{name}" for name in engines.SOURCE_LANGUAGES.values()]
        self.source_codes = list(engines.SOURCE_LANGUAGES.keys())
        self.target_names = [f"{name}" for name in engines.TARGET_LANGUAGES.values()]
        self.target_codes = list(engines.TARGET_LANGUAGES.keys())

        self._build_header()
        self._build_body()
        self._build_actionbar()
        self._build_statusbar()

        self._bind_keys()
        self._sync_engine_buttons()
        self.auto_toggle.set(self.cfg.auto_translate)
        self.top_toggle.set(self.cfg.always_on_top)
        root.attributes("-topmost", bool(self.cfg.always_on_top))
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(80, lambda: apply_dark_titlebar(root))
        root.after(200, lambda: self.input_text.focus_set())
        root.after(30, self._drain_queue)
        root.after(120, self._maybe_demo)

        # 托盘 / 全局快捷键 / 剪贴板监听
        self.popup: SelectionPopup | None = None
        self.tray: win32.TrayIcon | None = None
        self.hotkeys: win32.HotkeyListener | None = None
        self.watcher: win32.ClipboardWatcher | None = None
        self.mouse_hook: win32.SelectionMouseHook | None = None
        self.ocr: ocr.OcrEngine | None = None
        self.ocr_ready = False
        self._shot_busy = False
        self._shot_restore = False
        self.hotkey_errors: list[str] = []
        self._tray_notified = False
        self._quitting = False
        self._visible = True
        self._last_instant_text = ""
        self._last_instant_time = 0.0
        self._instant_busy = False
        root.after(300, self._init_integrations)

    # ------------------------------------------------------------ 托盘 / 热键
    def _init_integrations(self) -> None:
        self._start_watcher()
        self._refresh_hint()
        # 托盘和热键线程的 ready 必须等，但绝不能在 Tk 主线程里等：
        # 主线程一阻塞，窗口/浮窗就没法绘制（曾经因此白等好几秒）
        threading.Thread(target=self._start_workers, daemon=True).start()

    def _start_workers(self) -> None:
        messages: list[str] = []
        self._start_tray(messages)
        self._start_hotkeys(messages)
        self._start_mouse_hook(messages)
        self._warm_ocr(messages)
        for message in messages:
            self._post(lambda m=message: self.set_status(m, COLORS["warn"]))

    def _warm_ocr(self, messages: list[str] | None = None) -> None:
        """后台把 OCR 助手进程拉起来（PowerShell 冷启动 3 秒以上，别等到用的时候才启动）。"""

        if self.ocr is None:
            self.ocr = ocr.OcrEngine(self.cfg.ocr_language)
        ok = self.ocr.start()
        self.ocr_ready = ok
        if not ok and messages is not None:
            messages.append(f"截图翻译不可用：{self.ocr.error}")

    def _start_watcher(self) -> None:
        if self.watcher is not None:
            return
        self.watcher = win32.ClipboardWatcher(self._on_clipboard_change)
        self.watcher.start()

    def _start_tray(self, messages: list[str] | None = None) -> None:
        if not self.cfg.enable_tray or self.tray is not None:
            return
        try:
            paths = icon.ensure_assets()
            self.tray = win32.TrayIcon(
                paths["ico"],
                f"{APP_NAME} · 划词翻译已就绪",
                on_activate=lambda: self._post(self.toggle_window),
                menu_provider=self._tray_menu,
            )
            self.tray.start()
            self.tray.ready.wait(timeout=5)
            if not self.tray.ok:
                if messages is not None:
                    messages.append(f"托盘图标没加上：{self.tray.error}")
                self.tray = None
        except Exception as exc:
            self.tray = None
            if messages is not None:
                messages.append(f"托盘初始化失败：{exc}")

    def _stop_tray(self) -> None:
        if self.tray is not None:
            self.tray.stop()
            self.tray = None

    def _tray_menu(self) -> list:
        # 这个方法会在托盘线程里被调用，所以只能用纯 Python 状态，不能碰 Tk
        visible = self._visible
        return [
            (1, "隐藏主窗口" if visible else "显示主窗口", False, True, lambda: self._post(self.toggle_window)),
            (2, f"划词翻译（{win32.format_hotkey(self.cfg.hotkey_select)}）", False, True, lambda: self._post(self.translate_selection)),
            (3, f"翻译剪贴板（{win32.format_hotkey(self.cfg.hotkey_clipboard)}）", False, True, lambda: self._post(self.translate_clipboard)),
            (9, f"截图翻译（{win32.format_hotkey(self.cfg.hotkey_shot)}）", False, True, lambda: self._post(self.start_screenshot_translate)),
            None,
            (4, "复制即翻译（自动划词）", bool(self.cfg.auto_select_popup), True, lambda: self._post(self.toggle_auto_select)),
            (8, "选中即翻译（拖选/双击自动弹窗）", bool(self.cfg.select_instant), True, lambda: self._post(self.toggle_select_instant)),
            (5, "系统托盘", bool(self.cfg.enable_tray), True, lambda: self._post(self.toggle_tray)),
            None,
            (6, "设置", False, True, lambda: self._post(self.open_settings)),
            (7, "退出 Lumen 译", False, True, lambda: self._post(self.quit_app)),
        ]

    def _start_hotkeys(self, messages: list[str] | None = None) -> None:
        if not self.cfg.hotkeys_enabled or self.hotkeys is not None:
            return
        bindings = [
            win32.HotkeyBinding(self.cfg.hotkey_select, lambda: self._post(self.translate_selection)),
            win32.HotkeyBinding(self.cfg.hotkey_clipboard, lambda: self._post(self.translate_clipboard)),
            win32.HotkeyBinding(self.cfg.hotkey_show, lambda: self._post(self.toggle_window)),
            win32.HotkeyBinding(self.cfg.hotkey_shot, lambda: self._post(self.start_screenshot_translate)),
        ]
        self.hotkey_errors.clear()
        self.hotkeys = win32.HotkeyListener(bindings, on_error=self.hotkey_errors.append)
        self.hotkeys.start()
        self.hotkeys.ready.wait(timeout=5)
        self.hotkey_bindings = bindings
        failed = [b for b in bindings if not b.registered]
        if failed and messages is not None:
            first = failed[0]
            messages.append(f"快捷键 {win32.format_hotkey(first.spec)} 不可用：{first.error}")

    def _stop_hotkeys(self) -> None:
        if self.hotkeys is not None:
            self.hotkeys.stop()
            self.hotkeys = None

    # ------------------------------------------------------------ 选中即翻译
    def _start_mouse_hook(self, messages: list[str] | None = None) -> None:
        """装上低层鼠标钩子，用来识别"拖选一段"和"双击选词"。"""

        if not self.cfg.select_instant or self.mouse_hook is not None:
            return
        try:
            self.mouse_hook = win32.SelectionMouseHook(
                on_select=lambda x, y: self._post(lambda: self._on_instant_select(x, y)),
                on_click=lambda x, y: self._post(lambda: self._dismiss_popup_at(x, y)),
                min_drag=int(self.cfg.select_min_drag),
                double_click=bool(self.cfg.select_double_click),
                skip_own_process=True,
                skip_console=bool(self.cfg.select_skip_console),
            )
            self.mouse_hook.start()
            self.mouse_hook.ready.wait(timeout=5)
            if not self.mouse_hook.ok:
                if messages is not None:
                    messages.append(f"选中即翻译没装上：{self.mouse_hook.error}")
                self.mouse_hook = None
        except Exception as exc:
            self.mouse_hook = None
            if messages is not None:
                messages.append(f"选中即翻译初始化失败：{exc}")

    def _stop_mouse_hook(self) -> None:
        if self.mouse_hook is not None:
            self.mouse_hook.stop()
            self.mouse_hook = None

    def _on_instant_select(self, x: int, y: int) -> None:
        """鼠标松开那一刻：稍微等目标程序把选区定下来，再去取词。"""

        if not self.cfg.select_instant or self._quitting:
            return
        if getattr(self, "_instant_busy", False):
            return  # 上一次取词还没结束，别叠在一起
        self._instant_busy = True
        threading.Thread(target=self._instant_worker, args=(x, y), daemon=True).start()

    def _instant_worker(self, x: int, y: int) -> None:
        try:
            time.sleep(0.18)
            text = self._grab_selection(restore=bool(self.cfg.select_restore_clipboard), quiet=True)
        finally:
            self._instant_busy = False
        if not text or not any(ch.isalnum() for ch in text):
            return
        if len(text) > 3000:
            return
        now = time.time()
        if text == self._last_instant_text and now - self._last_instant_time < 4.0:
            return  # 同一个词反复选，不重复弹
        self._last_instant_text = text
        self._last_instant_time = now
        # 自动弹窗不抢焦点，免得你接着打字被吃掉
        self._post(lambda: self.show_popup(text, steal_focus=False))

    def _dismiss_popup_at(self, x: int, y: int) -> None:
        """鼠标点到浮窗外面就把浮窗收起来（不抢焦点的弹窗只能这么关）。"""

        popup = self.popup
        if popup is None or not popup.winfo_exists() or not popup.winfo_viewable():
            return
        if not popup.contains_point(x, y):
            popup.hide()

    def restart_integrations(self) -> None:
        """设置改过之后重新起一遍托盘/热键。"""

        self._stop_hotkeys()
        self._stop_tray()
        self._stop_mouse_hook()
        self._refresh_hint()
        threading.Thread(target=self._start_workers, daemon=True).start()

    def _refresh_hint(self) -> None:
        prefix = "选中即译 · " if self.cfg.select_instant else ""
        if self.cfg.hotkeys_enabled:
            text = (
                f"{win32.format_hotkey(self.cfg.hotkey_select)} 划词 · "
                f"{win32.format_hotkey(self.cfg.hotkey_shot)} 截图 · "
                f"{win32.format_hotkey(self.cfg.hotkey_show)} 显隐"
            )
        else:
            text = "Ctrl+Enter 翻译 · Esc 停止 · Ctrl+H 历史"
        self.hint_label.configure(text=prefix + text)

    # ------------------------------------------------------------ 窗口显隐
    def show_window(self) -> None:
        self._visible = True
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.root.attributes("-topmost", bool(self.cfg.always_on_top))

    def hide_window(self) -> None:
        self._visible = False
        self.root.withdraw()

    def toggle_window(self) -> None:
        if self._visible:
            self.hide_window()
        else:
            self.show_window()

    def toggle_tray(self) -> None:
        self.cfg.enable_tray = not self.cfg.enable_tray
        config_mod.save(self.cfg)
        if self.cfg.enable_tray:
            self._start_tray()
            self.set_status("系统托盘已开启", COLORS["ok"])
        else:
            self._stop_tray()
            self.set_status("系统托盘已关闭", COLORS["text_dim"])

    def toggle_auto_select(self) -> None:
        self.cfg.auto_select_popup = not self.cfg.auto_select_popup
        config_mod.save(self.cfg)
        if hasattr(self, "auto_select_toggle"):
            self.auto_select_toggle.set(self.cfg.auto_select_popup)
        self.set_status("复制即翻译已开启" if self.cfg.auto_select_popup else "复制即翻译已关闭", COLORS["ok"])

    def toggle_select_instant(self) -> None:
        self.cfg.select_instant = not self.cfg.select_instant
        config_mod.save(self.cfg)
        self._stop_mouse_hook()
        threading.Thread(target=self._start_mouse_hook, daemon=True).start()
        self.set_status(
            "选中即翻译已开启：拖选或双击选词就会弹窗" if self.cfg.select_instant else "选中即翻译已关闭",
            COLORS["ok"],
        )

    # ------------------------------------------------------------ 划词
    def translate_selection(self) -> None:
        """给前台窗口发 Ctrl+C，把选中文本捞出来翻译。"""

        if not win32.IS_WINDOWS:
            return
        self.set_status("正在读取选中文本…", COLORS["accent"])
        threading.Thread(target=self._selection_worker, daemon=True).start()

    def _grab_selection(self, restore: bool, quiet: bool) -> str:
        """给前台窗口发 Ctrl+C 把选中文本捞出来。

        restore=True 时读完会把剪贴板恢复成原样（自动划词用，免得悄悄动用户剪贴板）。
        quiet=True 时不弹状态提示（自动触发失败就该安静）。
        """

        previous = win32.read_clipboard_text()
        before = win32.clipboard_sequence()
        text = ""
        if self.watcher is not None:
            self.watcher.paused = True  # 期间我们自己动剪贴板，别让监听器跟着弹
        try:
            if not win32.send_ctrl_c():
                if not quiet:
                    self._post(lambda: self.set_status("没能发送 Ctrl+C，换个窗口再试", COLORS["warn"]))
                return ""
            for attempt in range(24):  # 最多等约 1.2 秒
                time.sleep(0.05)
                if win32.clipboard_sequence() != before:
                    text = win32.read_clipboard_text().strip()
                    break
                if attempt == 10:
                    win32.send_ctrl_c()  # 有些程序第一次没反应，补一次
        finally:
            if restore and previous:
                win32.write_clipboard_text(previous)
            if self.watcher is not None:
                self.watcher.paused = False
                self.watcher.note_own_write(previous if (restore and previous) else text)
        return text

    def _selection_worker(self) -> None:
        text = self._grab_selection(restore=False, quiet=False)
        if not text:
            self._post(lambda: self.set_status("没有选中文本（或当前程序不响应 Ctrl+C）", COLORS["warn"]))
            return
        self._post(lambda: self.show_popup(text))

    def translate_clipboard(self) -> None:
        text = win32.read_clipboard_text().strip()
        if not text:
            self.set_status("剪贴板里没有文本", COLORS["warn"])
            return
        self.show_popup(text)

    # ------------------------------------------------------------ 截图翻译
    def start_screenshot_translate(self) -> None:
        """框选屏幕一块区域，OCR 出来再翻译。"""

        if self._shot_busy:
            return
        self._shot_busy = True
        # 先把自己藏起来，否则主窗口/浮窗会被拍进截图里
        self._shot_restore = self._visible
        if self._visible:
            self.hide_window()
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.hide()
        self.set_status("框选要翻译的区域…（Esc 取消）", COLORS["accent"])
        # 留够时间让自己彻底从屏幕上消失，否则抓图会把刚藏起来的窗口拍进去
        self.root.after(420, self._open_region_selector)

    def _open_region_selector(self) -> None:
        pending = getattr(self, "_pending_region", None)
        if pending:  # 自动化/测试：区域是给定的，不用弹框选浮层
            self._pending_region = None
            self._on_region_selected(pending)
            return
        try:
            capture.RegionSelector(self.root, on_done=self._on_region_selected, on_cancel=self._on_region_cancelled)
        except Exception as exc:
            self._shot_busy = False
            self._restore_after_shot()
            self.set_status(f"打不开选区浮层：{exc}", COLORS["err"])

    def _on_region_cancelled(self) -> None:
        self._shot_busy = False
        self._restore_after_shot()
        self.set_status("已取消截图", COLORS["text_dim"])

    def _on_region_selected(self, bbox: tuple[int, int, int, int]) -> None:
        self._debug(f"[shot] region {bbox}")
        try:
            path = capture.grab_region(bbox)
        except Exception as exc:
            self._shot_busy = False
            self._restore_after_shot()
            self.set_status(f"截图失败：{exc}", COLORS["err"])
            return
        self._restore_after_shot()
        self.set_status("正在识别截图里的文字…", COLORS["accent"])
        threading.Thread(target=self._shot_worker, args=(path,), daemon=True).start()

    def _restore_after_shot(self) -> None:
        if self._shot_restore:
            self.show_window()
        self._shot_restore = False

    def _shot_worker(self, path) -> None:
        self._debug(f"[shot] captured {path}")
        runner = engines.EngineRunner(self.cfg)
        if runner.vision_available():
            self._debug("[shot] using AI vision")
            try:
                original, translated = runner.vision(path, self._current_langs()[1], cancel=self.cancel)
            except Exception as exc:
                self._debug(f"[shot] vision error: {exc}")
                self._post(lambda: self._shot_failed(f"AI 视觉识别失败\n\n{exc}"))
                self._shot_busy = False
                return
            self._shot_busy = False
            if not translated.strip():
                self._post(lambda: self._shot_failed("模型没返回译文，换个支持图片的模型再试。"))
                return
            self._post(lambda: self._shot_done_vision(original, translated))
            return
        try:
            if self.ocr is None:
                self.ocr = ocr.OcrEngine(self.cfg.ocr_language)
            # 屏幕小字是 ClearType 次像素渲染的，先对齐合成灰度再放大，英文才认得准
            prepared = capture.preprocess_for_ocr(path)
            self._debug(f"[shot] preprocessed {prepared.name}")
            text = self.ocr.recognize(prepared)
        except Exception as exc:
            self._debug(f"[shot] ocr error: {exc}")
            message = f"截图识别失败\n\n{exc}"
            self._post(lambda: self._shot_failed(message))
            return
        finally:
            self._shot_busy = False
        self._debug(f"[shot] ocr ok len={len(text)}")
        if not text.strip():
            self._post(lambda: self._shot_failed("这块区域里没认出文字。\n试试框得紧一点，或者避开纯图形区域。"))
            return
        self._post(lambda: self._shot_done(text))

    def _shot_done(self, text: str) -> None:
        self._debug(f"[shot] ocr text {text[:120]!r}")
        self.set_status(f"识别到 {len(text)} 个字符，正在翻译…", COLORS["accent"])
        # 截图内容常是中英混排：按语言分块，已经是目标语言的段落原样留着
        cfg = self.cfg
        dst = "en" if (cfg.popup_smart_target and engines.looks_chinese(text)) else cfg.target_lang
        if dst == cfg.target_lang and engines.looks_chinese(text) and cfg.target_lang == "en":
            dst = "zh-CN"
        threading.Thread(target=self._shot_translate_worker, args=(text, dst), daemon=True).start()

    def _shot_translate_worker(self, text: str, dst: str) -> None:
        runner = engines.EngineRunner(self.cfg)
        blocks = engines.split_language_blocks(text, dst)
        only_one = len(blocks) == 1
        out: list[str] = []
        engine_label = ""
        try:
            for needs, chunk in blocks:
                if not needs:
                    out.append(chunk)
                    continue
                # 单块时整段翻（上下文更完整）；多块时逐块翻
                result = runner.translate(
                    chunk, "auto", dst, cancel=self.cancel, on_delta=self._on_shot_delta if only_one else None
                )
                engine_label = engine_label or result.engine
                out.append(result.text)
        except engines.EngineError as exc:
            message = str(exc)
            self._post(lambda: self._shot_failed(message, cancelled=message == "已取消"))
            return
        except Exception as exc:
            self._post(lambda: self._shot_failed(f"{type(exc).__name__}: {exc}"))
            return
        merged = "\n".join(out).strip()
        self._post(lambda: self._shot_show_pair(text, merged, engine_label))

    def _on_shot_delta(self, partial: str) -> None:
        if self.popup is not None and self.popup.winfo_exists():
            self._post(lambda: self.popup._set_result(partial))

    def _shot_show_pair(self, original: str, translated: str, engine_label: str) -> None:
        self.set_status(f"截图翻译完成 · {engine_label or '已跳过翻译'}", COLORS["ok"])
        if self.popup is None or not self.popup.winfo_exists():
            self.popup = SelectionPopup(self)
        self.popup.show_pair(original, translated, title="截图翻译", engine_label=engine_label)

    def _shot_done_vision(self, original: str, translated: str) -> None:
        """AI 视觉模式：原文和译文一起来，直接塞进浮窗显示。"""

        self.set_status(f"AI 视觉识别完成 · {len(translated)} 字符", COLORS["ok"])
        if self.popup is None or not self.popup.winfo_exists():
            self.popup = SelectionPopup(self)
        self.popup.show_pair(original, translated, title="截图翻译 · AI 视觉")

    def _shot_failed(self, message: str, cancelled: bool = False) -> None:
        if cancelled:
            self.set_status("已取消", COLORS["warn"])
            return
        self.set_status(message.splitlines()[0], COLORS["err"])
        if self.popup is None or not self.popup.winfo_exists():
            self.popup = SelectionPopup(self)
        self.popup.show_error(message, title="截图翻译")

    def _debug(self, message: str) -> None:
        """LUMEN_DEBUG=1 时把关键步骤打到 stderr，方便自动化测试定位。"""

        if os.environ.get("LUMEN_DEBUG"):
            import sys

            print(message, file=sys.stderr, flush=True)

    def show_popup(self, text: str, steal_focus: bool = True, title: str = "划词翻译") -> None:
        if self.popup is None or not self.popup.winfo_exists():
            self.popup = SelectionPopup(self)
        self.popup.show_translation(text, steal_focus=steal_focus, title=title)
        if os.environ.get("LUMEN_DEBUG"):
            import sys

            self.popup.update_idletasks()
            print(f"[popup] {text[:60]!r} len={len(text)}", file=sys.stderr, flush=True)
            print(f"[popup-geom] {self.popup.winfo_geometry()}", file=sys.stderr, flush=True)

    def _on_clipboard_change(self, text: str) -> None:
        if not self.cfg.auto_select_popup:
            return
        if len(text) > 1500 or text.count("\n") > 12:
            return
        if not any(ch.isalpha() for ch in text):
            return
        self._post(lambda: self.show_popup(text))

    # ------------------------------------------------------------ 通用小工具
    def copy_to_clipboard(self, text: str) -> None:
        win32.write_clipboard_text(text)
        if self.watcher is not None:
            self.watcher.note_own_write(text)

    def remember_translation(self, result: engines.Result, source: str, label: str) -> None:
        src, dst = self._current_langs()
        history.append(
            history.Entry(
                ts=time.time(),
                engine=label or result.engine,
                source_lang=src,
                target_lang=dst,
                src=source,
                dst=result.text,
                latency_ms=result.latency_ms,
            )
        )

    def quit_app(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        try:
            if self.cfg.remember_geometry and self.root.winfo_viewable():
                self.cfg.geometry = self.root.geometry()
            config_mod.save(self.cfg)
        except Exception:
            pass
        self._stop_hotkeys()
        self._stop_mouse_hook()
        if self.watcher is not None:
            self.watcher.stop()
        self._stop_tray()
        if self.popup is not None:
            try:
                self.popup.destroy()
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _maybe_demo(self) -> None:
        """开发/截图用：设置 LUMEN_DEMO=1 时预填示例内容。"""

        import os
        import sys

        # 截图翻译的自动化钩子：直接给定屏幕区域，跳过框选浮层
        region = os.environ.get("LUMEN_SHOT_REGION")
        if region:
            def _auto_shot() -> None:
                try:
                    left, top, right, bottom = (int(v) for v in region.split(","))
                except ValueError:
                    return
                # 走真实流程：藏窗口 → 抓图 → OCR → 浮窗，只是跳过框选那一步
                self._debug(f"[shot] auto region {left},{top},{right},{bottom}")
                self._pending_region = (left, top, right, bottom)
                self.start_screenshot_translate()

            self.root.after(4000, _auto_shot)

        want = os.environ.get("LUMEN_OPEN", "")
        if want == "settings":
            self.open_settings()
        elif want == "history":
            self.open_history()
        elif want == "select":
            self.open_settings("select")

        if want:
            # 给截图脚本一个确定的坐标，省得它去猜是哪个窗口
            def _log_window_region() -> None:
                for child in self.root.winfo_children():
                    if isinstance(child, tk.Toplevel) and child.winfo_viewable():
                        print(
                            f"[region] {child.winfo_width()}x{child.winfo_height()}"
                            f"+{child.winfo_rootx()}+{child.winfo_rooty()}",
                            file=sys.stderr,
                            flush=True,
                        )
                        return
                print(
                    f"[region] {self.root.winfo_width()}x{self.root.winfo_height()}"
                    f"+{self.root.winfo_rootx()}+{self.root.winfo_rooty()}",
                    file=sys.stderr,
                    flush=True,
                )

            self.root.after(2000, _log_window_region)

        demo = os.environ.get("LUMEN_DEMO", "")
        if not demo:
            return
        if demo in ("popup", "popup-tray"):  # 截图/自检用：直接弹一个划词浮窗
            self.cfg.popup_auto_close = False  # 否则截图脚本抢焦点时它会自己关掉
            import sys

            if demo == "popup-tray":  # 模拟"窗口收进托盘后按快捷键"
                self.hide_window()

            def _show() -> None:
                self.show_popup(
                    "A good engine keeps the structure, the tone and every {placeholder} intact, "
                    "and it never touches your clipboard without asking."
                )
                self.popup.update_idletasks()
                print(
                    f"[region] {self.popup.winfo_width()}x{self.popup.winfo_height()}"
                    f"+{self.popup.winfo_rootx()}+{self.popup.winfo_rooty()}",
                    file=sys.stderr,
                    flush=True,
                )

            self.root.after(2500, _show)
            return
        sample_src = (
            "Translation is not just swapping words.\n"
            "A good engine keeps the structure, the tone and every {placeholder} intact.\n"
            "Type here, then press Ctrl+Enter."
        )
        self.input_text.insert("1.0", sample_src)
        self._on_input_change()
        if demo == "live":  # 走真实引擎，用来做端到端验证
            self.var_target.set("简体中文")
            self.root.after(300, self.translate)
            return
        sample_dst = (
            "翻译不只是替换词语。\n"
            "一个合格的引擎会保留结构、语气，以及每一个 {placeholder}。\n"
            "在这里输入内容，然后按 Ctrl+Enter。"
        )
        self.output_text.insert("1.0", sample_dst)
        self.detected_label.configure(text="英语")
        self.latency_label.configure(text="418 ms · 62 字符")
        self.engine_badge.configure(text="Google 免费线路")
        self.set_status("完成 · Google 免费线路 · 418 ms", COLORS["ok"])

    # ------------------------------------------------------------ 图标
    def _apply_icon(self) -> None:
        try:
            paths = icon.ensure_assets()
            self._icon_png = tk.PhotoImage(file=str(paths["png"]))
            self.root.iconphoto(True, self._icon_png)
            try:
                self.root.iconbitmap(default=str(paths["ico"]))
            except tk.TclError:
                pass
        except Exception:
            self._icon_png = None

    # ------------------------------------------------------------ 顶部
    def _build_header(self) -> None:
        header_h = 72
        header = tk.Frame(self.root, bg=COLORS["surface"], height=header_h)
        header.pack(fill="x", padx=14, pady=(12, 0))
        header.pack_propagate(False)
        GridBackdrop(header, height=header_h, step=24).place(x=0, y=0, relwidth=1, relheight=1)

        content = tk.Frame(header, bg=COLORS["surface"])
        content.place(x=0, y=0, relwidth=1, relheight=1)

        # 不设 pady，让 pack 自动垂直居中；两个标签加起来约 48px，低于此高度就会被裁掉
        left = tk.Frame(content, bg=COLORS["surface"])
        left.pack(side="left", padx=(16, 0))
        logo = tk.Canvas(left, width=34, height=34, bg=COLORS["surface"], bd=0, highlightthickness=0)
        logo.pack(side="left")
        self._draw_logo(logo)
        brand = tk.Frame(left, bg=COLORS["surface"])
        brand.pack(side="left", padx=(10, 0))
        tk.Label(brand, text="LUMEN", bg=COLORS["surface"], fg=COLORS["text"], font=(Fonts.ui, 15, "bold")).pack(anchor="w")
        tk.Label(
            brand,
            text="桌面翻译 · 在线 / AI 双引擎",
            bg=COLORS["surface"],
            fg=COLORS["text_mute"],
            font=Fonts.ui_sm,
        ).pack(anchor="w")

        right = tk.Frame(content, bg=COLORS["surface"])
        right.pack(side="right", padx=(0, 16))

        seg = tk.Frame(right, bg=COLORS["surface"])
        seg.pack(side="left")
        self.btn_engine_online = RoundedButton(seg, "在线", self._on_engine_online, variant="primary", width=76, height=32, font=Fonts.ui_bold)
        self.btn_engine_online.pack(side="left")
        self.btn_engine_ai = RoundedButton(seg, "AI", self._on_engine_ai, variant="ghost", width=76, height=32, font=Fonts.ui_bold)
        self.btn_engine_ai.pack(side="left", padx=(6, 0))

        tk.Frame(right, bg=COLORS["border"], width=1, height=22).pack(side="left", padx=12)

        RoundedButton(right, "历史", self.open_history, variant="subtle", width=68, height=32).pack(side="left")
        RoundedButton(right, "截图", self.start_screenshot_translate, variant="subtle", width=68, height=32).pack(
            side="left", padx=(6, 0)
        )
        RoundedButton(right, "设置", self.open_settings, variant="subtle", width=68, height=32).pack(side="left", padx=(6, 0))

        GradientRule(self.root, height=2).pack(fill="x", padx=14, pady=(0, 0))

    def _draw_logo(self, canvas: tk.Canvas) -> None:
        size = 34
        canvas.create_polygon(
            rounded_points(1, 1, size - 1, size - 1, 9, 6), fill=COLORS["surface3"], outline=COLORS["border_hi"],
        )
        for i, x0 in enumerate((9.0, 16.5)):
            color = lerp_color(COLORS["accent"], COLORS["violet"], i / 1.4)
            width = 3
            canvas.create_line(x0, 10, x0 + 6, 17, x0, 24, fill=color, width=width, capstyle="round", joinstyle="round")

    # ------------------------------------------------------------ 主体
    def _build_body(self) -> None:
        body = tk.Frame(self.root, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=14, pady=(12, 6))
        body.columnconfigure(0, weight=1, uniform="pane")
        body.columnconfigure(1, minsize=76)
        body.columnconfigure(2, weight=1, uniform="pane")
        body.rowconfigure(0, weight=1)

        self._build_source_pane(body)
        self._build_middle(body)
        self._build_result_pane(body)

    def _card_header(self, parent: tk.Misc, title: str, accent: str) -> tk.Frame:
        row = tk.Frame(parent, bg=COLORS["surface"])
        row.pack(fill="x", padx=14, pady=(12, 8))
        canvas = tk.Canvas(row, width=8, height=8, bg=COLORS["surface"], bd=0, highlightthickness=0)
        canvas.pack(side="left", pady=(2, 0))
        canvas.create_oval(0, 0, 8, 8, fill=accent, outline="")
        tk.Label(row, text=title, bg=COLORS["surface"], fg=COLORS["text_dim"], font=(Fonts.ui, 9, "bold")).pack(
            side="left", padx=(8, 0)
        )
        return row

    def _text_area(self, parent: tk.Misc) -> tuple[tk.Frame, tk.Text]:
        wrap = tk.Frame(parent, bg=COLORS["surface2"], highlightthickness=1, highlightbackground=COLORS["border"])
        wrap.pack(fill="both", expand=True, padx=14, pady=0)
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        text = tk.Text(
            wrap,
            bg=COLORS["surface2"],
            fg=COLORS["text"],
            insertbackground=COLORS["accent"],
            selectbackground=COLORS["accent_dk"],
            selectforeground=COLORS["accent_hi"],
            relief="flat",
            bd=0,
            highlightthickness=0,
            wrap="word",
            undo=True,
            maxundo=200,
            font=Fonts.editor,
            padx=14,
            pady=12,
            spacing1=3,
            spacing2=3,
            spacing3=6,
        )
        text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(wrap, orient="vertical", style="Lumen.Vertical.TScrollbar", command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns", padx=(0, 2), pady=4)
        text.configure(yscrollcommand=scroll.set)
        text.tag_configure("placeholder", foreground=COLORS["text_mute"])
        text.tag_configure("error", foreground=COLORS["err"])
        return wrap, text

    def _build_source_pane(self, body: tk.Frame) -> None:
        card = Card(body, radius=16)
        card.grid(row=0, column=0, sticky="nsew")
        card.body.columnconfigure(0, weight=1)
        row = self._card_header(card.body, "SOURCE 原文", COLORS["accent"])

        self.var_source = tk.StringVar(value=engines.SOURCE_LANGUAGES.get(self.cfg.source_lang, "自动检测"))
        combo = ttk.Combobox(
            row, textvariable=self.var_source, values=self.source_names, state="readonly", style="Lumen.TCombobox", width=17
        )
        combo.pack(side="right")
        self.detected_label = tk.Label(row, text="", bg=COLORS["surface"], fg=COLORS["accent"], font=Fonts.ui_sm)
        self.detected_label.pack(side="right", padx=(0, 10))

        card.body.rowconfigure(1, weight=1)
        _, self.input_text = self._text_area(card.body)

        footer = tk.Frame(card.body, bg=COLORS["surface"])
        footer.pack(fill="x", padx=14, pady=(8, 12))
        self.count_label = tk.Label(footer, text="0 字符", bg=COLORS["surface"], fg=COLORS["text_mute"], font=Fonts.ui_sm)
        self.count_label.pack(side="left")
        RoundedButton(footer, "粘贴", self.paste_input, variant="subtle", width=60, height=28, font=Fonts.ui_sm).pack(side="right")
        RoundedButton(footer, "清空", self.clear_all, variant="subtle", width=60, height=28, font=Fonts.ui_sm).pack(
            side="right", padx=(6, 0)
        )

        self.input_text.bind("<KeyRelease>", self._on_input_change)
        self.input_text.bind("<Control-a>", self._select_all)
        self.input_text.bind("<Button-3>", self._input_menu)

    def _build_middle(self, body: tk.Frame) -> None:
        mid = tk.Frame(body, bg=COLORS["bg"])
        mid.grid(row=0, column=1, sticky="nsew")
        inner = tk.Frame(mid, bg=COLORS["bg"])
        inner.place(relx=0.5, rely=0.5, anchor="center")
        self.btn_swap = SwapButton(inner, self.swap_languages, size=46)
        self.btn_swap.pack()
        tk.Label(inner, text="交换", bg=COLORS["bg"], fg=COLORS["text_mute"], font=Fonts.ui_sm).pack(pady=(8, 0))

    def _build_result_pane(self, body: tk.Frame) -> None:
        card = Card(body, radius=16)
        card.grid(row=0, column=2, sticky="nsew")
        card.body.columnconfigure(0, weight=1)
        row = self._card_header(card.body, "RESULT 译文", COLORS["violet"])
        self.engine_badge = tk.Label(row, text="在线翻译", bg=COLORS["surface"], fg=COLORS["text_dim"], font=Fonts.ui_sm)
        self.engine_badge.pack(side="right")

        self.var_target = tk.StringVar(value=engines.LANGUAGES.get(self.cfg.target_lang, "简体中文"))
        combo = ttk.Combobox(
            row, textvariable=self.var_target, values=self.target_names, state="readonly", style="Lumen.TCombobox", width=17
        )
        combo.pack(side="right", padx=(0, 12))

        card.body.rowconfigure(1, weight=1)
        _, self.output_text = self._text_area(card.body)

        footer = tk.Frame(card.body, bg=COLORS["surface"])
        footer.pack(fill="x", padx=14, pady=(8, 12))
        self.latency_label = tk.Label(footer, text="", bg=COLORS["surface"], fg=COLORS["text_mute"], font=Fonts.ui_sm)
        self.latency_label.pack(side="left")
        RoundedButton(footer, "复制", self.copy_output, variant="ghost", width=60, height=28, font=Fonts.ui_sm).pack(side="right")
        RoundedButton(footer, "重译", self.translate, variant="subtle", width=60, height=28, font=Fonts.ui_sm).pack(
            side="right", padx=(6, 0)
        )
        self.output_text.bind("<Control-a>", self._select_all)
        self.output_text.bind("<Button-3>", self._output_menu)

    # ------------------------------------------------------------ 操作条
    def _build_actionbar(self) -> None:
        bar = tk.Frame(self.root, bg=COLORS["bg"])
        bar.pack(fill="x", padx=14, pady=(0, 4))
        self.btn_translate = RoundedButton(bar, "翻译  ▸", self.translate, variant="primary", width=132, height=40, font=(Fonts.ui, 11, "bold"))
        self.btn_translate.pack(side="left")
        RoundedButton(bar, "AI 润色", self.polish_with_ai, variant="violet", width=92, height=40).pack(side="left", padx=(8, 0))

        right = tk.Frame(bar, bg=COLORS["bg"])
        right.pack(side="right")
        self.auto_toggle = ToggleSwitch(right, "自动翻译", self._on_auto_toggle, width=40)
        self.auto_toggle.pack(side="right", padx=(0, 4))
        self.top_toggle = ToggleSwitch(right, "窗口置顶", self._on_top_toggle, width=40)
        self.top_toggle.pack(side="right", padx=(0, 18))

    def _build_statusbar(self) -> None:
        bar = tk.Frame(self.root, bg=COLORS["bg"], height=24)
        bar.pack(fill="x", padx=14, pady=(0, 10))
        self.status_dot = StatusDot(bar, COLORS["ok"])
        self.status_dot.pack(side="left", pady=(4, 0))
        self.status_label = tk.Label(bar, text="就绪", bg=COLORS["bg"], fg=COLORS["text_dim"], font=Fonts.ui_sm)
        self.status_label.pack(side="left", padx=(6, 0))
        tk.Label(bar, text="v0.3 · 配置和密钥只存本机", bg=COLORS["bg"], fg=COLORS["text_mute"], font=Fonts.ui_sm).pack(
            side="right"
        )
        self.hint_label = tk.Label(bar, text="", bg=COLORS["bg"], fg=COLORS["text_mute"], font=Fonts.mono_xs)
        self.hint_label.pack(side="right", padx=(0, 14))
        self.hint_label.configure(text="Ctrl+Enter 翻译 · Esc 停止 · Ctrl+Shift+S 交换 · Ctrl+H 历史")

    # ------------------------------------------------------------ 快捷键
    def _bind_keys(self) -> None:
        self.root.bind("<Control-Return>", lambda _e: (self.translate(), "break")[1])
        self.root.bind("<F5>", lambda _e: (self.translate(), "break")[1])
        self.root.bind("<Escape>", lambda _e: self.cancel_request())
        self.root.bind("<Control-l>", lambda _e: self.clear_all())
        self.root.bind("<Control-h>", lambda _e: self.open_history())
        self.root.bind("<Control-comma>", lambda _e: self.open_settings())
        self.root.bind("<Control-Shift-S>", lambda _e: self.swap_languages())
        self.root.bind("<Control-Shift-C>", lambda _e: self.copy_output())
        self.root.bind("<Control-q>", lambda _e: self.quit_app())

    def _select_all(self, event):
        event.widget.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _input_menu(self, event) -> None:
        self._popup_menu(event, [("粘贴", self.paste_input), ("清空", self.clear_all), ("全选", lambda: self._select_all_for(self.input_text))])

    def _output_menu(self, event) -> None:
        self._popup_menu(event, [("复制", self.copy_output), ("全选", lambda: self._select_all_for(self.output_text))])

    def _select_all_for(self, widget: tk.Text) -> None:
        widget.tag_add("sel", "1.0", "end-1c")

    def _popup_menu(self, event, items) -> None:
        menu = tk.Menu(
            self.root, tearoff=0, bg=COLORS["surface3"], fg=COLORS["text"], activebackground=COLORS["accent_dk"],
            activeforeground=COLORS["accent_hi"], bd=0, font=Fonts.ui_md,
        )
        for label, command in items:
            menu.add_command(label=label, command=command)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ------------------------------------------------------------ 语言 / 引擎
    def _current_langs(self) -> tuple[str, str]:
        try:
            src = self.source_codes[self.source_names.index(self.var_source.get())]
        except ValueError:
            src = "auto"
        try:
            dst = self.target_codes[self.target_names.index(self.var_target.get())]
        except ValueError:
            dst = "zh-CN"
        return src, dst

    def swap_languages(self) -> None:
        src, dst = self._current_langs()
        if src == "auto":
            detected = self.detected_label.cget("text") or self.cfg.source_lang
            src = detected if detected in engines.TARGET_LANGUAGES else "en"
        new_src = dst if dst in engines.TARGET_LANGUAGES else "en"
        new_dst = src
        self.var_source.set(engines.SOURCE_LANGUAGES.get(new_src, new_src))
        self.var_target.set(engines.LANGUAGES.get(new_dst, new_dst))
        source_value = self.input_text.get("1.0", "end-1c")
        output_value = self.output_text.get("1.0", "end-1c")
        if output_value.strip():
            self.input_text.delete("1.0", "end")
            self.input_text.insert("1.0", output_value)
            self.output_text.delete("1.0", "end")
            self.output_text.insert("1.0", source_value)
        self._persist()

    def _on_engine_online(self) -> None:
        self.cfg.engine = "online"
        self._sync_engine_buttons()
        self._persist()
        self._schedule_auto()

    def _on_engine_ai(self) -> None:
        self.cfg.engine = "ai"
        self._sync_engine_buttons()
        self._persist()
        if not self.cfg.ai_key_resolved():
            self.set_status("AI 引擎还没接上：先填 API Key", COLORS["warn"])
            self.open_ai_wizard()
            return
        self._schedule_auto()

    def _sync_engine_buttons(self) -> None:
        online = self.cfg.engine == "online"
        self.btn_engine_online.set_variant("primary" if online else "ghost")
        self.btn_engine_ai.set_variant("ghost" if online else "primary")
        self.engine_badge.configure(text="在线翻译" if online else f"AI · {self.cfg.ai_model}")

    # ------------------------------------------------------------ 输入事件
    def _on_input_change(self, event=None) -> None:
        text = self.input_text.get("1.0", "end-1c")
        self.count_label.configure(text=f"{len(text)} 字符 · {len(text.splitlines())} 行")
        self._schedule_auto()
        if event is not None:
            return None

    def _schedule_auto(self) -> None:
        if self._auto_after:
            self.root.after_cancel(self._auto_after)
            self._auto_after = None
        if not self.cfg.auto_translate or self._busy:
            return
        text = self.input_text.get("1.0", "end-1c").strip()
        if not text or text == self._last_src:
            return
        self._auto_after = self.root.after(900, self._auto_fire)

    def _auto_fire(self) -> None:
        self._auto_after = None
        self.translate()

    def _on_auto_toggle(self, value: bool) -> None:
        self.cfg.auto_translate = value
        self._persist()
        if value:
            self._schedule_auto()

    def _on_top_toggle(self, value: bool) -> None:
        self.cfg.always_on_top = value
        self.root.attributes("-topmost", value)
        self._persist()

    # ------------------------------------------------------------ 剪贴板
    def paste_input(self) -> None:
        text = win32.read_clipboard_text()
        if not text:
            try:
                text = self.root.clipboard_get()
            except tk.TclError:
                return
        self.input_text.delete("1.0", "end")
        self.input_text.insert("1.0", text)
        self._on_input_change()
        if self.cfg.auto_translate:
            self._schedule_auto()
        else:
            self.translate()

    def copy_output(self) -> None:
        text = self.output_text.get("1.0", "end-1c")
        if not text.strip():
            self.set_status("没有可复制的内容", COLORS["warn"])
            return
        self.copy_to_clipboard(text)
        self.set_status(f"已复制 {len(text)} 字符到剪贴板", COLORS["ok"])

    def clear_all(self) -> None:
        self.input_text.delete("1.0", "end")
        self.output_text.delete("1.0", "end")
        self.detected_label.configure(text="")
        self.latency_label.configure(text="")
        self.count_label.configure(text="0 字符")
        self._last_src = ""
        self.set_status("已清空", COLORS["text_dim"])

    # ------------------------------------------------------------ 翻译主流程
    def translate(self) -> None:
        if self._busy:
            self.cancel_request()
            return
        text = self.input_text.get("1.0", "end-1c")
        if not text.strip():
            self.set_status("先输入或粘贴要翻译的内容", COLORS["warn"])
            self.input_text.focus_set()
            return
        src, dst = self._current_langs()
        if src != "auto" and src == dst:
            self.set_status("源语言和目标语言相同，先换一个目标语言", COLORS["warn"])
            return

        self._last_src = text.strip()
        self.cancel.clear()
        self.output_text.delete("1.0", "end")
        self.latency_label.configure(text="")
        self._stream_buffer = ""
        self._start_busy()

        worker = threading.Thread(target=self._worker, args=(text, src, dst, None), daemon=True)
        worker.start()

    def polish_with_ai(self) -> None:
        """用 AI 引擎把当前译文再润色一遍。"""

        if self._busy:
            self.cancel_request()
            return
        base = self.output_text.get("1.0", "end-1c").strip() or self.input_text.get("1.0", "end-1c").strip()
        if not base:
            self.set_status("没有可润色的内容", COLORS["warn"])
            return
        _, dst = self._current_langs()
        self.cancel.clear()
        self._stream_buffer = ""
        self._start_busy()
        self.set_status("AI 润色中…", COLORS["violet"])
        worker = threading.Thread(target=self._worker, args=(base, "auto", dst, "润色"), daemon=True)
        worker.start()

    def cancel_request(self) -> None:
        if self._busy:
            self.cancel.set()
            self.set_status("正在取消…", COLORS["warn"])

    def _start_busy(self) -> None:
        self._busy = True
        self.btn_translate.set_text("停止  ■")
        self.btn_translate.set_variant("danger")
        self.status_dot.set_color(COLORS["accent"])
        self.status_dot.start_pulse()
        self.set_status("翻译中…", COLORS["accent"])

    def _end_busy(self) -> None:
        self._busy = False
        self.btn_translate.set_text("翻译  ▸")
        self.btn_translate.set_variant("primary")
        self.status_dot.stop_pulse()

    def _worker(self, text: str, src: str, dst: str, forced_style: str | None) -> None:
        try:
            runner = engines.EngineRunner(self.cfg)
            result = runner.translate(
                text, src, dst, cancel=self.cancel, on_delta=self._on_delta, style=forced_style
            )
            self._post(lambda: self._on_success(result, text, src, dst))
        except engines.EngineError as exc:
            message = str(exc)
            self._post(lambda: self._on_failure(message, cancelled=message == "已取消"))
        except Exception as exc:  # 兜底，避免线程静默死掉
            message = f"{type(exc).__name__}: {exc}"
            self._post(lambda: self._on_failure(message, cancelled=False))

    # Tk 只能在主线程里碰，工作线程统一把回调塞进队列
    def _post(self, fn) -> None:
        self._ui_queue.put(fn)

    def _drain_queue(self) -> None:
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                try:
                    fn()
                except Exception:
                    pass
        except queue.Empty:
            pass
        self.root.after(30, self._drain_queue)

    def _on_delta(self, partial: str) -> None:
        with self._stream_lock:
            self._stream_buffer = partial
            if self._stream_dirty:
                return
            self._stream_dirty = True
        self._post(self._flush_stream)

    def _flush_stream(self) -> None:
        with self._stream_lock:
            text = self._stream_buffer
            self._stream_dirty = False
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", text)
        self.output_text.see("end")
        self.set_status(f"流式输出中… {len(text)} 字符", COLORS["accent"])

    def _on_success(self, result: engines.Result, text: str, src: str, dst: str) -> None:
        self._end_busy()
        if self._stream_buffer:
            self.output_text.delete("1.0", "end")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", result.text)
        self._stream_buffer = ""
        self.latency_label.configure(text=f"{result.latency_ms} ms · {len(result.text)} 字符")
        if result.detected and result.detected != src:
            self.detected_label.configure(text=engines.short_lang_name(result.detected))
        self.engine_badge.configure(text=result.engine)
        self.set_status(f"完成 · {result.engine} · {result.latency_ms} ms{self._health_suffix()}", COLORS["ok"])
        self.remember_translation(result, text, result.engine)
        if self.cfg.auto_translate:
            self._schedule_auto()

    def _on_failure(self, message: str, cancelled: bool) -> None:
        self._end_busy()
        if cancelled:
            self.set_status("已取消", COLORS["warn"])
            return
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", "翻译失败\n\n" + message)
        self.output_text.tag_add("error", "1.0", "end")
        self.set_status("翻译失败，详情见译文区", COLORS["err"])
        self.status_dot.set_color(COLORS["err"])

    def set_status(self, text: str, color: str | None = None) -> None:
        self.status_label.configure(text=text)
        if color:
            self.status_label.configure(fg=color)
            if not self._busy:
                self.status_dot.set_color(color if color != COLORS["text_dim"] else COLORS["ok"])

    def _health_suffix(self) -> str:
        """把正在冷却的线路写进状态栏，用户能知道为什么变慢了。"""

        health = engines.route_health()
        if not health:
            return ""
        names = "、".join(name.split(" ")[0] for name in health)
        return f" · {names} 冷却中"

    # ------------------------------------------------------------ 持久化
    def _persist(self) -> None:
        src, dst = self._current_langs()
        self.cfg.source_lang = src
        self.cfg.target_lang = dst
        try:
            config_mod.save(self.cfg)
        except Exception:
            pass

    def on_close(self) -> None:
        # 有托盘的时候，点 X 只收进托盘；想真退出就用托盘菜单或 Ctrl+Q
        if self.cfg.close_to_tray and self.tray is not None and self.tray.ok:
            self.hide_window()
            if not self._tray_notified:
                self._tray_notified = True
                self.tray.notify(APP_NAME, "已收到托盘里，双击图标就能回来。右键有划词翻译开关。")
            return
        self.quit_app()

    def open_settings(self, tab: str | None = None) -> None:
        SettingsWindow(self, tab)

    def open_history(self) -> None:
        HistoryWindow(self)

    def open_ai_wizard(self) -> None:
        """没配 Key 就点 AI 时，直接把人送到接入向导。"""

        self.open_settings("ai")
        self.set_status("AI 引擎需要先填 API Key，填完点「测试连接」验证", COLORS["warn"])


class ModalWindow(tk.Toplevel):
    """统一的深色弹窗基类。"""

    def __init__(self, app: LumenApp, title: str, size: str, resizable: bool = False):
        super().__init__(app.root)
        self.app = app
        self.title(title)
        self.configure(bg=COLORS["bg"])
        self.geometry(size)
        self.transient(app.root)
        self.resizable(resizable, resizable)
        outer = tk.Frame(self, bg=COLORS["bg"])
        outer.pack(fill="both", expand=True, padx=16, pady=14)
        self.outer = outer
        self.after(60, lambda: apply_dark_titlebar(self))
        self.after(10, self._center)
        self.bind("<Escape>", lambda _e: self.destroy())

    def _center(self) -> None:
        self.update_idletasks()
        parent = self.app.root
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")


class SettingsWindow(ModalWindow):
    def __init__(self, app: LumenApp, tab: str | None = None):
        super().__init__(app, "Lumen 设置", "680x772", resizable=True)
        cfg = app.cfg
        self.grab_set()

        tk.Label(self.outer, text="设置", bg=COLORS["bg"], fg=COLORS["text"], font=Fonts.ui_xl).pack(anchor="w")
        tk.Label(
            self.outer,
            text="配置只写入本机 data/config.json，也可以改用环境变量 LUMEN_API_KEY。",
            bg=COLORS["bg"],
            fg=COLORS["text_mute"],
            font=Fonts.ui_sm,
        ).pack(anchor="w", pady=(2, 12))

        # 先给按钮条占位，窗口不够高时压缩的是上面的表单，按钮不会跑丢
        actions = tk.Frame(self.outer, bg=COLORS["bg"])
        actions.pack(side="bottom", fill="x", pady=(12, 0))
        RoundedButton(actions, "保存", self._save, variant="primary", width=96, height=38).pack(side="right")
        RoundedButton(actions, "取消", self.destroy, variant="subtle", width=88, height=38).pack(side="right", padx=(0, 8))
        self.test_label = tk.Label(actions, text="", bg=COLORS["bg"], fg=COLORS["text_mute"], font=Fonts.ui_sm)
        self.test_label.pack(side="left")
        RoundedButton(actions, "测试连接", self._test, variant="ghost", width=96, height=38).pack(side="left", padx=(0, 8))

        notebook = ttk.Notebook(self.outer)
        notebook.pack(fill="both", expand=True, pady=(0, 4))
        style = ttk.Style(self)
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=COLORS["surface2"], foreground=COLORS["text_dim"], padding=(16, 7), borderwidth=0)
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLORS["surface3"])],
            foreground=[("selected", COLORS["accent"])],
        )
        style.configure("TFrame", background=COLORS["bg"])

        tab_ai = tk.Frame(notebook, bg=COLORS["bg"])
        tab_net = tk.Frame(notebook, bg=COLORS["bg"])
        tab_select = tk.Frame(notebook, bg=COLORS["bg"])
        notebook.add(tab_ai, text="  AI 引擎  ")
        notebook.add(tab_net, text="  网络与通用  ")
        notebook.add(tab_select, text="  划词与托盘  ")

        self._build_ai_tab(tab_ai, cfg)
        self._build_net_tab(tab_net, cfg)
        self._build_select_tab(tab_select, cfg)

        if tab == "ai":
            notebook.select(tab_ai)
        elif tab == "select":
            notebook.select(tab_select)

    def _build_ai_tab(self, tab: tk.Frame, cfg: config_mod.Config) -> None:
        pad = {"padx": 18, "pady": (7, 0)}
        section_label(tab, "服务商预设").pack(anchor="w", **pad)
        self.var_preset = tk.StringVar(value=cfg.ai_preset)
        preset = ttk.Combobox(
            tab, textvariable=self.var_preset, values=list(config_mod.AI_PRESETS), state="readonly", style="Lumen.TCombobox", width=28
        )
        preset.pack(anchor="w", padx=18, pady=(4, 0))
        preset.bind("<<ComboboxSelected>>", self._on_preset)

        section_label(tab, "接口地址 Base URL").pack(anchor="w", **pad)
        self.var_base = tk.StringVar(value=cfg.ai_base_url)
        dark_entry(tab, self.var_base, width=62).pack(anchor="w", padx=18, pady=(4, 0))

        section_label(tab, "模型名").pack(anchor="w", **pad)
        self.var_model = tk.StringVar(value=cfg.ai_model)
        dark_entry(tab, self.var_model, width=62).pack(anchor="w", padx=18, pady=(4, 0))

        row = tk.Frame(tab, bg=COLORS["bg"])
        row.pack(anchor="w", fill="x", **pad)
        section_label(row, "API Key").pack(anchor="w")
        self.var_key = tk.StringVar(value=cfg.ai_key)
        self.key_entry = dark_entry(row, self.var_key, width=48, show="•")
        self.key_entry.pack(side="left", pady=(4, 0))
        self.show_key = False
        RoundedButton(row, "显示", self._toggle_key, variant="subtle", width=56, height=24, font=Fonts.ui_sm).pack(
            side="left", padx=(8, 0), pady=(6, 0)
        )
        tk.Label(
            tab,
            text=f"当前来源：{cfg.key_source()}（留空则读环境变量）",
            bg=COLORS["bg"],
            fg=COLORS["text_mute"],
            font=Fonts.ui_sm,
        ).pack(anchor="w", padx=18, pady=(4, 0))

        row2 = tk.Frame(tab, bg=COLORS["bg"])
        row2.pack(anchor="w", fill="x", **pad)
        left = tk.Frame(row2, bg=COLORS["bg"])
        left.pack(side="left")
        section_label(left, "翻译风格").pack(anchor="w")
        self.var_style = tk.StringVar(value=cfg.ai_style)
        ttk.Combobox(
            left, textvariable=self.var_style, values=list(engines.AI_STYLES), state="readonly", style="Lumen.TCombobox", width=14
        ).pack(pady=(4, 0))
        right = tk.Frame(row2, bg=COLORS["bg"])
        right.pack(side="left", padx=(18, 0))
        section_label(right, "温度 temperature").pack(anchor="w")
        self.var_temp = tk.StringVar(value=str(cfg.ai_temperature))
        dark_entry(right, self.var_temp, width=10).pack(pady=(4, 0))

        section_label(tab, "额外要求（追加进系统提示词）").pack(anchor="w", **pad)
        self.txt_extra = tk.Text(
            tab, height=3, bg=COLORS["surface2"], fg=COLORS["text"], insertbackground=COLORS["accent"], relief="flat",
            highlightthickness=1, highlightbackground=COLORS["border"], highlightcolor=COLORS["accent_dk"], font=Fonts.ui_md,
            wrap="word", padx=10, pady=8,
        )
        self.txt_extra.pack(fill="x", padx=18, pady=(4, 0))
        self.txt_extra.insert("1.0", cfg.ai_extra_prompt)

    def _build_net_tab(self, tab: tk.Frame, cfg: config_mod.Config) -> None:
        pad = {"padx": 18, "pady": (7, 0)}
        section_label(tab, "代理（http://127.0.0.1:7890，留空即直连）").pack(anchor="w", **pad)
        self.var_proxy = tk.StringVar(value=cfg.proxy)
        dark_entry(tab, self.var_proxy, width=44).pack(anchor="w", padx=18, pady=(4, 0))

        section_label(tab, "超时（秒）").pack(anchor="w", **pad)
        self.var_timeout = tk.StringVar(value=str(cfg.timeout))
        dark_entry(tab, self.var_timeout, width=10).pack(anchor="w", padx=18, pady=(4, 0))

        section_label(tab, "窗口").pack(anchor="w", **pad)
        row = tk.Frame(tab, bg=COLORS["bg"])
        row.pack(anchor="w", **pad)
        self.var_remember = tk.BooleanVar(value=cfg.remember_geometry)
        tk.Checkbutton(
            row, text="记住窗口大小与位置", variable=self.var_remember, bg=COLORS["bg"], fg=COLORS["text_dim"],
            activebackground=COLORS["bg"], activeforeground=COLORS["accent"], selectcolor=COLORS["surface3"],
            font=Fonts.ui_md, bd=0, highlightthickness=0,
        ).pack(anchor="w")

        tk.Label(tab, text="", bg=COLORS["bg"]).pack(pady=6)
        info = (
            "在线引擎按 有道 → MyMemory → Google 的顺序自动降级，全都不需要 Key；\n"
            "某条线路限流或不通时会自动冷却并跳过，冷却状态显示在状态栏。\n"
            "Google 线路在国内需要代理，填了代理才会生效。\n\n"
            "在线翻译会自动保护 {占位符}、%s、<b> 标签、`代码` 和链接，翻译后原样还原。\n\n"
            "AI 引擎走 OpenAI 兼容协议，支持 DeepSeek / OpenAI / 通义 / 智谱 / Moonshot / 本地 Ollama。\n\n"
            "快捷键：Ctrl+Enter 翻译，Esc 停止，Ctrl+Shift+S 交换语言，Ctrl+H 历史，Ctrl+, 设置。\n\n"
            "历史记录存放于 data/history.jsonl，上限 500 条，可随时在历史窗口清空。"
        )
        tk.Label(tab, text=info, bg=COLORS["bg"], fg=COLORS["text_mute"], font=Fonts.ui_sm, justify="left", anchor="w").pack(
            anchor="w", padx=18, pady=(10, 0)
        )

    def _build_select_tab(self, tab: tk.Frame, cfg: config_mod.Config) -> None:
        pad = {"padx": 18, "pady": (8, 0)}

        section_label(tab, "开关").pack(anchor="w", **pad)
        row = tk.Frame(tab, bg=COLORS["bg"])
        row.pack(anchor="w", fill="x", padx=18, pady=(4, 0))
        self.var_shot_vision = tk.BooleanVar(value=cfg.screenshot_use_vision)
        self.var_hotkeys = tk.BooleanVar(value=cfg.hotkeys_enabled)
        self.var_tray = tk.BooleanVar(value=cfg.enable_tray)
        self.var_close_tray = tk.BooleanVar(value=cfg.close_to_tray)
        self.var_instant = tk.BooleanVar(value=cfg.select_instant)
        self.var_instant_double = tk.BooleanVar(value=cfg.select_double_click)
        self.var_instant_console = tk.BooleanVar(value=cfg.select_skip_console)
        self.var_instant_restore = tk.BooleanVar(value=cfg.select_restore_clipboard)
        self.var_auto_select = tk.BooleanVar(value=cfg.auto_select_popup)
        self.var_smart = tk.BooleanVar(value=cfg.popup_smart_target)
        self.var_popup_auto_close = tk.BooleanVar(value=cfg.popup_auto_close)
        for text, var in (
            ("选中即翻译：拖选一段或双击选词就自动弹窗（不用按快捷键）", self.var_instant),
            ("　　双击 / 三击选词也触发", self.var_instant_double),
            ("　　在终端窗口里不自动触发（避免误发 Ctrl+C 打断命令）", self.var_instant_console),
            ("　　取完词把剪贴板恢复原样", self.var_instant_restore),
            ("截图翻译交给 AI 视觉模型（识别更准，需要模型支持图片）", self.var_shot_vision),
            ("启用全局快捷键", self.var_hotkeys),
            ("启用系统托盘图标", self.var_tray),
            ("点关闭按钮时收进托盘（而不是退出）", self.var_close_tray),
            ("复制即翻译：剪贴板一变就弹浮窗", self.var_auto_select),
            ("浮窗智能选方向（中文→英文，其它→中文）", self.var_smart),
            ("手动划词的浮窗失去焦点时自动关闭", self.var_popup_auto_close),
        ):
            tk.Checkbutton(
                row, text=text, variable=var, bg=COLORS["bg"], fg=COLORS["text_dim"],
                activebackground=COLORS["bg"], activeforeground=COLORS["accent"], selectcolor=COLORS["surface3"],
                font=Fonts.ui_md, bd=0, highlightthickness=0, anchor="w",
            ).pack(anchor="w")

        section_label(tab, "快捷键（形如 ctrl+alt+t，改完点保存即时生效）").pack(anchor="w", **pad)
        grid = tk.Frame(tab, bg=COLORS["bg"])
        grid.pack(anchor="w", padx=18, pady=(4, 0))
        rows = (
            ("划词翻译（选中文本后按下）", "hotkey_select", cfg.hotkey_select),
            ("翻译剪贴板内容", "hotkey_clipboard", cfg.hotkey_clipboard),
            ("截图翻译（框选屏幕区域）", "hotkey_shot", cfg.hotkey_shot),
            ("显示 / 隐藏主窗口", "hotkey_show", cfg.hotkey_show),
        )
        self.hotkey_vars: dict[str, tk.StringVar] = {}
        for index, (label, key, value) in enumerate(rows):
            tk.Label(grid, text=label, bg=COLORS["bg"], fg=COLORS["text_dim"], font=Fonts.ui_sm, anchor="w", width=24).grid(
                row=index, column=0, sticky="w", pady=3
            )
            var = tk.StringVar(value=value)
            self.hotkey_vars[key] = var
            dark_entry(grid, var, width=16).grid(row=index, column=1, sticky="w", padx=(6, 0), pady=3)

        self.hotkey_status = tk.Label(
            tab, text=self._hotkey_status_text(), bg=COLORS["bg"], fg=COLORS["text_mute"], font=Fonts.ui_sm, justify="left", anchor="w"
        )
        self.hotkey_status.pack(anchor="w", padx=18, pady=(10, 0))
        # 托盘/热键是在后台线程里注册的，标签要跟着刷新，否则会显示成"未启用"
        self.after(400, self._tick_status_labels)

        tk.Label(
            tab,
            text=(
                "划词原理：向当前前台窗口模拟一次 Ctrl+C，把选中文本读进剪贴板再翻译。\n"
                "「选中即翻译」用低层鼠标钩子识别拖选 / 双击，只对真实鼠标输入生效。\n"
                "托盘：左键单击 = 显示/隐藏主窗口，右键 = 菜单。"
            ),
            bg=COLORS["bg"],
            fg=COLORS["text_mute"],
            font=Fonts.ui_sm,
            justify="left",
            anchor="w",
        ).pack(anchor="w", padx=18, pady=(12, 0))

    def _hotkey_status_text(self) -> str:
        parts = []
        for binding in getattr(self.app, "hotkey_bindings", []) or []:
            name = win32.format_hotkey(binding.spec)
            parts.append(f"{name} {'✓ 已注册' if binding.registered else '✗ ' + (binding.error or '未注册')}")
        if not parts:
            parts.append("快捷键未启用")
        tray = "托盘 ✓" if (self.app.tray is not None and self.app.tray.ok) else "托盘 ✗"
        return "　".join(parts) + f"　{tray}"

    def _tick_status_labels(self) -> None:
        if not self.winfo_exists():
            return
        try:
            self.hotkey_status.configure(
                text=self._hotkey_status_text(),
                fg=COLORS["ok"] if (self.app.tray is not None and self.app.tray.ok) else COLORS["text_mute"],
            )
        except tk.TclError:
            return
        self.after(800, self._tick_status_labels)

    def _on_preset(self, _event=None) -> None:
        preset = config_mod.AI_PRESETS.get(self.var_preset.get())
        if preset:
            if preset["base_url"]:
                self.var_base.set(preset["base_url"])
            if preset["model"]:
                self.var_model.set(preset["model"])

    def _toggle_key(self) -> None:
        self.show_key = not self.show_key
        self.key_entry.configure(show="" if self.show_key else "•")

    def _collect(self) -> dict:
        try:
            temperature = max(0.0, min(2.0, float(self.var_temp.get())))
        except ValueError:
            temperature = 0.2
        try:
            timeout = max(5, min(180, int(float(self.var_timeout.get()))))
        except ValueError:
            timeout = 20
        return {
            "ai_preset": self.var_preset.get(),
            "ai_base_url": self.var_base.get().strip(),
            "ai_model": self.var_model.get().strip(),
            "ai_key": self.var_key.get().strip(),
            "ai_style": self.var_style.get(),
            "ai_temperature": temperature,
            "ai_extra_prompt": self.txt_extra.get("1.0", "end-1c").strip(),
            "proxy": self.var_proxy.get().strip(),
            "timeout": timeout,
            "remember_geometry": bool(self.var_remember.get()),
            "hotkeys_enabled": bool(self.var_hotkeys.get()),
            "enable_tray": bool(self.var_tray.get()),
            "close_to_tray": bool(self.var_close_tray.get()),
            "select_instant": bool(self.var_instant.get()),
            "select_double_click": bool(self.var_instant_double.get()),
            "select_skip_console": bool(self.var_instant_console.get()),
            "select_restore_clipboard": bool(self.var_instant_restore.get()),
            "screenshot_use_vision": bool(self.var_shot_vision.get()),
            "auto_select_popup": bool(self.var_auto_select.get()),
            "popup_smart_target": bool(self.var_smart.get()),
            "popup_auto_close": bool(self.var_popup_auto_close.get()),
            "hotkey_select": self.hotkey_vars["hotkey_select"].get().strip(),
            "hotkey_clipboard": self.hotkey_vars["hotkey_clipboard"].get().strip(),
            "hotkey_shot": self.hotkey_vars["hotkey_shot"].get().strip(),
            "hotkey_show": self.hotkey_vars["hotkey_show"].get().strip(),
        }

    def _apply(self) -> None:
        for key, value in self._collect().items():
            setattr(self.app.cfg, key, value)
        self.app._sync_engine_buttons()
        config_mod.save(self.app.cfg)
        self.app.restart_integrations()
        self.hotkey_status.configure(text=self._hotkey_status_text())

    def _save(self) -> None:
        self._apply()
        self.app.set_status("设置已保存", COLORS["ok"])
        self.destroy()

    def _test(self) -> None:
        values = self._collect()
        self.test_label.configure(text="测试中…", fg=COLORS["accent"])

        def run() -> None:
            try:
                key = values["ai_key"] or self.app.cfg.ai_key_resolved()
                engine = engines.AIEngine(values["ai_base_url"], key, values["ai_model"], 0.0, 20, values["proxy"])
                result = engine.translate("Hello, world.", "en", "zh-CN", style="直译")
                message, color = f"✓ 连接成功：{result.text[:24]}", COLORS["ok"]
            except Exception as exc:
                message, color = f"✗ {str(exc).splitlines()[0][:60]}", COLORS["err"]
            self.app._post(lambda: self.test_label.configure(text=message, fg=color))

        threading.Thread(target=run, daemon=True).start()


class HistoryWindow(ModalWindow):
    def __init__(self, app: LumenApp):
        super().__init__(app, "Lumen 历史", "720x520", resizable=True)
        self.grab_set()
        head = tk.Frame(self.outer, bg=COLORS["bg"])
        head.pack(fill="x")
        tk.Label(head, text="翻译历史", bg=COLORS["bg"], fg=COLORS["text"], font=Fonts.ui_xl).pack(side="left")
        RoundedButton(head, "清空历史", self._clear, variant="danger", width=88, height=32, font=Fonts.ui_sm).pack(side="right")
        tk.Label(
            self.outer, text="点任意一条可回填到左右两栏", bg=COLORS["bg"], fg=COLORS["text_mute"], font=Fonts.ui_sm
        ).pack(anchor="w", pady=(2, 10))

        wrap = tk.Frame(self.outer, bg=COLORS["border"], highlightthickness=0)
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg=COLORS["surface"], bd=0, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        scroll = ttk.Scrollbar(wrap, orient="vertical", style="Lumen.Vertical.TScrollbar", command=self.canvas.yview)
        scroll.pack(side="right", fill="y", padx=(0, 1), pady=1)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.list_frame = tk.Frame(self.canvas, bg=COLORS["surface"])
        self._win = self.canvas.create_window(0, 0, window=self.list_frame, anchor="nw")
        self.list_frame.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
        self._render()

    def destroy(self) -> None:
        try:
            self.canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
        super().destroy()

    def _render(self) -> None:
        for child in self.list_frame.winfo_children():
            child.destroy()
        entries = history.load_recent(80)
        if not entries:
            tk.Label(self.list_frame, text="还没有记录", bg=COLORS["surface"], fg=COLORS["text_mute"], font=Fonts.ui_md).pack(pady=24)
            return
        for entry in entries:
            self._row(entry)

    def _row(self, entry: history.Entry) -> None:
        row = tk.Frame(self.list_frame, bg=COLORS["surface"], cursor="hand2")
        row.pack(fill="x", padx=10, pady=(0, 8))
        inner = tk.Frame(row, bg=COLORS["surface2"], highlightthickness=1, highlightbackground=COLORS["border"])
        inner.pack(fill="x")
        top = tk.Frame(inner, bg=COLORS["surface2"])
        top.pack(fill="x", padx=12, pady=(9, 4))
        tk.Label(top, text=entry.when(), bg=COLORS["surface2"], fg=COLORS["text_mute"], font=Fonts.mono_xs).pack(side="left")
        tk.Label(
            top,
            text=f"{entry.source_lang} → {entry.target_lang}",
            bg=COLORS["surface2"],
            fg=COLORS["accent"],
            font=Fonts.mono_xs,
        ).pack(side="left", padx=(10, 0))
        tk.Label(top, text=f"{entry.engine} · {entry.latency_ms} ms", bg=COLORS["surface2"], fg=COLORS["text_mute"], font=Fonts.ui_sm).pack(
            side="right"
        )
        preview_src = entry.src.strip().replace("\n", " ")[:70]
        preview_dst = entry.dst.strip().replace("\n", " ")[:70]
        tk.Label(inner, text=preview_src, bg=COLORS["surface2"], fg=COLORS["text"], font=Fonts.ui_md, anchor="w", justify="left").pack(
            fill="x", padx=12
        )
        tk.Label(inner, text="↓", bg=COLORS["surface2"], fg=COLORS["text_mute"], font=Fonts.mono_xs).pack(anchor="w", padx=12)
        tk.Label(inner, text=preview_dst, bg=COLORS["surface2"], fg=COLORS["text_dim"], font=Fonts.ui_md, anchor="w", justify="left").pack(
            fill="x", padx=12, pady=(0, 10)
        )
        for widget in (row, inner, top, *inner.winfo_children(), *top.winfo_children()):
            widget.bind("<Button-1>", lambda _e, item=entry: self._load(item))

    def _load(self, entry: history.Entry) -> None:
        app = self.app
        app.input_text.delete("1.0", "end")
        app.input_text.insert("1.0", entry.src)
        app.output_text.delete("1.0", "end")
        app.output_text.insert("1.0", entry.dst)
        app.var_source.set(engines.SOURCE_LANGUAGES.get(entry.source_lang, "自动检测"))
        app.var_target.set(engines.LANGUAGES.get(entry.target_lang, "简体中文"))
        app._on_input_change()
        app.set_status(f"已载入 {entry.when()} 的记录", COLORS["ok"])
        self.destroy()

    def _clear(self) -> None:
        history.clear()
        self._render()
