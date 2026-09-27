#!/usr/bin/env python3
"""把 DeepSeek 里置顶的会话整理成一个独立文件夹。

数据来源：同步桥抓到的会话列表快照（带 pinned 标记）。整理结果放在
knowledge/deepseek/置顶会话/，取消置顶的会自动从文件夹里清掉。

命令行用法:
    python tools/deepseek_pinned.py            # 重新生成
    python tools/deepseek_pinned.py --list     # 只列出置顶会话

同步桥服务会在每次收到会话列表时自动调用下面的 sync_pinned()，
所以正常使用不需要手动运行。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deepseek_sync import DEFAULT_ROOT, REPO_ROOT, safe_name  # noqa: E402

PINNED_DIR = "置顶会话"
INDEX_NAME = "索引.md"
DIGEST_NAME = "摘要.md"
GENERATED_RE = re.compile(r"^\d{2}_")


def latest_sessions(root: Path) -> list[dict] | None:
    """取最近一次会话列表快照。优先读 sessions.json，其次翻原始报文。"""
    snapshot = root / "data" / "sessions.json"
    if snapshot.exists():
        try:
            data = json.loads(snapshot.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("sessions"):
                return data["sessions"]
            if isinstance(data, list) and data:
                return data
        except json.JSONDecodeError:
            pass

    raw = root / "data" / "live_raw.jsonl"
    if not raw.exists():
        return None
    for line in reversed(raw.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line or "fetch_page" not in line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "fetch_page" not in (row.get("api") or ""):
            continue
        try:
            data = json.loads(row["body"])
            sessions = data["data"]["biz_data"]["chat_sessions"]
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        if sessions:
            return sessions
    return None


def sync_pinned(root: Path, sessions: list[dict] | None = None) -> dict:
    """按置顶列表重建「置顶会话」文件夹，返回执行摘要。"""
    if sessions is None:
        sessions = latest_sessions(root)
    if not sessions:
        return {"ok": False, "reason": "没有会话列表快照"}

    pinned = [s for s in sessions if s.get("pinned")]
    manifest_path = root / "data" / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {"conversations": {}}
    )
    conversations = manifest.get("conversations", {})

    out_dir = root / PINNED_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    rows: list[dict] = []
    missing: list[str] = []
    for i, session in enumerate(pinned, 1):
        cid = session.get("id")
        entry = conversations.get(cid)
        if not entry:
            missing.append(session.get("title") or cid or "?")
            continue
        source = root / "transcripts" / entry["file"]
        if not source.exists():
            missing.append(entry.get("title") or cid)
            continue
        name = f"{i:02d}_{safe_name(entry.get('title') or '未命名', 48)}.md"
        target = out_dir / name
        # 内容没变就不重写，避免文件时间被无意义地刷新
        if not (target.exists() and target.read_bytes() == source.read_bytes()):
            shutil.copyfile(source, target)
        written.append(target)
        rows.append(
            {
                "index": i,
                "id": cid,
                "title": entry.get("title") or "未命名",
                "created": (entry.get("created") or "")[:10],
                "messages": entry.get("messages", 0),
                "file": name,
            }
        )

    stale = [
        p
        for p in out_dir.glob("*.md")
        if GENERATED_RE.match(p.name) and p not in written
    ]
    for path in stale:
        path.unlink()

    lines = [
        "# 置顶会话",
        "",
        f"共 {len(rows)} 个，整理时间 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "> 由 `tools/deepseek_pinned.py` 生成，同步桥会自动刷新。",
        "> 在 DeepSeek 里改了置顶，打开一次网页就会同步过来；取消置顶的会自动删除。",
        "",
        "| # | 会话 | 日期 | 消息 | 记录 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['index']} | {row['title']} | {row['created']} | "
            f"{row['messages']} | [打开]({row['file']}) |"
        )
    lines.append("")
    (out_dir / INDEX_NAME).write_text("\n".join(lines), encoding="utf-8")

    (out_dir / DIGEST_NAME).write_text(
        build_digest(root, rows), encoding="utf-8"
    )

    return {
        "ok": True,
        "pinned": len(pinned),
        "written": len(rows),
        "removed": len(stale),
        "missing": missing,
        "dir": str(out_dir),
        "titles": [r["title"] for r in rows],
    }


def first_turns(root: Path) -> dict[str, dict]:
    """从 messages.jsonl 里取出每个会话的第一轮问答，用于生成摘要。"""
    jsonl = root / "data" / "messages.jsonl"
    out: dict[str, dict] = {}
    if not jsonl.exists():
        return out
    for line in jsonl.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("on_path") is False:
            continue
        cid = rec.get("conv_id")
        if not cid:
            continue
        slot = out.setdefault(cid, {"ask": "", "reply": ""})
        if not slot["ask"] and rec.get("request"):
            slot["ask"] = rec["request"]
        if not slot["reply"] and rec.get("response"):
            slot["reply"] = rec["response"]
    return out


def brief(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit] + "……" if len(text) > limit else text


def build_digest(root: Path, rows: list[dict]) -> str:
    turns = first_turns(root)
    lines = [
        "# 置顶会话摘要",
        "",
        f"共 {len(rows)} 个，整理时间 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "> 每个会话只保留开场那一轮问答，用来快速了解这个项目在做什么。",
        "> 需要细节时再打开对应的完整记录。",
        "",
    ]
    for row in rows:
        turn = turns.get(row.get("id") or "", {})
        lines.append(f"## {row['index']}. {row['title']}")
        lines.append("")
        lines.append(
            f"- 日期：{row['created']}　消息数：{row['messages']}　"
            f"[完整记录]({row['file']})"
        )
        if turn.get("ask"):
            lines.append(f"- 用户：{brief(turn['ask'], 180)}")
        if turn.get("reply"):
            lines.append(f"- DeepSeek：{brief(turn['reply'], 320)}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="整理置顶会话")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--list", action="store_true", help="只列出，不生成文件")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_absolute():
        root = (REPO_ROOT / root).resolve()

    if args.list:
        sessions = latest_sessions(root)
        if not sessions:
            print("没有会话列表快照。先打开一次 DeepSeek 网页，再试。")
            return 1
        for i, s in enumerate([x for x in sessions if x.get("pinned")], 1):
            print(f"{i:2d}. {s.get('title')}  ({s.get('id')})")
        return 0

    result = sync_pinned(root)
    if not result.get("ok"):
        print(result.get("reason"))
        return 1
    print(f"置顶会话 {result['pinned']} 个，已整理 {result['written']} 个到：{result['dir']}")
    for i, title in enumerate(result["titles"], 1):
        print(f"  {i}. {title}")
    if result["removed"]:
        print(f"清理了 {result['removed']} 个不再置顶的文件")
    if result["missing"]:
        print("以下置顶会话在本地没有记录：" + "、".join(result["missing"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
