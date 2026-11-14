#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH 插件脉冲面板 —— 原生桌面窗口（Tkinter），非网页 UI。

视觉参考「科技脉冲」：深色玻璃底、青绿脉冲波形、扫描线、等宽字体。
复用了 server.py 的数据与安装/诊断逻辑（插件库、兼容性诊断、官方 CLI 安装），
本身不再启动本地 Web 服务。

用法：
    python pulse_panel.py
    python pulse_panel.py --shot out.png     # 渲染一张窗口截图（用于预览）
"""

import argparse
import ctypes
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import server as core
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"无法导入 server.py（数据层）: {exc}")

# ------------------------------------------------------------------ 主题色 --
BG = "#04070c"
BG2 = "#070d15"
PANEL = "#0a1119"
PANEL2 = "#0d1722"
LINE = "#122334"
TEXT = "#cfe6f5"
DIM = "#5b7285"
CYAN = "#00e5ff"
MINT = "#00ffc6"
AMBER = "#ffc247"
RED = "#ff4d6d"
VIOLET = "#8b5bff"

MONO = ("Cascadia Mono", "Consolas")
UI_FONT = ("Microsoft YaHei UI", 10)

ROOT = None
LOG_Q = queue.Queue()
STATE = {
    "view": "lib",           # lib | picks
    "items": [],             # 当前列表
    "page": 1,
    "page_size": 100,
    "total": 0,
    "sel": 0,
    "scope": 0,              # 列表滚动起始
    "q": "",
    "sort": "stars",
    "verified": False,
    "row_h": 58,
    "detail": None,
    "diag": None,
    "hover": -1,
    "busy": False,
    "diag_busy": False,
    "phase": 0.0,
    "picks": [],
    "picks_installed": {},
    "picks_diag": None,
    "lib_meta": {},
}


# --------------------------------------------------------------- 数据层 ----
def boot_core():
    core.init_env()
    core.ensure_catalog_copy()
    threading.Thread(target=core.refresh_loop, daemon=True).start()


def load_picks():
    try:
        cat = core.load_catalog()
    except Exception:
        cat = {"items": [], "defaultProfile": "desktop"}
    picks = []
    for it in cat.get("items", []):
        prof = it.get("profile", cat.get("defaultProfile", "desktop"))
        state = core.read_profile(prof)
        bundle = it.get("bundle") or core.spec_name(it.get("spec", ""))
        picks.append({**it, "profile": prof, "bundle": bundle,
                      "installed": bundle in state.get("bundles", [])})
    return picks


def lib_query(reset_page=False):
    if reset_page:
        STATE["page"] = 1
        STATE["items"] = []
        STATE["scope"] = 0
        STATE["sel"] = 0
    data = core.query_plugins(q=STATE["q"], page=STATE["page"],
                              size=STATE["page_size"], sort=STATE["sort"],
                              verified_only=STATE["verified"])
    STATE["total"] = data["total"]
    STATE["items"] = data["items"]
    STATE["lib_meta"] = data.get("meta", {})
    STATE["detail"] = STATE["items"][0] if STATE["items"] else None


def pick_item():
    if STATE["view"] == "picks":
        i = min(STATE["sel"], len(STATE["picks"]) - 1)
        return STATE["picks"][i] if i >= 0 else None
    i = min(STATE["sel"], len(STATE["items"]) - 1)
    return STATE["items"][i] if i >= 0 else None


# ------------------------------------------------------------------ 排版 ----
def enable_dark_titlebar(root):
    """尽量让原生标题栏也变成深色（Win10 1903+）。"""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, root.title()) or user32.GetParent(root.winfo_id()) or root.winfo_id()
        v = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass


class PulseApp:
    def __init__(self, root):
        self.root = root
        self.shot_path = None
        root.title("DSH 插件脉冲面板")
        root.configure(bg=BG)
        root.geometry("1380x880")
        root.minsize(1100, 700)
        try:
            root.iconbitmap(str(Path(__file__).resolve().parent / "assets" / "icon.ico"))
        except Exception:
            pass
        self._build_ui()
        root.overrideredirect(True)          # 无系统标题栏，纯自绘科技脉冲外壳
        self._center_window()
        load_picks()
        STATE["picks"] = load_picks()
        lib_query(reset_page=True)
        self.draw_all()
        self.tick()

    # ---------------- 布局 ----------------
    def _build_ui(self):
        self.pulse = tk.Canvas(self.root, height=122, bg=BG, highlightthickness=0)
        self.pulse.pack(fill="x")
        self.pulse.bind("<ButtonPress-1>", self.start_drag)
        self.pulse.bind("<B1-Motion>", self.on_drag)

        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=18, pady=(2, 6))
        self.tab_lib = self._tab(bar, "插件库", True, lambda: self.switch("lib"))
        self.tab_picks = self._tab(bar, "精选推荐", False, lambda: self.switch("picks"))
        self.tab_lib.pack(side="left", padx=(0, 8))
        self.tab_picks.pack(side="left")
        tk.Label(bar, text="", bg=BG).pack(side="left", expand=True)
        self.search_var = tk.StringVar()
        self.search = tk.Entry(bar, textvariable=self.search_var, width=34, bg=PANEL, fg=TEXT,
                               insertbackground=CYAN, relief="flat", font=(MONO[0], 10),
                               highlightthickness=1, highlightbackground=LINE, highlightcolor=CYAN)
        self.search.pack(side="right", ipady=6, padx=(8, 0))
        self.search.bind("<Return>", lambda e: self.apply_search())
        self.search.bind("<KeyRelease>", self.on_search_key)
        tk.Label(bar, text="搜索", bg=BG, fg=DIM, font=UI_FONT).pack(side="right")
        self.sort_btn = self._btn(bar, "SORT ★", self.cycle_sort, ghost=True)
        self.sort_btn.pack(side="right", padx=8)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 8))

        # 左：列表
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        self.list_canvas = tk.Canvas(left, bg=BG, highlightthickness=0)
        self.list_canvas.pack(fill="both", expand=True)
        self.list_canvas.bind("<Button-1>", self.on_list_click)
        self.list_canvas.bind("<Double-Button-1>", lambda e: self.install_selected())
        self.list_canvas.bind("<Motion>", self.on_list_motion)
        self.list_canvas.bind("<MouseWheel>", self.on_wheel)
        self.list_canvas.bind("<Configure>", lambda e: self.draw_list())
        self.root.bind("<Down>", lambda e: self.move(1))
        self.root.bind("<Up>", lambda e: self.move(-1))
        self.root.bind("<Prior>", lambda e: self.move(-8))
        self.root.bind("<Next>", lambda e: self.move(8))
        self.root.bind("<Return>", lambda e: self.install_selected())
        self.root.bind("<Escape>", lambda e: self.search.delete(0, "end"))
        self.root.bind("/", lambda e: self.search.focus_set())
        self.root.bind("<Tab>", lambda e: self.switch("picks" if STATE["view"] == "lib" else "lib"))
        self.root.bind("d", lambda e: self.diagnose_selected())
        self.root.bind("i", lambda e: self.install_selected())
        self.root.bind("o", lambda e: self.open_selected())
        self.root.bind("r", lambda e: self.refresh())

        # 右：详情
        right = tk.Frame(body, bg=PANEL, width=440)
        right.pack(side="right", fill="y", padx=(14, 0))
        right.pack_propagate(False)
        tk.Frame(right, bg=LINE, height=1).pack(fill="x")
        self.d_title = tk.Label(right, text="", bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 15, "bold"),
                                anchor="w", justify="left", wraplength=400)
        self.d_title.pack(fill="x", padx=16, pady=(14, 2))
        self.d_meta = tk.Label(right, text="", bg=PANEL, fg=DIM, font=(MONO[0], 9), anchor="w",
                               justify="left", wraplength=400)
        self.d_meta.pack(fill="x", padx=16)
        self.d_badges = tk.Label(right, text="", bg=PANEL, fg=MINT, font=(MONO[0], 9), anchor="w")
        self.d_badges.pack(fill="x", padx=16, pady=(4, 8))
        self.d_desc = tk.Text(right, height=7, bg=PANEL, fg=TEXT, font=UI_FONT, relief="flat",
                              wrap="word", padx=0, pady=0, insertwidth=0, highlightthickness=0)
        self.d_desc.pack(fill="x", padx=16)
        self.d_desc.configure(state="disabled")
        self.d_btns = tk.Frame(right, bg=PANEL)
        self.d_btns.pack(fill="x", padx=16, pady=10)
        self.b_install = self._btn(self.d_btns, "安装  ⏎", self.install_selected)
        self.b_install.pack(side="left")
        self.b_diag = self._btn(self.d_btns, "诊断  D", self.diagnose_selected, ghost=True)
        self.b_diag.pack(side="left", padx=8)
        self.b_open = self._btn(self.d_btns, "来源  O", self.open_selected, ghost=True)
        self.b_open.pack(side="left")
        tk.Label(right, text="DIAGNOSTICS", bg=PANEL, fg=DIM, font=(MONO[0], 8)).pack(anchor="w", padx=16)
        self.d_diag = tk.Text(right, height=11, bg=BG2, fg=TEXT, font=(MONO[0], 9), relief="flat",
                              wrap="word", padx=10, pady=8, insertwidth=0, highlightthickness=1,
                              highlightbackground=LINE)
        self.d_diag.pack(fill="both", expand=True, padx=16, pady=(4, 14))

        # 底部日志
        self.log = tk.Text(self.root, height=6, bg=BG2, fg=TEXT, font=(MONO[0], 9), relief="flat",
                           padx=14, pady=8, insertwidth=0, highlightthickness=0, state="disabled")
        self.log.pack(fill="x", padx=18, pady=(0, 4))
        self.log.tag_configure("cmd", foreground=CYAN)
        self.log.tag_configure("ok", foreground=MINT)
        self.log.tag_configure("warn", foreground=AMBER)
        self.log.tag_configure("err", foreground=RED)
        self.log.tag_configure("dim", foreground=DIM)

        self.status = tk.Label(self.root, text="", bg=BG, fg=DIM, font=(MONO[0], 9), anchor="w")
        self.status.pack(fill="x", padx=18, pady=(0, 8))

    def _center_window(self):
        w, h = 1380, 880
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2 - 20)}")

    def start_drag(self, event):
        self._drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def on_drag(self, event):
        if not getattr(self, "_drag", None):
            return
        x, y = self._drag
        self.root.geometry(f"+{event.x_root - x}+{event.y_root - y}")

    def _tab(self, parent, text, active, cmd):
        b = tk.Label(parent, text=text, bg=PANEL2 if active else BG, fg=TEXT if active else DIM,
                     font=("Microsoft YaHei UI", 10, "bold"), padx=14, pady=6, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        b._active = active
        return b

    def _btn(self, parent, text, cmd, ghost=False):
        b = tk.Label(parent, text=text, bg=PANEL2 if ghost else "#0b6b7a",
                     fg=TEXT if ghost else "#eaffff", font=("Microsoft YaHei UI", 9, "bold"),
                     padx=12, pady=6, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(bg="#12212e" if ghost else "#0e8a9c"))
        b.bind("<Leave>", lambda e: b.configure(bg=PANEL2 if ghost else "#0b6b7a"))
        return b

    # ---------------- 动画 ----------------
    def tick(self):
        STATE["phase"] += 0.16
        self.draw_pulse()
        self.pump_queue()
        if STATE["busy"] or STATE["diag_busy"]:
            self.update_status()
        self.root.after(55, self.tick)

    def draw_pulse(self):
        import math
        c = self.pulse
        w = max(600, c.winfo_width())
        h = 122
        c.delete("all")
        for x in range(0, w, 48):
            c.create_line(x, 0, x, h, fill="#08131c")
        for y in range(0, h, 24):
            c.create_line(0, y, w, y, fill="#08131c")
        # 波形只在下方带状区域，避免压住标题
        base_y = h - 6
        max_h = 34
        n = w // 9
        ph = STATE["phase"]
        for i in range(n):
            v = 0.5 + 0.5 * math.sin(ph + i * 0.24)
            v *= 0.55 + 0.45 * math.sin(ph * 0.6 + i * 0.07)
            v = abs(v)
            bh = 4 + v * max_h
            x = i * 9 + 4
            color = CYAN if v > 0.55 else (MINT if v > 0.3 else "#0e6b83")
            c.create_rectangle(x, base_y - bh, x + 4, base_y, fill=color, outline="")
        sx = int((ph * 90) % w)
        c.create_rectangle(sx, 0, sx + 2, h, fill="#0b3d4d", outline="")
        c.create_text(22, 24, text="DSH PLUGIN PULSE", anchor="w",
                      fill="#e8fdff", font=(MONO[0], 20, "bold"))
        meta = STATE["lib_meta"] or {}
        sub = f"PLUGINS {STATE['total']:,}  ·  SCANNED {meta.get('pagesScanned', 0)}/{meta.get('totalPages', 269)}  ·  DSH {self.dsh_ver() or '-'}"
        c.create_text(24, 48, text=sub, anchor="w", fill="#3fd3e8", font=(MONO[0], 9))
        c.create_text(24, 64, text="↑↓ 选择   ⏎ 安装   D 诊断   O 来源   / 搜索   TAB 切换   R 刷新",
                      anchor="w", fill="#2c4a5e", font=(MONO[0], 8))
        live = "● LIVE" if meta.get("scanning") else "○ IDLE"
        c.create_text(w - 22, 24, text=live, anchor="e", fill=MINT if meta.get("scanning") else DIM,
                      font=(MONO[0], 10, "bold"))
        asof = meta.get("lastRefresh") or "--"
        c.create_text(w - 22, 48, text="LAST SYNC " + asof, anchor="e", fill=DIM, font=(MONO[0], 8))
        # 自绘窗口控制
        c.create_text(w - 26, 22, text="✕", anchor="e", fill="#ff6b81",
                      font=(MONO[0], 11, "bold"), tags=("winbtn", "close"))
        c.tag_bind("close", "<Button-1>", lambda e: self.root.destroy())
        c.create_line(0, h - 1, w, h - 1, fill="#0a2531")

    # ---------------- 列表 ----------------
    def rows_visible(self):
        return max(4, self.list_canvas.winfo_height() // STATE["row_h"])

    def draw_list(self):
        c = self.list_canvas
        c.delete("all")
        w = max(400, c.winfo_width())
        h = c.winfo_height()
        rows = self.rows_visible()
        items = STATE["picks"] if STATE["view"] == "picks" else STATE["items"]
        if STATE["sel"] < STATE["scope"]:
            STATE["scope"] = STATE["sel"]
        elif STATE["sel"] >= STATE["scope"] + rows:
            STATE["scope"] = STATE["sel"] - rows + 1
        scope = STATE["scope"]
        if not items:
            c.create_text(w // 2, 60, text="暂无数据 · 正在扫描插件库…", fill=DIM, font=UI_FONT)
            return
        for idx in range(scope, min(len(items), scope + rows)):
            it = items[idx]
            y = (idx - scope) * STATE["row_h"]
            sel = idx == STATE["sel"]
            hover = idx == STATE["hover"]
            bg = "#0b1d2b" if sel else ("#081521" if hover else BG2)
            c.create_rectangle(0, y + 2, w - 6, y + STATE["row_h"] - 4, fill=bg, outline="")
            if sel:
                c.create_rectangle(0, y + 2, 3, y + STATE["row_h"] - 4, fill=CYAN, outline="")
            if STATE["view"] == "picks":
                name = it.get("name", "")
                sub = f"{it.get('category', '')} · {it.get('profile', 'desktop')} profile"
                right = "已安装" if it.get("installed") else "未安装"
                rcolor = MINT if it.get("installed") else DIM
            else:
                name = it.get("name", "")
                sub = " · ".join([x for x in [it.get("owner", ""), it.get("ucs", "").split("|")[0],
                                              (it.get("license") or "")] if x])
                right = f"★ {it.get('stars', 0):,}"
                rcolor = AMBER
            c.create_text(16, y + 18, text=name[:46], anchor="w", fill=TEXT, font=(MONO[0], 11, "bold"))
            c.create_text(16, y + 40, text=sub[:78], anchor="w", fill=DIM, font=(MONO[0], 8))
            c.create_text(w - 18, y + 20, text=right, anchor="e", fill=rcolor, font=(MONO[0], 9, "bold"))
            if STATE["view"] == "lib":
                badge = it.get("statusText") or ""
                c.create_text(w - 18, y + 40, text=badge, anchor="e",
                              fill=MINT if it.get("status") == "ok" else DIM, font=(MONO[0], 8))

    def draw_detail(self):
        it = pick_item()
        STATE["detail"] = it
        if not it:
            self.d_title.configure(text="—")
            self.d_meta.configure(text="")
            self.d_badges.configure(text="")
            self._set_text(self.d_desc, "")
            return
        if STATE["view"] == "picks":
            title = it.get("name", "")
            meta = f"{it.get('category', '')}   ·   {it.get('profile', 'desktop')}   ·   {it.get('verified', '')}"
            badges = ("已安装" if it.get("installed") else "未安装") + f"   {it.get('risk', '').upper()} RISK"
            desc = (it.get("summary") or "") + "\n\n风险： " + (it.get("riskNote") or "")
            self.b_install.configure(text="卸载  ⏎" if it.get("installed") else "安装  ⏎")
        else:
            title = it.get("name", "")
            meta = " · ".join([x for x in [it.get("owner", ""), it.get("license") or "",
                                           "↻ " + (it.get("updated") or "")] if x])
            badges = "  ".join([x for x in [it.get("statusText") or "",
                                            (it.get("trust") or "").upper(),
                                            "npm" if it.get("npm") else "GITHUB"] if x])
            desc = it.get("desc") or "（无描述）"
            self.b_install.configure(text="安装  ⏎")
        self.d_title.configure(text=title)
        self.d_meta.configure(text=meta)
        self.d_badges.configure(text=badges)
        self._set_text(self.d_desc, desc)

    def _set_text(self, widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    # ---------------- 交互 ----------------
    def switch(self, view):
        STATE["view"] = view
        STATE["sel"] = 0
        STATE["scope"] = 0
        STATE["diag"] = None
        self.tab_lib.configure(bg=PANEL2 if view == "lib" else BG, fg=TEXT if view == "lib" else DIM)
        self.tab_picks.configure(bg=PANEL2 if view == "picks" else BG, fg=TEXT if view == "picks" else DIM)
        self.draw_all()

    def move(self, delta):
        items = STATE["picks"] if STATE["view"] == "picks" else STATE["items"]
        if not items:
            return
        STATE["sel"] = max(0, min(len(items) - 1, STATE["sel"] + delta))
        if STATE["view"] == "lib":
            self.maybe_more()
        self.draw_list()
        self.draw_detail()

    def maybe_more(self):
        if STATE.get("loading_more"):
            return
        if STATE["page"] * STATE["page_size"] >= STATE["total"]:
            return
        if STATE["sel"] < len(STATE["items"]) - 3:
            return
        STATE["loading_more"] = True
        STATE["page"] += 1
        threading.Thread(target=self._load_more, daemon=True).start()

    def _load_more(self):
        try:
            data = core.query_plugins(q=STATE["q"], page=STATE["page"],
                                      size=STATE["page_size"], sort=STATE["sort"],
                                      verified_only=STATE["verified"])
            if data["items"]:
                STATE["items"].extend(data["items"])
            if data["page"] * data["size"] >= data["total"]:
                STATE["page"] = max(1, (data["total"] + data["size"] - 1) // data["size"])
        except Exception as exc:
            self.q_log(f"[!] 加载更多失败: {exc}", "warn")
        finally:
            STATE["loading_more"] = False
            LOG_Q.put(("redraw", None, None))

    def on_wheel(self, event):
        self.move(-1 if event.delta > 0 else 1)

    def on_list_click(self, event):
        rows = self.rows_visible()
        idx = STATE["scope"] + (event.y // STATE["row_h"])
        items = STATE["picks"] if STATE["view"] == "picks" else STATE["items"]
        if 0 <= idx < len(items):
            STATE["sel"] = idx
            self.draw_list()
            self.draw_detail()

    def on_list_motion(self, event):
        rows = self.rows_visible()
        idx = STATE["scope"] + (event.y // STATE["row_h"])
        items = STATE["picks"] if STATE["view"] == "picks" else STATE["items"]
        STATE["hover"] = idx if 0 <= idx < len(items) else -1
        self.draw_list()

    def on_search_key(self, event):
        if event.keysym in ("Return", "Escape"):
            return
        self.root.after(280, self.apply_search)

    def apply_search(self):
        q = self.search_var.get().strip()
        if q == STATE["q"]:
            return
        STATE["q"] = q
        STATE["sel"] = 0
        lib_query(reset_page=True)
        self.draw_all()

    def cycle_sort(self):
        order = ["stars", "updated", "name"]
        STATE["sort"] = order[(order.index(STATE["sort"]) + 1) % len(order)]
        self.sort_btn.configure(text="SORT " + {"stars": "★", "updated": "↻", "name": "A-Z"}[STATE["sort"]])
        lib_query(reset_page=True)
        self.draw_all()

    def spec_of(self, it):
        if not it:
            return ""
        if STATE["view"] == "picks":
            return it.get("spec", "")
        return it.get("spec") or ""

    def install_selected(self):
        it = pick_item()
        if not it or STATE["busy"]:
            return
        if STATE["view"] == "picks" and it.get("installed"):
            self.start_uninstall(it)
            return
        spec = self.spec_of(it)
        if not spec:
            self.log_line("[!] 该插件没有可用的安装 spec", "warn")
            return
        self.start_install(spec, it.get("profile") or "desktop", it.get("name", spec))

    def start_install(self, spec, profile, name):
        STATE["busy"] = True
        self.log_line(f"$ dsh plugin --profile {profile} add {spec}", "cmd")
        self.update_status(f"安装中  {name} …")
        threading.Thread(target=self._install_worker, args=(spec, profile), daemon=True).start()

    def start_uninstall(self, it):
        bundle = it.get("bundle") or it.get("name", "")
        spec = bundle
        STATE["busy"] = True
        self.log_line(f"$ dsh plugin --profile {it.get('profile', 'desktop')} remove {spec}", "cmd")
        threading.Thread(target=self._uninstall_worker, args=(spec, it.get("profile", "desktop")), daemon=True).start()

    def _install_worker(self, spec, profile):
        deps_before = set(core.read_profile(profile).get("dependencies", {}).keys())
        rc = self._run_cli_stream(["plugin", "--profile", profile, "add", spec])
        if rc == 0:
            deps_after = set(core.read_profile(profile).get("dependencies", {}).keys())
            new = deps_after - deps_before
            bundle = next(iter(new)) if len(new) == 1 else ""
            if bundle:
                msg = core.register_bundle(profile, bundle)
                self.q_log("[bundle] " + msg, "ok")
            self.q_log("[ok] 安装完成，重启 DeepSeek Harness 后生效。", "ok")
        else:
            self.q_log(f"[fail] CLI 退出码 {rc}", "err")
        STATE["busy"] = False
        STATE["picks"] = load_picks()
        self.q_refresh()

    def _uninstall_worker(self, spec, profile):
        rc = self._run_cli_stream(["plugin", "--profile", profile, "remove", spec])
        if rc == 0:
            self.q_log("[ok] 卸载完成，重启 DeepSeek Harness 后生效。", "ok")
        else:
            self.q_log(f"[fail] CLI 退出码 {rc}", "err")
        STATE["busy"] = False
        STATE["picks"] = load_picks()
        self.q_refresh()

    def _run_cli_stream(self, args):
        env = dict(os.environ)
        env["ELECTRON_RUN_AS_NODE"] = "1"
        cmd = [str(core.DSH_EXE), "--expose-internals", str(core.DSH_CLI)] + args
        flags = 0x08000000 if os.name == "nt" else 0
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 encoding="utf-8", errors="replace", env=env, creationflags=flags)
        except Exception as exc:
            self.q_log(f"!! 无法启动 CLI: {exc}", "err")
            return -1
        for line in p.stdout:
            line = line.rstrip()
            if line:
                self.q_log(line, "dim")
        return p.wait()

    def diagnose_selected(self):
        it = pick_item()
        if not it or STATE["diag_busy"]:
            return
        spec = self.spec_of(it)
        if not spec:
            self.q_diag("该插件没有可诊断的 spec")
            return
        STATE["diag_busy"] = True
        self.update_status("诊断中…")
        threading.Thread(target=self._diag_worker, args=(spec, it.get("profile") or "desktop"), daemon=True).start()

    def _diag_worker(self, spec, profile):
        try:
            res = core.diagnose_one(spec, profile)
            STATE["diag"] = res
            text = [f"{res['verdict'].upper()}   latest={res.get('latest') or '-'}   profile={profile}", ""]
            marks = {"ok": "[ OK ]", "fail": "[FAIL]", "unknown": "[ ?? ]", "info": "[INFO]"}
            for c in res["checks"]:
                text.append(f"{marks.get(c['status'], '[----]')} {c['label']}: {c['detail']}")
            self.q_diag("\n".join(text))
        except Exception as exc:
            self.q_diag(f"诊断失败: {exc}")
        STATE["diag_busy"] = False
        self.update_status()

    def open_selected(self):
        it = pick_item()
        if not it:
            return
        url = it.get("source") or ""
        if STATE["view"] == "lib" and it.get("slug"):
            url = url or f"https://dshbase.com/plugins/{it['slug']}/"
        if url:
            webbrowser.open(url)

    def refresh(self):
        meta = core.host_info(force=True)
        lib_query(reset_page=True)
        STATE["picks"] = load_picks()
        self.draw_all()
        self.log_line(f"[i] 刷新完成 · npm {'OK' if meta['network']['npm'] else 'DOWN'} · DSH {meta.get('dshVersion') or '-'}", "dim")

    # ---------------- 队列 ----------------
    def q_log(self, text, tag="dim"):
        LOG_Q.put(("log", text, tag))

    def q_diag(self, text):
        LOG_Q.put(("diag", text, None))

    def q_refresh(self):
        LOG_Q.put(("refresh", None, None))

    def pump_queue(self):
        try:
            while True:
                kind, text, tag = LOG_Q.get_nowait()
                if kind == "log":
                    self.log_line(text, tag)
                elif kind == "diag":
                    self.show_diag_text(text)
                elif kind == "refresh":
                    STATE["picks"] = load_picks()
                    lib_query(reset_page=True)
                    self.draw_all()
                elif kind == "redraw":
                    self.draw_list()
                    self.update_status()
        except queue.Empty:
            pass

    # ---------------- 输出 ----------------
    def log_line(self, text, tag="dim"):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def show_diag_text(self, text):
        self.d_diag.delete("1.0", "end")
        self.d_diag.insert("1.0", text)

    def dsh_ver(self):
        try:
            return core.host_info().get("dshVersion")
        except Exception:
            return None

    def update_status(self, msg=None):
        meta = STATE["lib_meta"] or {}
        txt = msg or f"{STATE['total']:,} plugins · scanned {meta.get('pagesScanned', 0)}/{meta.get('totalPages', 201)} · {meta.get('lastRefresh') or '--'}"
        self.status.configure(text="▌ " + txt)

    def draw_all(self):
        self.draw_list()
        self.draw_detail()
        self.update_status()
        self.search_var.set(STATE["q"])

    # ---------------- 截图 ----------------
    def schedule_shot(self, path, delay_ms=4600):
        self.shot_path = path
        self.root.after(delay_ms, self._take_shot)

    def _take_shot(self):
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.FindWindowW(None, "DSH 插件脉冲面板")
            if not hwnd:
                hwnd = self.root.winfo_id()
            self.capture_window(hwnd, self.shot_path)
        except Exception as exc:
            print("shot failed:", exc)
        finally:
            self.root.after(300, self.root.destroy)

    @staticmethod
    def capture_window(hwnd, path):
        """用 Win32 API 抓窗口位图并写成 PNG（不依赖 Pillow）。"""
        import struct
        import zlib
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w <= 0 or h <= 0:
            raise RuntimeError(f"无效窗口尺寸 {w}x{h}")
        hdc = user32.GetWindowDC(hwnd)
        mem = gdi32.CreateCompatibleDC(hdc)
        bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
        gdi32.SelectObject(mem, bmp)
        user32.PrintWindow(hwnd, mem, 2)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]

        bi = BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.biWidth = w
        bi.biHeight = -h          # 负数 = 自上而下
        bi.biPlanes = 1
        bi.biBitCount = 32
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)

        raw = bytes(buf)
        rows = []
        for y in range(h):
            line = raw[y * w * 4:(y + 1) * w * 4]
            out = bytearray(w * 3 + 1)
            for x in range(w):
                out[1 + x * 3] = line[x * 4 + 2]
                out[2 + x * 3] = line[x * 4 + 1]
                out[3 + x * 3] = line[x * 4]
            rows.append(bytes(out))
        png = PulseApp._png_bytes(w, h, b"".join(rows))
        Path(path).write_bytes(png)

    @staticmethod
    def _png_bytes(w, h, raw_rows):
        import struct
        import zlib

        def chunk(tag, data):
            return (struct.pack(">I", len(data)) + tag + data +
                    struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + \
               chunk(b"IDAT", zlib.compress(raw_rows, 6)) + chunk(b"IEND", b"")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", default=None, help="截图输出路径")
    ap.add_argument("--shot-tab", default="lib", choices=["lib", "picks"])
    args = ap.parse_args()
    boot_core()
    root = tk.Tk()
    app = PulseApp(root)
    if args.shot_tab == "picks":
        app.switch("picks")
        app.move(1)
    else:
        app.move(2)
    if args.shot:
        app.root.after(800, app.diagnose_selected)
        app.schedule_shot(args.shot)
    root.mainloop()


if __name__ == "__main__":
    main()
