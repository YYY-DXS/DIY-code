#!/usr/bin/env python3
"""DeepSeek 实时同步桥 —— 本机接收端。

浏览器里的用户脚本会把网页版新产生的消息发到这里，本服务写进
knowledge/deepseek/ 知识库，和导出包同步的结果共用同一套文件。

常用命令:
    python tools/deepseek_bridge/server.py --setup     # 首次：生成令牌和用户脚本
    python tools/deepseek_bridge/server.py             # 启动服务（保持窗口开着）
    python tools/deepseek_bridge/server.py --port 8899 # 换端口
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deepseek_sync import (  # noqa: E402
    DEFAULT_ROOT,
    REPO_ROOT,
    merge_jsonl,
    normalize,
    parse_ts,
    render_transcript,
    safe_name,
    write_index,
)
from deepseek_pinned import sync_pinned  # noqa: E402

BRIDGE_DIR_NAME = "bridge"
RAW_LIMIT_BYTES = 50 * 1024 * 1024
DEFAULT_PORT = 8765
MAX_PULL_PER_BATCH = 40


# ------------------------------------------------------------------ 工具函数


def resolve_root(value: str) -> Path:
    root = Path(value)
    return root if root.is_absolute() else (REPO_ROOT / root).resolve()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def as_local(value) -> datetime | None:
    """把 unix 秒或 ISO 字符串统一成本机时区的 datetime，便于比较。"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value).astimezone()
    dt = parse_ts(value)
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.astimezone()


def pick_records(recs: list[dict], tolerance_seconds: int = 2) -> list[dict]:
    """同一会话里，导出记录和实时拉取的记录会重叠，这里挑出一份不重复的。

    规则：导出包是完整的权威版本，保留它的全部记录；实时记录里只保留
    比导出最新一条还新的（也就是导出之后新增的对话），其余视为重复丢弃。
    """
    export = [r for r in recs if r.get("source") != "live"]
    live = [r for r in recs if r.get("source") == "live"]
    if not export or not live:
        return sorted(recs, key=lambda r: r.get("index") or 0)

    newest = None
    for rec in export:
        stamp = as_local(rec.get("ts"))
        if stamp and (newest is None or stamp > newest):
            newest = stamp

    kept: list[dict] = []
    for rec in live:
        stamp = as_local(rec.get("ts"))
        if stamp is None or newest is None:
            kept.append(rec)
        elif stamp > newest + timedelta(seconds=tolerance_seconds):
            kept.append(rec)
    return sorted(export + kept, key=lambda r: r.get("index") or 0)


class Store:
    """知识库写入端：内存里维护实时会话，落盘时复用导出同步的逻辑。"""

    def __init__(self, root: Path, token: str):
        self.root = root
        self.token = token
        self.lock = threading.RLock()
        self.records: dict[str, list[dict]] = {}
        self.log_path = root / "data" / "bridge.log"
        self.raw_path = root / "data" / "live_raw.jsonl"
        self._last_ping_log = 0.0
        self.manifest_path = root / "data" / "manifest.json"
        self.manifest = {"conversations": {}}
        self.load()

    # -- 落盘 / 读取 -------------------------------------------------------

    def load(self) -> None:
        if self.manifest_path.exists():
            try:
                self.manifest = json.loads(
                    self.manifest_path.read_text(encoding="utf-8")
                )
            except json.JSONDecodeError:
                pass
        self.manifest.setdefault("conversations", {})
        jsonl = self.root / "data" / "messages.jsonl"
        if not jsonl.exists():
            return
        # 全部记录都读进来：实时捕获要和老会话的导出记录合并成同一份
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            cid = rec.get("conv_id")
            self.records.setdefault(cid, []).append(rec)
        for cid, recs in self.records.items():
            recs.sort(key=lambda r: r.get("index") or 0)

    def log(self, text: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {text}\n")
        print(f"[{stamp}] {text}", flush=True)

    def append_raw(self, payload: dict) -> None:
        try:
            if self.raw_path.exists() and self.raw_path.stat().st_size > RAW_LIMIT_BYTES:
                return
            self.raw_path.parent.mkdir(parents=True, exist_ok=True)
            with self.raw_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # -- 写入 --------------------------------------------------------------

    def ingest(self, payload: dict) -> dict:
        """单条消息（实时流式回复走这条）。"""
        return self.apply_messages(
            payload.get("conv_id"),
            payload.get("title"),
            payload.get("conv_created"),
            payload.get("model"),
            [payload],
        )

    def ingest_batch(self, payload: dict) -> dict:
        """一次发来整个会话的历史，避免逐条写盘。"""
        return self.apply_messages(
            payload.get("conv_id"),
            payload.get("title"),
            payload.get("conv_created"),
            payload.get("model"),
            payload.get("messages") or [],
        )

    def apply_messages(
        self,
        cid: str | None,
        title: str | None,
        created: str | None,
        model: str | None,
        items: list[dict],
    ) -> dict:
        cid = str(cid or "").strip()
        if not cid or not items:
            return {"ok": False, "reason": "缺少 conv_id 或消息内容"}

        with self.lock:
            recs = self.records.setdefault(cid, [])
            entry = self.manifest["conversations"].get(cid) or {}
            index_cursor = max([r.get("index") or 0 for r in recs], default=0) + 1
            # 会话里已经有导出包的记录时，实时消息一律排在最后，
            # 避免网页的 message_id 和导出包的顺序号互相打架
            has_export = any(r.get("source") != "live" for r in recs)
            room = title or entry.get("title") or "未命名会话"
            born = created or entry.get("created") or now_iso()
            fresh: list[dict] = []
            for item in items:
                fragments = item.get("fragments") or []
                if not fragments:
                    continue
                message = {
                    "fragments": fragments,
                    "inserted_at": item.get("ts") or now_iso(),
                    "model": item.get("model") or model or "",
                }
                parts = normalize(message)
                if not any(
                    [
                        parts["request"],
                        parts["response"],
                        parts["think"],
                        parts["searches"],
                    ]
                ):
                    continue
                node_id = item.get("node_id") or f"live-{len(recs) + 1}"
                previous = next(
                    (r for r in recs if r.get("node_id") == node_id), None
                )
                if previous and previous.get("index") is not None:
                    index = previous["index"]
                elif not has_export and isinstance(item.get("order"), (int, float)):
                    index = int(item["order"])
                else:
                    index = index_cursor
                index_cursor = max(index_cursor, index) + 1
                record = {
                    "conv_id": cid,
                    "title": room,
                    "conv_created": born,
                    "conv_updated": now_iso(),
                    "node_id": node_id,
                    "parent": None,
                    "index": index,
                    "ts": message["inserted_at"],
                    "model": message["model"],
                    "branch": False,
                    "on_path": True,
                    "source": "live",
                    **parts,
                }
                recs[:] = [r for r in recs if r.get("node_id") != node_id]
                recs.append(record)
                fresh.append(record)
            if not fresh:
                return {"ok": False, "reason": "内容为空"}
            recs.sort(key=lambda r: r.get("index") or 0)
            total = self.flush(cid, fresh)
        return {
            "ok": True,
            "conv_id": cid,
            "count": len(fresh),
            "total": total,
        }

    def save_sessions(self, sessions: list) -> dict:
        """保存会话列表快照，并顺带刷新「置顶会话」文件夹。"""
        path = self.root / "data" / "sessions.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"updated_at": now_iso(), "sessions": sessions},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        with self.lock:
            return sync_pinned(self.root, sessions)

    def needs_pull(self, sessions: list) -> list[str]:
        """哪些会话本地还没有内容，或者网页上比本地更新。"""
        need: list[str] = []
        for session in sessions:
            cid = session.get("id")
            if not cid:
                continue
            recs = self.records.get(cid)
            if not recs:
                need.append(cid)
                continue
            # 上次成功拉取的时间更有参考价值：网页的 updated_at 会因为
            # 置顶、重命名等操作变化，用它比较会天天都判定成"需要拉取"
            entry = self.manifest["conversations"].get(cid) or {}
            newest = as_local(entry.get("pulled_at"))
            if newest is None:
                for rec in recs:
                    stamp = as_local(rec.get("ts"))
                    if stamp and (newest is None or stamp > newest):
                        newest = stamp
            remote = as_local(session.get("updated_at"))
            if remote and (newest is None or remote > newest):
                need.append(cid)
        return need

    def flush(self, cid: str, records: list[dict]) -> int:
        """把该会话的所有记录（导出的 + 实时的）渲染成同一份 md。"""
        recs = pick_records(self.records.get(cid, []))
        if not recs:
            return int(self.manifest.get("total_messages") or 0)
        entry = self.manifest["conversations"].setdefault(cid, {})
        if entry.get("hash"):
            # 导出包里已有的会话：标题和文件名沿用导出版本
            created = entry.get("created") or recs[0].get("conv_created") or ""
            title = entry.get("title") or "未命名"
            fname = entry.get("file") or f"{created[:10]}_{safe_name(title, 45)}.md"
        else:
            # 只靠实时同步的会话：标题会随网页更新，文件名跟着改
            created = entry.get("created") or recs[0].get("conv_created") or ""
            title = recs[-1].get("title") or recs[0].get("title") or "未命名会话"
            stamp = created[:10] if created else datetime.now().strftime("%Y-%m-%d")
            fname = f"{stamp}_{safe_name(title, 45)}_live-{cid[:6]}.md"
            old = entry.get("file")
            if old and old != fname:
                stale = self.root / "transcripts" / old
                if stale.exists():
                    stale.unlink()
        (self.root / "transcripts").mkdir(parents=True, exist_ok=True)
        only_live = all(r.get("source") == "live" for r in recs)
        (self.root / "transcripts" / fname).write_text(
            render_transcript(
                recs, "浏览器实时同步" if only_live else "导出包 + 浏览器实时同步"
            ),
            encoding="utf-8",
        )
        entry.update(
            {
                "title": title,
                "created": created,
                "updated": recs[-1].get("conv_updated") or "",
                "file": fname,
                "messages": len(recs),
                "user": sum(1 for r in recs if r["request"]),
                "assistant": sum(1 for r in recs if r["response"]),
                "live_pending": True,
                "pulled_at": now_iso(),
            }
        )
        total = merge_jsonl(self.root / "data" / "messages.jsonl", records)
        self.manifest["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.manifest["total_messages"] = total
        self.manifest_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_index(self.root, self.manifest)
        return total

    def rebuild_all(self) -> dict:
        """按当前存储重新渲染所有会话，用于修正历史遗留的重复。"""
        fixed = 0
        for cid in list(self.records):
            raw = self.records[cid]
            picked = pick_records(raw)
            if len(picked) == len(raw):
                continue
            entry = self.manifest["conversations"].setdefault(cid, {})
            title = entry.get("title") or picked[0].get("title") or "未命名"
            created = entry.get("created") or picked[0].get("conv_created") or ""
            stamp = created[:10] if created else datetime.now().strftime("%Y-%m-%d")
            fname = entry.get("file") or f"{stamp}_{safe_name(title, 45)}.md"
            (self.root / "transcripts").mkdir(parents=True, exist_ok=True)
            (self.root / "transcripts" / fname).write_text(
                render_transcript(
                    picked,
                    "导出包 + 浏览器实时同步"
                    if any(r.get("source") != "live" for r in picked)
                    else "浏览器实时同步",
                ),
                encoding="utf-8",
            )
            entry.update(
                {
                    "title": title,
                    "created": created,
                    "file": fname,
                    "messages": len(picked),
                    "user": sum(1 for r in picked if r["request"]),
                    "assistant": sum(1 for r in picked if r["response"]),
                }
            )
            fixed += 1
        if fixed:
            kept_ids = set()
            for cid, recs in self.records.items():
                kept_ids.update(
                    (cid, r.get("node_id")) for r in pick_records(recs)
                )
            jsonl = self.root / "data" / "messages.jsonl"
            rows = []
            for line in jsonl.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                if (rec.get("conv_id"), rec.get("node_id")) in kept_ids:
                    rows.append(rec)
            with jsonl.open("w", encoding="utf-8", newline="\n") as fh:
                for rec in rows:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.manifest["total_messages"] = len(rows)
            self.manifest_path.write_text(
                json.dumps(self.manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            write_index(self.root, self.manifest)
        return {"ok": True, "fixed": fixed, "total": self.manifest.get("total_messages")}


# ----------------------------------------------------------------- HTTP 服务


def make_handler(store: Store, allow_raw: bool):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DeepSeekBridge/0.1"

        def log_message(self, *args):  # 静音默认日志
            pass

        def _reply(self, code: int, body: dict) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Bridge-Token")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._reply(204, {})

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/ping"):
                now = time.time()
                if now - store._last_ping_log > 60:
                    store._last_ping_log = now
                    ua = (self.headers.get("User-Agent") or "")[:60]
                    store.log(f"浏览器脚本在线（{ua}）")
                total = int(store.manifest.get("total_messages") or 0)
                self._reply(200, {"ok": True, "messages": total, "time": now_iso()})
            elif self.path.startswith("/install"):
                store.log("有人打开了脚本安装页")
                self._serve_userscript()
            elif self.path in ("/", "/index.html"):
                store.log("有人打开了服务首页")
                self._serve_home()
            else:
                self._reply(404, {"ok": False, "reason": "未知路径"})

        def _send_text(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _serve_userscript(self) -> None:
            """以 .user.js 形式返回脚本，Tampermonkey 会自动弹出安装界面。"""
            path = store.root / BRIDGE_DIR_NAME / "deepseek-bridge.user.js"
            if not path.exists():
                self._reply(404, {"ok": False, "reason": "还没生成用户脚本"})
                return
            self._send_text(
                path.read_bytes(), "text/javascript; charset=utf-8"
            )

        def _serve_home(self) -> None:
            total = int(store.manifest.get("total_messages") or 0)
            convs = len(store.manifest.get("conversations") or {})
            html = f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8">
<title>DeepSeek 同步桥</title>
<body style="font:16px/1.8 system-ui;max-width:640px;margin:60px auto;padding:0 20px">
<h1>DeepSeek 同步桥</h1>
<p>状态：<b style="color:#16833c">运行中</b>　已收录 {convs} 个会话 / {total} 条消息</p>
<h2>安装浏览器脚本</h2>
<ol>
  <li>先装 <a href="https://microsoftedge.microsoft.com/addons/detail/tampermonkey/iikmkjmpaadaobahmlepeloendndfphd" target="_blank">Tampermonkey</a>（点“获取”→ 确认添加）</li>
  <li>回到本页，点下面的链接 → 弹出安装界面 → 点“安装”</li>
</ol>
<p><a href="/install/deepseek-bridge.user.js" style="font-size:20px">安装同步脚本</a></p>
<p style="color:#666">装好后去 chat.deepseek.com 正常聊天，右下角会出现绿色标签。</p>
</body></html>"""
            self._send_text(html.encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._reply(400, {"ok": False, "reason": "JSON 解析失败"})
                return
            token = payload.get("token") or self.headers.get("X-Bridge-Token")
            if token != store.token:
                self._reply(403, {"ok": False, "reason": "令牌不匹配"})
                return
            path = self.path.split("?", 1)[0]
            if path == "/ingest":
                with store.lock:
                    store.append_raw(
                        {
                            "t": now_iso(),
                            "url": payload.get("url") or "",
                            "conv_id": payload.get("conv_id") or "",
                            "kind": "ingest",
                            "fragments": payload.get("fragments"),
                        }
                    )
                    result = store.ingest(payload)
                if result.get("ok"):
                    store.log(
                        "写入 %s / %d 条（累计 %d）"
                        % (result["conv_id"][:8], result["count"], result["total"])
                    )
                else:
                    store.log(f"忽略：{result.get('reason')}")
                self._reply(200 if result.get("ok") else 200, result)
            elif path == "/ingest_batch":
                result = store.ingest_batch(payload)
                if result.get("ok"):
                    store.log(
                        "批量写入 %s / %d 条（累计 %d）"
                        % (result["conv_id"][:8], result["count"], result["total"])
                    )
                else:
                    store.log(f"批量写入忽略：{result.get('reason')}")
                self._reply(200, result)
            elif path == "/raw" and allow_raw:
                with store.lock:
                    store.append_raw(payload)
                self._reply(200, {"ok": True})
            elif path == "/sessions":
                sessions = payload.get("sessions") or []
                result = store.save_sessions(sessions)
                need = store.needs_pull(sessions)
                if payload.get("force"):
                    need = [s.get("id") for s in sessions if s.get("id")]
                batch, rest = need[:MAX_PULL_PER_BATCH], need[MAX_PULL_PER_BATCH:]
                result["need"] = batch
                result["need_rest"] = len(rest)
                if result.get("ok"):
                    store.log(
                        "置顶会话已同步：%d 个（刷新 %d，删除 %d）；待拉取 %d 个会话，本批 %d 个"
                        % (
                            result["pinned"],
                            result["written"],
                            result["removed"],
                            len(need),
                            len(batch),
                        )
                    )
                else:
                    store.log(f"会话列表同步跳过：{result.get('reason')}")
                self._reply(200, result)
            else:
                self._reply(404, {"ok": False, "reason": "未知路径"})

    return Handler


# --------------------------------------------------------------------- 入口


class BridgeServer(ThreadingHTTPServer):
    """Windows 下 SO_REUSEADDR 会让第二个实例也能绑定成功、但收不到请求，
    所以这里显式关掉，宁可启动失败也不要静默空转。"""

    allow_reuse_address = False
    daemon_threads = True


def already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/ping", timeout=1.5
        ) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def ensure_setup(root: Path, port: int) -> tuple[Path, str]:
    """生成/读取令牌，并从模板渲染用户脚本。"""
    bridge_dir = root / BRIDGE_DIR_NAME
    bridge_dir.mkdir(parents=True, exist_ok=True)
    token_path = bridge_dir / "token.txt"
    if token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
    else:
        token = secrets.token_hex(16)
        token_path.write_text(token, encoding="utf-8")
    template = Path(__file__).resolve().parent / "userscript_template.js"
    target = bridge_dir / "deepseek-bridge.user.js"
    if template.exists():
        script = (
            template.read_text(encoding="utf-8")
            .replace("__TOKEN__", token)
            .replace("__PORT__", str(port))
        )
        target.write_text(script, encoding="utf-8")
    return target, token


def main() -> int:
    ap = argparse.ArgumentParser(description="DeepSeek 实时同步桥（本机接收端）")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="知识库根目录")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口")
    ap.add_argument("--setup", action="store_true", help="只生成令牌和用户脚本后退出")
    ap.add_argument("--rebuild", action="store_true", help="按存储重新渲染全部会话后退出")
    ap.add_argument("--no-raw", action="store_true", help="不保存原始报文（调试用）")
    args = ap.parse_args()

    root = resolve_root(args.root)
    script_path, token = ensure_setup(root, args.port)
    print(f"知识库      : {root}")
    print(f"用户脚本    : {script_path}")
    print(f"令牌        : {token[:8]}…（完整内容见 bridge/token.txt）")
    if args.setup:
        print("\n下一步：把上面的用户脚本装进 Tampermonkey，然后启动服务。")
        return 0

    store = Store(root, token)
    if args.rebuild:
        result = store.rebuild_all()
        print(
            f"重建完成：修正 {result['fixed']} 个会话，"
            f"当前总消息 {result['total']} 条"
        )
        return 0
    handler = make_handler(store, allow_raw=not args.no_raw)
    if already_running(args.port):
        print(f"端口 {args.port} 上已经有一个同步桥在运行，不用重复启动。")
        return 0
    try:
        httpd = BridgeServer(("127.0.0.1", args.port), handler)
    except OSError as exc:
        print(f"启动失败：端口 {args.port} 用不了（{exc}）。")
        print(f"换一个端口再试：start.cmd --port 8899（之后要重新 --setup）")
        return 1
    store.log(f"服务已启动 http://127.0.0.1:{args.port}（Ctrl+C 停止）")
    print("保持这个窗口开着，去 Edge 里正常聊天即可。", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。", flush=True)
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
