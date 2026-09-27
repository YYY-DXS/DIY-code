#!/usr/bin/env python3
"""把 DeepSeek 官方导出包同步进本地知识库（增量、可重复运行）。

用法:
    python tools/deepseek_sync.py "路径/deepseek_data-YYYY-MM-DD.zip"
    python tools/deepseek_sync.py "路径/conversations.json" --root knowledge/deepseek

产物:
    knowledge/deepseek/data/messages.jsonl   结构化消息（每行一条节点）
    knowledge/deepseek/data/manifest.json    同步状态（用于增量判定）
    knowledge/deepseek/transcripts/*.md      人类可读的对话记录
    knowledge/deepseek/index.md              会话总览
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = REPO_ROOT / "knowledge" / "deepseek"

CONTENT_TYPES = ("REQUEST", "RESPONSE", "THINK")
SEARCH_TYPES = ("SEARCH", "TOOL_SEARCH")


# ---------------------------------------------------------------- 读取导出包


def load_conversations(src: Path) -> list[dict]:
    """从 zip 或 conversations.json 里读出会话数组。"""
    if src.suffix.lower() == ".zip":
        with zipfile.ZipFile(src) as z:
            names = [n for n in z.namelist() if n.endswith("conversations.json")]
            if not names:
                raise SystemExit(f"压缩包里没找到 conversations.json: {src}")
            raw = z.read(names[0]).decode("utf-8")
    else:
        raw = src.read_text(encoding="utf-8")
    data = json.loads(raw)
    if isinstance(data, dict):  # 容错：某些版本会包一层
        data = data.get("conversations") or data.get("data") or []
    return data


def parse_ts(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    # 网页接口有时给 UTC 时间，统一换算成本机时区再显示
    return dt.astimezone() if dt.tzinfo is not None else dt


def fmt_ts(value) -> str:
    dt = parse_ts(value)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


# ------------------------------------------------------- 从对话树还原主分支


def main_path(mapping: dict) -> list[str]:
    """对话树可能有分支（重新生成/编辑），取最长的那条作为主分支。"""
    roots = [nid for nid, n in mapping.items() if not n.get("parent")]
    if not roots:
        return []
    height_memo: dict[str, int] = {}

    def height(nid: str) -> int:
        if nid in height_memo:
            return height_memo[nid]
        kids = [c for c in (mapping[nid].get("children") or []) if c in mapping]
        height_memo[nid] = 1 + max((height(c) for c in kids), default=0)
        return height_memo[nid]

    path: list[str] = []
    cur = roots[0]
    while cur and cur in mapping:
        path.append(cur)
        kids = [c for c in (mapping[cur].get("children") or []) if c in mapping]
        if not kids:
            break
        cur = max(kids, key=height)
    return path


# --------------------------------------------------------------- 消息归一化


def normalize(msg: dict) -> dict:
    """把 fragments 拆成 request / response / think / searches / files。"""
    out = {
        "request": [],
        "response": [],
        "think": [],
        "searches": [],
        "files": [],
        "order": [],
    }
    for frag in msg.get("fragments") or []:
        kind = frag.get("type")
        if kind in CONTENT_TYPES:
            out[kind.lower()].append(frag.get("content") or "")
            out["order"].append(kind)
        elif kind in SEARCH_TYPES:
            for item in frag.get("results") or []:
                if isinstance(item, dict):
                    out["searches"].append(
                        {"title": item.get("title") or "", "url": item.get("url") or ""}
                    )
            out["order"].append("SEARCH")
        elif kind == "FILE":
            for item in frag.get("files") or []:
                if isinstance(item, dict):
                    out["files"].append(
                        {
                            "name": item.get("file_name") or "",
                            "bytes": item.get("file_size") or 0,
                        }
                    )
            out["order"].append("FILE")
        # TOOL_OPEN 之类的空壳直接丢弃
    out["request"] = "\n\n".join(t for t in out["request"] if t.strip())
    out["response"] = "\n\n".join(t for t in out["response"] if t.strip())
    out["think"] = "\n\n".join(t for t in out["think"] if t.strip())
    return out


def conversation_records(conv: dict, source: str) -> list[dict]:
    mapping = conv.get("mapping") or {}
    path = main_path(mapping)
    on_path = set(path)
    records = []
    for index, nid in enumerate(path):
        node = mapping[nid]
        msg = node.get("message")
        if not msg:
            continue
        parts = normalize(msg)
        if not any(
            [parts["request"], parts["response"], parts["think"], parts["searches"]]
        ):
            continue
        records.append(
            {
                "conv_id": conv.get("id"),
                "title": conv.get("title") or "未命名",
                "conv_created": conv.get("inserted_at"),
                "conv_updated": conv.get("updated_at"),
                "node_id": nid,
                "parent": node.get("parent"),
                "index": index,
                "ts": msg.get("inserted_at"),
                "model": msg.get("model") or "",
                "branch": any(
                    len(mapping[c].get("children") or []) > 1
                    for c in [node.get("parent")]
                    if c in mapping
                ),
                "on_path": nid in on_path,
                "source": source,
                **parts,
            }
        )
    # 未被选中的分支节点也留档，标记 on_path=False
    for nid, node in mapping.items():
        if nid in on_path:
            continue
        msg = node.get("message")
        if not msg:
            continue
        parts = normalize(msg)
        if not any([parts["request"], parts["response"], parts["think"]]):
            continue
        records.append(
            {
                "conv_id": conv.get("id"),
                "title": conv.get("title") or "未命名",
                "conv_created": conv.get("inserted_at"),
                "conv_updated": conv.get("updated_at"),
                "node_id": nid,
                "parent": node.get("parent"),
                "index": -1,
                "ts": msg.get("inserted_at"),
                "model": msg.get("model") or "",
                "branch": True,
                "on_path": False,
                "source": source,
                **parts,
            }
        )
    records.sort(key=lambda r: r["index"])
    return records


# ------------------------------------------------------------------ 渲染 md


def safe_name(text: str, limit: int = 60) -> str:
    text = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", text or "")
    text = re.sub(r"\s+", " ", text).strip().strip(".")
    return text[:limit] or "untitled"


def render_transcript(records: list[dict], source: str) -> str:
    head = records[0]
    turns = sum(1 for r in records if r["request"])
    replies = sum(1 for r in records if r["response"])
    lines = [
        f"# {head['title']}",
        "",
        f"- 会话 ID：`{head['conv_id']}`",
        f"- 创建时间：{fmt_ts(head['conv_created'])}",
        f"- 最后更新：{fmt_ts(head['conv_updated'])}",
        f"- 用户发言 {turns} 条 / 助手回复 {replies} 条",
        f"- 来源：`{source}`",
        "",
        f"> 本文由同步工具自动整理（{source}），思考过程与联网搜索结果折叠在下面。",
        "",
        "---",
        "",
    ]
    seen_urls: set[str] = set()
    turn_no = 0
    for rec in records:
        if rec["request"]:
            turn_no += 1
            lines += [f"## {turn_no}. 用户 · {fmt_ts(rec['ts'])}", "", rec["request"], ""]
        if rec["think"]:
            lines += [
                "<details><summary>思考过程</summary>",
                "",
                rec["think"],
                "",
                "</details>",
                "",
            ]
        if rec["response"]:
            lines += [f"## DeepSeek · {fmt_ts(rec['ts'])}", "", rec["response"], ""]
        fresh = [
            s for s in rec["searches"] if s["url"] and s["url"] not in seen_urls
        ]
        for s in fresh:
            seen_urls.add(s["url"])
        if fresh:
            lines += [
                "<details><summary>联网搜索（%d 条）</summary>" % len(fresh),
                "",
            ]
            lines += [f"- [{s['title'] or s['url']}]({s['url']})" for s in fresh]
            lines += ["", "</details>", ""]
        for f in rec["files"]:
            lines += [f"> 附件：{f['name']}（{f['bytes']} 字节）", ""]
    return "\n".join(lines).rstrip() + "\n"


# ------------------------------------------------------------------- 主流程


def fingerprint(conv: dict) -> str:
    blob = json.dumps(conv, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def merge_jsonl(
    path: Path, records: list[dict], drop_live_for: set[str] | None = None
) -> int:
    """按 (conv_id, node_id) 合并，返回合并后的总条数。

    drop_live_for 里的会话，会先清掉浏览器实时同步的临时记录——导出包是
    权威版本，同一条消息在两边都有时以导出为准，避免重复。
    """
    existing: dict[tuple, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            existing[(obj.get("conv_id"), obj.get("node_id"))] = obj
    if drop_live_for:
        for key, obj in list(existing.items()):
            if obj.get("source") == "live" and obj.get("conv_id") in drop_live_for:
                del existing[key]
    for rec in records:
        existing[(rec["conv_id"], rec["node_id"])] = rec
    ordered = sorted(
        existing.values(),
        key=lambda r: (r.get("conv_created") or "", r.get("conv_id") or "", r.get("index") or 0),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for obj in ordered:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
    return len(ordered)


def write_index(root: Path, manifest: dict) -> None:
    rows = sorted(
        manifest["conversations"].values(),
        key=lambda c: c["created"],
        reverse=True,
    )
    total_msgs = sum(c["user"] + c["assistant"] for c in rows)
    lines = [
        "# DeepSeek 对话记录总览",
        "",
        f"- 会话数：{len(rows)}",
        f"- 消息数：{total_msgs}",
        f"- 最近同步：{manifest.get('generated_at', '')}",
        f"- 数据来源：`{manifest.get('source', '')}`",
        "",
        "| 日期 | 会话 | 用户 | 助手 | 记录 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in rows:
        date = (c["created"] or "")[:10]
        lines.append(
            f"| {date} | {c['title']} | {c['user']} | {c['assistant']} | "
            f"[打开](transcripts/{c['file']}) |"
        )
    lines.append("")
    lines.append(
        "检索整个知识库：`rg -i \"关键词\" knowledge/deepseek/transcripts`"
    )
    lines.append("")
    (root / "index.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="同步 DeepSeek 导出数据到本地知识库")
    ap.add_argument("source", help="导出 zip 或 conversations.json 的路径")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="知识库根目录")
    ap.add_argument("--force", action="store_true", help="忽略增量判定，全部重写")
    args = ap.parse_args()

    src = Path(args.source).expanduser().resolve()
    if not src.exists():
        raise SystemExit(f"找不到文件：{src}")
    root = Path(args.root)
    if not root.is_absolute():
        root = (REPO_ROOT / root).resolve()
    transcripts = root / "transcripts"
    transcripts.mkdir(parents=True, exist_ok=True)

    manifest_path = root / "data" / "manifest.json"
    manifest = {"conversations": {}}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.setdefault("conversations", {})

    source_label = str(src)
    conversations = load_conversations(src)
    added = updated = skipped = 0
    new_records: list[dict] = []
    covered: set[str] = set()

    for conv in conversations:
        cid = conv.get("id")
        if not cid:
            continue
        digest = fingerprint(conv)
        prev = manifest["conversations"].get(cid)
        if prev and prev.get("hash") == digest and not args.force:
            skipped += 1
            continue
        recs = conversation_records(conv, source_label)
        if not recs:
            continue
        new_records.extend(recs)
        covered.add(cid)
        created = conv.get("inserted_at") or ""
        fname = (prev or {}).get("file") or (
            f"{created[:10]}_{safe_name(conv.get('title'))}.md"
        )
        if not (prev or {}).get("file") and (transcripts / fname).exists():
            fname = f"{created[:10]}_{safe_name(conv.get('title'), 45)}_{cid[:6]}.md"
        if (
            prev
            and prev.get("live_pending")
            and prev.get("file")
            and prev["file"] != fname
        ):
            stale = transcripts / prev["file"]
            if stale.exists():
                stale.unlink()
        (transcripts / fname).write_text(
            render_transcript(recs, source_label), encoding="utf-8"
        )
        manifest["conversations"][cid] = {
            "title": conv.get("title") or "未命名",
            "created": created,
            "updated": conv.get("updated_at") or "",
            "hash": digest,
            "file": fname,
            "messages": len(recs),
            "user": sum(1 for r in recs if r["request"]),
            "assistant": sum(1 for r in recs if r["response"]),
        }
        if prev:
            updated += 1
        else:
            added += 1

    total = merge_jsonl(
        root / "data" / "messages.jsonl", new_records, drop_live_for=covered
    )
    manifest["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    manifest["source"] = source_label
    manifest["total_messages"] = total
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_index(root, manifest)

    print(f"源文件      : {src}")
    print(f"知识库      : {root}")
    print(f"新增会话    : {added}")
    print(f"更新会话    : {updated}")
    print(f"跳过（未变）: {skipped}")
    print(f"消息总条数  : {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
