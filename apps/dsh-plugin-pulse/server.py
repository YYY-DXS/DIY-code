#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH 插件安装面板（图形化）—— 本地 HTTP 服务，只监听 127.0.0.1。

能力：
  * 把《优秀 DSH 插件简报》的精选渲染成卡片，一键调用官方 CLI 安装 / 卸载
  * 兼容性诊断：检查本机 DSH 版本、Node 版本、profile 状态、npm 可达性，
    并按 npm 上最新的 engines / peerDependencies 判断每个插件是否兼容本机
  * 安装成功后自动把插件注册进 profile 的 dsh.profile.bundles

可直接 `python server.py` 运行，也可用 PyInstaller 打包成 exe。
"""

import html as html_mod
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor  # noqa: F401  (预留并行查询)
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_TITLE = "DSH 插件安装面板"
HOST = "127.0.0.1"
PORT = int(os.environ.get("DSH_INSTALLER_PORT", "8790"))
URL = f"http://{HOST}:{PORT}/"

FROZEN = bool(getattr(sys, "frozen", False))
_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) if FROZEN else Path(__file__).resolve().parent
UI_PATH = _BASE / "ui.html"
BUNDLED_CATALOG = _BASE / "catalog.json"

# 数据目录：打包后用于放可编辑的 catalog.json 与日志
DATA_DIR = Path(os.environ.get("DSH_INSTALLER_HOME") or (Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DSHPluginInstaller"))
CATALOG_EXTERNAL = DATA_DIR / "catalog.json"

PROFILES_DIR = None          # 在 main() 中探测
APP_DIR = None
DSH_EXE = None
DSH_ASAR = None
DSH_CLI = None
NODE_EXE = None

SPEC_RE = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*(?:@[A-Za-z0-9._^*<>=~-]+)?$")
GITHUB_SPEC_RE = re.compile(r"^github:[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
MAX_LOG_LINES = 4000

_jobs = {}
_jobs_lock = threading.Lock()
_busy = threading.Lock()
_host_cache = {}
_host_lock = threading.Lock()


# --------------------------------------------------------------- logging ----
def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(DATA_DIR / "server.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if not FROZEN and sys.stderr:
        print(line, file=sys.stderr)


# ------------------------------------------------------------ environment ---
def find_app_dir():
    env = os.environ.get("DSH_APP_DIR")
    cands = []
    if env:
        cands.append(Path(env))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cands.append(Path(local) / "Programs" / "DeepSeek Harness")
    for pf in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if pf:
            cands.append(Path(pf) / "DeepSeek Harness")
    for c in cands:
        if (c / "DeepSeek Harness.exe").exists():
            return c
    return None


def find_dsh_home():
    env = os.environ.get("DSH_HOME")
    if env:
        return Path(env)
    profile_dir = os.environ.get("DSH_PROFILE_DIR")
    if profile_dir:
        return Path(profile_dir).parent.parent
    return Path.home() / ".dsh"


def find_node(exe_dir, dsh_home):
    cands = []
    if exe_dir:
        cands += [
            exe_dir / "resources" / "runtime" / "bin" / "node.exe",
            exe_dir / "resources" / "runtime" / "primary-runtime" / "dependencies" / "node" / "bin" / "node.exe",
        ]
    if dsh_home:
        cands.append(dsh_home / "dsh-runtimes" / "dsh-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe")
    for c in cands:
        if c.exists():
            return c
    return None


def init_env():
    global APP_DIR, DSH_EXE, DSH_ASAR, DSH_CLI, NODE_EXE, PROFILES_DIR
    APP_DIR = find_app_dir()
    if APP_DIR:
        DSH_EXE = APP_DIR / "DeepSeek Harness.exe"
        DSH_ASAR = APP_DIR / "resources" / "app.asar"
        DSH_CLI = DSH_ASAR / "dsh" / "node_modules" / "@deepseek-ai" / "dsh-desktop-host" / "lib" / "cli.js"
    NODE_EXE = find_node(APP_DIR, find_dsh_home())
    PROFILES_DIR = find_dsh_home() / "profiles"
    log(f"app_dir={APP_DIR} profiles_dir={PROFILES_DIR} node={NODE_EXE}")


def run_cli(args, timeout=1800, stream_to=None):
    env = dict(os.environ)
    env["ELECTRON_RUN_AS_NODE"] = "1"
    cmd = [str(DSH_EXE), "--expose-internals", str(DSH_CLI)] + args
    creationflags = 0x08000000 if os.name == "nt" else 0
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace",
                                env=env, creationflags=creationflags, bufsize=1)
    except Exception as exc:
        if stream_to:
            _append(stream_to, f"!! 无法启动 CLI: {exc}")
        return -1
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if stream_to:
                _append(stream_to, line.rstrip())
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        if stream_to:
            _append(stream_to, "!! 超时，已终止")
        return -1


def host_info(force=False):
    """本机运行环境信息（带缓存）。"""
    with _host_lock:
        if _host_cache and not force:
            return _host_cache
        info = {
            "appFound": bool(DSH_EXE and DSH_EXE.exists() and DSH_ASAR and DSH_ASAR.exists()),
            "appDir": str(APP_DIR) if APP_DIR else None,
            "profilesDir": str(PROFILES_DIR),
            "dshVersion": None,
            "nodeVersion": None,
            "network": {"npm": False},
            "profiles": {},
        }
        if NODE_EXE:
            try:
                p = subprocess.run([str(NODE_EXE), "--version"], capture_output=True, text=True, timeout=15,
                                   creationflags=0x08000000)
                info["nodeVersion"] = (p.stdout or "").strip().lstrip("v") or None
            except Exception as exc:
                log(f"node version failed: {exc}")
        if info["appFound"]:
            try:
                env = dict(os.environ); env["ELECTRON_RUN_AS_NODE"] = "1"
                p = subprocess.run([str(DSH_EXE), "--expose-internals", str(DSH_CLI), "--version"],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   timeout=90, env=env, creationflags=0x08000000)
                out = ((p.stdout or "") + (p.stderr or "")).strip().splitlines()
                info["dshVersion"] = out[-1].strip() if out else None
            except Exception as exc:
                log(f"dsh version failed: {exc}")
        try:
            with socket.create_connection(("registry.npmjs.org", 443), timeout=4):
                info["network"]["npm"] = True
        except Exception:
            info["network"]["npm"] = False
        if PROFILES_DIR and PROFILES_DIR.exists():
            for d in sorted(p for p in PROFILES_DIR.iterdir() if p.is_dir()):
                pkg = d / "package.json"
                bundles = []
                deps = {}
                if pkg.exists():
                    try:
                        data = json.loads(pkg.read_text(encoding="utf-8"))
                        bundles = data.get("dsh", {}).get("profile", {}).get("bundles", [])
                        deps = data.get("dependencies", {})
                    except Exception:
                        pass
                info["profiles"][d.name] = {"path": str(d), "bundles": bundles,
                                            "dependencies": list(deps.keys()),
                                            "writable": os.access(d, os.W_OK) if d.exists() else False}
        _host_cache.clear()
        _host_cache.update(info)
        return info


# ------------------------------------------------------------------ semver --
_VER_RE = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?$")


def parse_ver(raw):
    m = _VER_RE.match((raw or "").strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0), m.group(4))


def _cmp_pre(a, b):
    if a is None and b is None:
        return 0
    if a is None:
        return 1
    if b is None:
        return -1
    pa, pb = a.split("."), b.split(".")
    for x, y in zip(pa, pb):
        xd, yd = x.isdigit(), y.isdigit()
        if xd and yd:
            if int(x) != int(y):
                return -1 if int(x) < int(y) else 1
        elif xd != yd:
            return -1 if xd else 1
        elif x != y:
            return -1 if x < y else 1
    if len(pa) != len(pb):
        return -1 if len(pa) < len(pb) else 1
    return 0


def cmp_ver(a, b):
    for i in range(3):
        if a[i] != b[i]:
            return -1 if a[i] < b[i] else 1
    return _cmp_pre(a[3], b[3])


def _split_op(tok):
    for op in (">=", "<=", ">", "<", "^", "~", "="):
        if tok.startswith(op):
            return op, tok[len(op):]
    return "", tok


def _caret_ok(v, r):
    if r[0] > 0:
        upper = (r[0] + 1, 0, 0, None)
    elif r[1] > 0:
        upper = (0, r[1] + 1, 0, None)
    else:
        upper = (0, 0, r[2] + 1, None)
    return cmp_ver(v, upper) < 0


def _match_token(v, tok):
    op, rest = _split_op(tok)
    if rest.strip() in ("", "*", "x", "X"):
        return True
    r = parse_ver(rest)
    if r is None:
        return None  # 无法解析 → 不判定为失败
    if op == "^":
        return cmp_ver(v, r) >= 0 and _caret_ok(v, r)
    if op == "~":
        upper = (r[0], r[1] + 1, 0, None)
        return cmp_ver(v, r) >= 0 and cmp_ver(v, upper) < 0
    if op == ">=":
        return cmp_ver(v, r) >= 0
    if op == ">":
        return cmp_ver(v, r) > 0
    if op == "<=":
        return cmp_ver(v, r) <= 0
    if op == "<":
        return cmp_ver(v, r) < 0
    return cmp_ver(v, r) == 0


def satisfies(version, rng):
    """简化版 semver 范围判断；返回 True / False / None(无法判断)。"""
    v = parse_ver(version)
    if v is None:
        return None
    rng = (rng or "").strip()
    if not rng or rng in ("*", "x"):
        return True
    results = []
    for clause in rng.split("||"):
        ok = True
        for tok in clause.replace(" - ", " ").split():
            res = _match_token(v, tok)
            if res is None:
                results.append(None)
                ok = None
                break
            if not res:
                ok = False
                break
        if ok:
            return True
        if ok is None:
            results.append(None)
    return None if results else False


# ------------------------------------------------------------------- npm ----
def npm_latest(pkg):
    url = "https://registry.npmjs.org/" + urllib.parse.quote(pkg, safe="") + "/latest"
    req = urllib.request.Request(url, headers={"User-Agent": "dsh-plugin-installer/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        log(f"npm_latest({pkg}) failed: {exc}")
        return None


def spec_name(spec):
    spec = (spec or "").strip()
    if spec.startswith("@"):
        at = spec.find("@", 1)
        return spec[:at] if at != -1 else spec
    at = spec.find("@")
    return spec[:at] if at != -1 else spec


def dsh_peers(meta):
    peers = (meta or {}).get("peerDependencies") or {}
    only_dsh = {k: v for k, v in peers.items() if k.startswith("@deepseek-ai/dsh")}
    cordis = peers.get("@deepseek-ai/cordis")
    return only_dsh, cordis


# --------------------------------------------------------------- catalog ----
def catalog_path():
    env = os.environ.get("DSH_INSTALLER_CATALOG")
    if env and Path(env).exists():
        return Path(env)
    if CATALOG_EXTERNAL.exists():
        return CATALOG_EXTERNAL
    return BUNDLED_CATALOG


def ensure_catalog_copy():
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if BUNDLED_CATALOG.exists() and not CATALOG_EXTERNAL.exists():
            shutil.copy2(BUNDLED_CATALOG, CATALOG_EXTERNAL)
    except Exception as exc:
        log(f"catalog copy failed: {exc}")


def load_catalog():
    with open(catalog_path(), "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- profile ---
def profile_dir(profile):
    return PROFILES_DIR / profile


def read_profile(profile):
    pkg = profile_dir(profile) / "package.json"
    if not pkg.exists():
        return {"dependencies": {}, "bundles": []}
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except Exception:
        return {"dependencies": {}, "bundles": []}
    return {"dependencies": data.get("dependencies", {}),
            "bundles": data.get("dsh", {}).get("profile", {}).get("bundles", [])}


def register_bundle(profile, name):
    pkg_path = profile_dir(profile) / "package.json"
    if not pkg_path.exists():
        return "profile 尚未初始化，跳过 bundle 注册"
    meta_path = profile_dir(profile) / "node_modules" / Path(*name.split("/")) / "package.json"
    if not meta_path.exists():
        return f"未找到 {name} 的安装产物，跳过 bundle 注册"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return f"读取 {name} 元数据失败，跳过 bundle 注册"
    if not meta.get("dsh"):
        return f"{name} 未声明 dsh bundle，无需注册"
    data = json.loads(pkg_path.read_text(encoding="utf-8"))
    prof = data.setdefault("dsh", {}).setdefault("profile", {})
    bundles = prof.setdefault("bundles", [])
    if name in bundles:
        return f"{name} 已在 bundles 中"
    bundles.append(name)
    shutil.copy2(pkg_path, pkg_path.with_name("package.json.bak"))
    pkg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"{name} 已注册到 {profile} profile 的 bundles"


def unregister_bundle(profile, name):
    pkg_path = profile_dir(profile) / "package.json"
    if not pkg_path.exists():
        return "profile 不存在"
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except Exception:
        return "profile package.json 解析失败"
    bundles = data.get("dsh", {}).get("profile", {}).get("bundles", [])
    if name not in bundles:
        return f"{name} 不在 bundles 中"
    bundles.remove(name)
    shutil.copy2(pkg_path, pkg_path.with_name("package.json.bak"))
    pkg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"{name} 已从 bundles 移除"


# ------------------------------------------------------------------ jobs ----
def _append(job_id, line):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["log"].append(line)
        if len(job["log"]) > MAX_LOG_LINES:
            job["log"] = job["log"][-MAX_LOG_LINES:]


def _update(job_id, **kw):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.update(kw)


def _run_job(job_id, action, spec, profile, bundle):
    deps_before = set(read_profile(profile)["dependencies"].keys())
    try:
        _update(job_id, status="running")
        _append(job_id, f"$ dsh plugin --profile {profile} {action} {spec}")
        _append(job_id, "")
        rc = run_cli(["plugin", "--profile", profile, action, spec], stream_to=job_id)
        _append(job_id, "")
        if rc == 0:
            try:
                deps_after = set(read_profile(profile)["dependencies"].keys())
                if action == "add":
                    if not bundle:
                        new = deps_after - deps_before
                        if len(new) == 1:
                            bundle = next(iter(new))
                            _append(job_id, f"[bundle] 检测到新依赖: {bundle}")
                    if bundle:
                        _append(job_id, "[bundle] " + register_bundle(profile, bundle))
                elif action == "remove":
                    if not bundle:
                        gone = deps_before - deps_after
                        if len(gone) == 1:
                            bundle = next(iter(gone))
                    if bundle:
                        _append(job_id, "[bundle] " + unregister_bundle(profile, bundle))
                _append(job_id, "[ok] 命令执行成功。重启 DeepSeek Harness 后生效。")
                _update(job_id, status="done", rc=0, finished=time.time())
            except Exception as exc:
                _append(job_id, f"[bundle] 注册步骤异常（插件本身已装入）: {exc}")
                _update(job_id, status="done", rc=0, finished=time.time())
        else:
            _append(job_id, f"[fail] CLI 退出码 {rc}，请查看上面的输出。")
            _update(job_id, status="failed", rc=rc, finished=time.time())
    except Exception as exc:
        _append(job_id, f"!! 任务异常: {exc}")
        _update(job_id, status="failed", rc=-1, finished=time.time())
    finally:
        _busy.release()


def start_job(action, spec, profile, bundle):
    if not _busy.acquire(blocking=False):
        return None, "已有安装/卸载任务在进行中，请等它结束"
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"id": job_id, "action": action, "spec": spec, "profile": profile,
                         "status": "queued", "log": [], "started": time.time(), "finished": None}
    threading.Thread(target=_run_job, args=(job_id, action, spec, profile, bundle), daemon=True).start()
    return job_id, None


# ------------------------------------------------------------ diagnostics ---
def diagnose_item(item, host):
    profile = item.get("profile") or "desktop"
    name = item.get("bundle") or spec_name(item.get("spec", ""))
    checks = []

    def add(key, label, status, detail):
        checks.append({"key": key, "label": label, "status": status, "detail": detail})

    if not host.get("appFound"):
        add("app", "DSH 安装位置", "fail", "未找到 DeepSeek Harness 安装目录，无法安装")
    if not host["network"]["npm"]:
        add("net", "npm registry 连通", "fail", "无法连接 registry.npmjs.org，安装会失败")

    meta = None
    latest = None
    if host["network"]["npm"] and APP_DIR:
        meta = npm_latest(name)
        if meta:
            latest = meta.get("version")
            add("pkg", "npm 包存在", "ok", f"{name}@latest = {latest}")
        else:
            add("pkg", "npm 包存在", "fail", f"registry 查询不到 {name}（可能不是 npm 包）")
    else:
        add("pkg", "npm 包存在", "unknown", "网络不可达，跳过 npm 查询")

    if meta:
        engines = meta.get("engines") or {}
        node_req = engines.get("node")
        node_ver = host.get("nodeVersion")
        if node_req:
            ok = satisfies(node_ver, node_req) if node_ver else None
            if ok is True:
                add("node", "Node 版本", "ok", f"要求 {node_req}，本机 {node_ver}")
            elif ok is False:
                add("node", "Node 版本", "fail", f"要求 {node_req}，本机 {node_ver} 不满足")
            else:
                add("node", "Node 版本", "unknown", f"要求 {node_req}，本机版本无法判断")
        else:
            add("node", "Node 版本", "info", "未声明 engines.node")

        peers, cordis = dsh_peers(meta)
        host_ver = host.get("dshVersion")
        if not peers:
            add("peer", "DSH peer 依赖", "info", "未声明 @deepseek-ai/dsh-* peer 依赖")
        else:
            bad = []
            unknown = []
            for pkg, rng in peers.items():
                res = satisfies(host_ver, rng) if host_ver else None
                if res is False:
                    bad.append(f"{pkg}@{rng}")
                elif res is None:
                    unknown.append(f"{pkg}@{rng}")
            if bad:
                add("peer", "DSH peer 依赖", "fail", f"本机 DSH {host_ver} 不满足：" + "；".join(bad))
            elif unknown:
                add("peer", "DSH peer 依赖", "unknown", f"本机 DSH 版本未知，无法判断：" + "；".join(unknown))
            else:
                add("peer", "DSH peer 依赖", "ok", f"本机 DSH {host_ver} 满足 {len(peers)} 项 peer 要求")
        if cordis:
            add("cordis", "cordis peer 依赖", "info", f"要求 {cordis}；cordis 版本随宿主内置，需在 DSH 内确认")

        add("bundle", "bundle 声明", "ok" if meta.get("dsh") else "unknown",
            "包含 dsh.bundle 补丁" if meta.get("dsh") else "未检测到 dsh.bundle 字段")

    prof = host["profiles"].get(profile)
    if prof is None:
        add("profile", f"目标 profile ({profile})", "info", "profile 尚未初始化，首次安装时自动创建")
    else:
        installed = name in prof["bundles"]
        add("profile", f"目标 profile ({profile})", "ok",
            f"{'已安装' if installed else '未安装'}；bundles {len(prof['bundles'])} 个；{'可写' if prof['writable'] else '不可写'}")

    statuses = [c["status"] for c in checks]
    if "fail" in statuses:
        verdict = "incompatible"
    elif "unknown" in statuses:
        verdict = "unknown"
    else:
        verdict = "compatible"
    return {"id": item.get("id"), "name": item.get("name"), "spec": item.get("spec"),
            "profile": profile, "latest": latest, "verdict": verdict, "checks": checks}


def diagnose_all():
    host = host_info(force=True)
    catalog = load_catalog()
    items = [diagnose_item(it, host) for it in catalog["items"]]
    compat = sum(1 for i in items if i["verdict"] == "compatible")
    return {
        "host": {
            "appFound": host["appFound"],
            "appDir": host["appDir"],
            "dshVersion": host["dshVersion"],
            "nodeVersion": host["nodeVersion"],
            "npmReachable": host["network"]["npm"],
            "profiles": list(host["profiles"].keys()),
            "catalogSource": str(catalog_path()),
        },
        "summary": {"total": len(items), "compatible": compat,
                    "incompatible": sum(1 for i in items if i["verdict"] == "incompatible"),
                    "unknown": sum(1 for i in items if i["verdict"] == "unknown")},
        "items": items,
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


# ------------------------------------------------------------- 插件库数据 ---
STORE_PATH = DATA_DIR / "plugins_store.json"
STORE_LOCK = threading.RLock()
STORE = {
    "items": {},
    "meta": {"nextPage": 1, "totalPages": 201, "pagesScanned": 0,
             "lastRefresh": None, "scanning": False, "lastError": None,
             "source": "https://dshbase.com/plugins/directory/"},
}

CARD_RE = re.compile(r'<a class="card pcard"(?P<attrs>[^>]*)>(?P<body>.*?)</a>', re.S)
ATTR_RE = re.compile(r'data-([a-z0-9-]+)="([^"]*)"')
TAG_RE = re.compile(r"<[^>]+>")


def _plain(raw):
    return html_mod.unescape(TAG_RE.sub("", raw or "")).strip()


def _grab(pattern, text, idx=1):
    m = re.search(pattern, text, re.S)
    return m.group(idx) if m else ""


def _to_int(raw):
    m = re.search(r"([\d,]+)", raw or "")
    return int(m.group(1).replace(",", "")) if m else 0


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) dsh-installer/1.0",
        "Accept": "text/html,application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def parse_directory(page_html):
    """解析 dshbase 目录页，返回 (items, 最大页码)。"""
    items = []
    for m in CARD_RE.finditer(page_html or ""):
        attrs = dict(ATTR_RE.findall(m.group("attrs")))
        body = m.group("body")
        slug = attrs.get("slug") or ""
        if not slug:
            continue
        name = attrs.get("name") or _plain(_grab(r'pcard-name[^>]*>(.*?)</span>', body))
        owner = _plain(_grab(r'pcard-owner[^>]*>(.*?)</span>', body))
        desc = _plain(_grab(r'<p class="pcard-desc"[^>]*>(.*?)</p>', body))
        trust = _grab(r'pcard-trust t-(\w+)', body)
        status_m = re.search(r'class="badge st-(\w+)"[^>]*>(.*?)</span>', body, re.S)
        status = status_m.group(1) if status_m else ""
        status_text = _plain(status_m.group(2)) if status_m else ""
        if not status_text:
            status_text = {"ok": "Verified", "warn": "Unverified"}.get(status, "Listed")
        cmd_raw = attrs.get("cmd", "")
        spec = ""
        madd = re.search(r"\badd\s+(.+?)\s*$", cmd_raw)
        if madd:
            spec = madd.group(1).strip().strip('"').strip("'")
        items.append({
            "slug": slug,
            "name": name or slug,
            "owner": owner,
            "desc": desc,
            "stars": int(attrs.get("stars") or 0),
            "npm": attrs.get("npm") == "1",
            "cmd": cmd_raw,
            "spec": spec,
            "trust": trust,
            "status": status,
            "statusText": status_text,
            "license": _plain(_grab(r'pcard-meta[^>]*>(.*?)</span>', body)).lstrip("⚖ ").strip(),
            "updated": _plain(_grab(r'pcard-updated[^>]*>(.*?)</span>', body)).replace("↻", "").strip(),
            "ucs": attrs.get("ucs", ""),
            "source": "https://dshbase.com/plugins/%s/" % slug,
            "seenAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
    pages = [int(x) for x in re.findall(r"/plugins/directory/page/(\d+)/", page_html or "")]
    return items, (max(pages) if pages else 0)


def store_load():
    if not STORE_PATH.exists():
        return
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        with STORE_LOCK:
            STORE["items"] = data.get("items", {})
            STORE["meta"].update(data.get("meta", {}))
            STORE["meta"]["scanning"] = False
    except Exception as exc:
        log(f"store load failed: {exc}")


def store_save():
    try:
        with STORE_LOCK:
            data = {"items": STORE["items"], "meta": dict(STORE["meta"], savedAt=time.strftime("%Y-%m-%d %H:%M:%S"))}
        tmp = STORE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STORE_PATH)
    except Exception as exc:
        log(f"store save failed: {exc}")


def refresh_loop():
    """后台持续扫描 dshbase 插件目录，一页接一页循环刷新。"""
    store_load()
    sleep_s = float(os.environ.get("DSH_REFRESH_SLEEP", "2.5"))
    with STORE_LOCK:
        STORE["meta"]["scanning"] = True
    while True:
        try:
            page = int(STORE["meta"].get("nextPage") or 1)
            total = int(STORE["meta"].get("totalPages") or 201)
            page = max(1, min(page, total))
            url = "https://dshbase.com/plugins/directory/page/%d/" % page
            page_html = http_get(url, timeout=35)
            items, max_page = parse_directory(page_html)
            if max_page:
                total = max_page
            with STORE_LOCK:
                for it in items:
                    STORE["items"][it["slug"]] = it
                STORE["meta"].update({
                    "totalPages": total,
                    "pagesScanned": int(STORE["meta"].get("pagesScanned") or 0) + 1,
                    "lastRefresh": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "lastError": None,
                    "scanning": True,
                    "lastPage": page,
                    "nextPage": (page % total) + 1,
                })
                count = len(STORE["items"])
            if page % 5 == 0 or page == 1:
                store_save()
            log(f"refresh page {page}/{total} -> +{len(items)} items, total={count}")
            time.sleep(sleep_s)
        except Exception as exc:
            with STORE_LOCK:
                STORE["meta"]["lastError"] = str(exc)[:200]
                STORE["meta"]["scanning"] = True
            log(f"refresh failed: {exc}")
            time.sleep(20)


def query_plugins(q="", page=1, size=24, sort="stars", verified_only=False):
    with STORE_LOCK:
        items = list(STORE["items"].values())
        meta = dict(STORE["meta"])
    q = (q or "").strip().lower()
    if q:
        items = [i for i in items if q in (i.get("name") or "").lower()
                 or q in (i.get("desc") or "").lower()
                 or q in (i.get("owner") or "").lower()
                 or q in (i.get("slug") or "").lower()]
    if verified_only:
        items = [i for i in items if i.get("status") in ("ok", "verified")]
    if sort == "stars":
        items.sort(key=lambda i: i.get("stars") or 0, reverse=True)
    elif sort == "updated":
        items.sort(key=lambda i: i.get("updated") or "", reverse=True)
    else:
        items.sort(key=lambda i: (i.get("name") or "").lower())
    total = len(items)
    size = max(6, min(int(size or 24), 100))
    page = max(1, int(page or 1))
    start = (page - 1) * size
    return {"total": total, "page": page, "size": size,
            "items": items[start:start + size], "meta": meta}


# ------------------------------------------------------------ 单插件诊断 ---
GITHUB_REPO_RE = re.compile(r"^github:([A-Za-z0-9][A-Za-z0-9._-]*)/([A-Za-z0-9][A-Za-z0-9._-]*)$")


def _add_check(checks, key, label, status, detail):
    checks.append({"key": key, "label": label, "status": status, "detail": detail})


def _verdict_of(checks):
    statuses = [c["status"] for c in checks]
    if "fail" in statuses:
        return "incompatible"
    if "unknown" in statuses:
        return "unknown"
    return "compatible"


def diagnose_one(spec, profile="desktop"):
    host = host_info()
    checks = []
    gm = GITHUB_REPO_RE.match(spec or "")
    if not host.get("appFound"):
        _add_check(checks, "app", "DSH 安装位置", "fail", "未找到 DeepSeek Harness 安装目录")
    if not host["network"]["npm"]:
        _add_check(checks, "net", "网络连通", "fail", "无法连接外网，安装可能失败")
    latest = None
    if gm:
        owner, repo = gm.group(1), gm.group(2)
        _add_check(checks, "src", "安装来源", "info", "GitHub 源码（非 npm），无法校验 npm 元数据")
        try:
            meta = json.loads(http_get("https://api.github.com/repos/%s/%s" % (owner, repo), timeout=15))
            full = meta.get("full_name", repo)
            latest = meta.get("pushed_at", "")[:10]
            _add_check(checks, "repo", "GitHub 仓库", "ok",
                       "%s · ★%s · 最近推送 %s · %s issues" % (full, meta.get("stargazers_count"), latest, meta.get("open_issues_count")))
            if meta.get("archived"):
                _add_check(checks, "archived", "仓库状态", "fail", "仓库已归档，后续不再维护")
            lic = (meta.get("license") or {}).get("spdx_id")
            _add_check(checks, "license", "License", "ok" if lic and lic != "NOASSERTION" else "unknown",
                       lic or "未声明 license")
        except Exception as exc:
            _add_check(checks, "repo", "GitHub 仓库", "unknown", "api.github.com 查询失败: %s" % str(exc)[:80])
    else:
        pkg = spec_name(spec)
        meta = npm_latest(pkg) if host["network"]["npm"] else None
        if meta:
            latest = meta.get("version")
            _add_check(checks, "pkg", "npm 包存在", "ok", "%s@latest = %s" % (pkg, latest))
            engines = meta.get("engines") or {}
            node_req = engines.get("node")
            node_ver = host.get("nodeVersion")
            if node_req:
                ok = satisfies(node_ver, node_req) if node_ver else None
                _add_check(checks, "node", "Node 版本", "ok" if ok is True else ("fail" if ok is False else "unknown"),
                           "要求 %s，本机 %s" % (node_req, node_ver))
            peers, cordis = dsh_peers(meta)
            if peers:
                bad = []
                unknown = []
                for p, rng in peers.items():
                    res = satisfies(host.get("dshVersion"), rng) if host.get("dshVersion") else None
                    if res is False:
                        bad.append("%s@%s" % (p, rng))
                    elif res is None:
                        unknown.append("%s@%s" % (p, rng))
                if bad:
                    _add_check(checks, "peer", "DSH peer 依赖", "fail", "本机 DSH %s 不满足：%s" % (host.get("dshVersion"), "；".join(bad)))
                elif unknown:
                    _add_check(checks, "peer", "DSH peer 依赖", "unknown", "本机 DSH 版本未知")
                else:
                    _add_check(checks, "peer", "DSH peer 依赖", "ok", "本机 DSH %s 满足 %d 项 peer 要求" % (host.get("dshVersion"), len(peers)))
            if cordis:
                _add_check(checks, "cordis", "cordis peer 依赖", "info", "要求 %s；cordis 版本随宿主内置" % cordis)
        elif host["network"]["npm"]:
            _add_check(checks, "pkg", "npm 包存在", "fail", "registry 查询不到 %s" % pkg)
        else:
            _add_check(checks, "pkg", "npm 包存在", "unknown", "网络不可达，跳过 npm 查询")
    prof = host["profiles"].get(profile)
    if prof is None:
        _add_check(checks, "profile", "目标 profile (%s)" % profile, "info", "profile 尚未初始化，首次安装时自动创建")
    else:
        _add_check(checks, "profile", "目标 profile (%s)" % profile, "ok",
                   "可写" if prof.get("writable") else "不可写")
    return {"spec": spec, "profile": profile, "latest": latest,
            "verdict": _verdict_of(checks), "checks": checks}


# ------------------------------------------------------------------ HTTP ----
class Handler(BaseHTTPRequestHandler):
    server_version = "DSHPluginInstaller/2.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            try:
                html = UI_PATH.read_bytes()
            except FileNotFoundError:
                return self._json(500, {"error": "ui.html 缺失"})
            return self._send(200, html, "text/html; charset=utf-8")
        if path == "/api/health":
            return self._json(200, {"ok": bool(DSH_EXE and DSH_EXE.exists() and DSH_ASAR and DSH_ASAR.exists()),
                                    "frozen": FROZEN, "port": PORT,
                                    "appDir": str(APP_DIR) if APP_DIR else None,
                                    "profilesDir": str(PROFILES_DIR),
                                    "catalog": str(catalog_path())})
        if path == "/api/catalog":
            return self._json(200, self._catalog_payload())
        if path == "/api/diagnose":
            try:
                return self._json(200, diagnose_all())
            except Exception as exc:
                log(f"diagnose failed: {exc}")
                return self._json(500, {"error": f"诊断失败: {exc}"})
        if path == "/api/plugins":
            qs = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = {}
            for part in qs.split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k] = urllib.parse.unquote_plus(v)
            return self._json(200, query_plugins(
                q=params.get("q", ""),
                page=params.get("page", 1),
                size=params.get("size", 24),
                sort=params.get("sort", "stars"),
                verified_only=params.get("verified") in ("1", "true", "yes"),
            ))
        if path == "/api/refresh/status":
            with STORE_LOCK:
                return self._json(200, {"meta": dict(STORE["meta"]), "total": len(STORE["items"])})
        if path == "/api/installed":
            catalog = load_catalog()
            profiles = sorted({it.get("profile", catalog.get("defaultProfile", "desktop")) for it in catalog["items"]})
            return self._json(200, {p: read_profile(p) for p in profiles})
        if path == "/api/job":
            qs = self.path.split("?", 1)[1] if "?" in self.path else ""
            job_id = ""
            for part in qs.split("&"):
                if part.startswith("id="):
                    job_id = part[3:]
            with _jobs_lock:
                job = dict(_jobs.get(job_id) or {})
            if not job:
                return self._json(404, {"error": "job not found"})
            return self._json(200, job)
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        data = self._body()
        if path in ("/api/install", "/api/uninstall"):
            return self._start(data, path.split("/")[-1])
        if path == "/api/diagnose-one":
            spec = str(data.get("spec") or "").strip()
            if not (SPEC_RE.match(spec) or GITHUB_SPEC_RE.match(spec)):
                return self._json(400, {"error": "包名格式不合法"})
            profile = str(data.get("profile") or "desktop")
            try:
                return self._json(200, diagnose_one(spec, profile))
            except Exception as exc:
                log(f"diagnose-one failed: {exc}")
                return self._json(500, {"error": str(exc)})
        if path == "/api/refresh":
            if data.get("reset"):
                with STORE_LOCK:
                    STORE["meta"]["nextPage"] = 1
                return self._json(200, {"ok": True, "reset": True})
            with STORE_LOCK:
                return self._json(200, {"ok": True, "meta": dict(STORE["meta"]), "total": len(STORE["items"])})
        if path == "/api/shutdown":
            self._json(200, {"ok": True})
            threading.Thread(target=lambda: (time.sleep(0.3), os._exit(0)), daemon=True).start()
            return
        return self._json(404, {"error": "not found"})

    def _catalog_payload(self):
        catalog = load_catalog()
        profiles = {}
        installed_map = {}
        for it in catalog["items"]:
            profile = it.get("profile", catalog.get("defaultProfile", "desktop"))
            if profile not in profiles:
                profiles[profile] = read_profile(profile)
            bundle = it.get("bundle") or spec_name(it.get("spec", ""))
            installed_map[it["id"]] = {"installed": bundle in profiles[profile]["bundles"]}
        return {"catalog": catalog, "installed": installed_map, "profiles": profiles}

    def _start(self, data, kind):
        catalog = load_catalog()
        item = None
        if data.get("id"):
            item = next((it for it in catalog["items"] if it["id"] == data["id"]), None)
            if item is None:
                return self._json(400, {"error": "未知插件 id"})
            spec = item["spec"]
            profile = item.get("profile", catalog.get("defaultProfile", "desktop"))
            bundle = item.get("bundle") or spec_name(spec)
        else:
            spec = str(data.get("spec") or "").strip()
            if SPEC_RE.match(spec):
                bundle = spec_name(spec)
            elif GITHUB_SPEC_RE.match(spec):
                bundle = ""
            else:
                return self._json(400, {"error": "包名格式不合法（支持 npm 包名，如 pkg / @scope/pkg@1.2.3，或 github:owner/repo）"})
            profile = str(data.get("profile") or catalog.get("defaultProfile", "desktop"))
        if not (DSH_EXE and DSH_EXE.exists() and DSH_ASAR and DSH_ASAR.exists()):
            return self._json(500, {"error": "找不到 DeepSeek Harness 的 CLI 入口"})
        action = "add" if kind == "install" else "remove"
        job_id, err = start_job(action, spec, profile, bundle)
        if err:
            return self._json(409, {"error": err})
        return self._json(200, {"jobId": job_id, "spec": spec, "profile": profile, "action": action})


# ------------------------------------------------------------------ main ----
def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex((HOST, port)) == 0


def main():
    if not CATALOG_EXTERNAL.parent.exists():
        CATALOG_EXTERNAL.parent.mkdir(parents=True, exist_ok=True)
    init_env()
    ensure_catalog_copy()
    if port_in_use(PORT):
        log("面板已在运行，直接打开浏览器")
        webbrowser.open(URL)
        return 0
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    log(f"启动 {APP_TITLE}: {URL}")
    store_load()
    threading.Thread(target=refresh_loop, daemon=True).start()
    if os.environ.get("DSH_INSTALLER_OPEN_BROWSER", "1") == "1":
        threading.Timer(0.8, lambda: webbrowser.open(URL)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        log("已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
