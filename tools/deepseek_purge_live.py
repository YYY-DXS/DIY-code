#!/usr/bin/env python3
"""清掉浏览器实时同步产生的记录（调试或重建时用）。

用法:
    python tools/deepseek_purge_live.py            # 清掉全部实时记录
    python tools/deepseek_purge_live.py --conv ID  # 只清某个会话
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deepseek_sync import DEFAULT_ROOT, REPO_ROOT, write_index  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="清除实时同步记录")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--conv", default=None, help="只清这个会话 ID")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_absolute():
        root = (REPO_ROOT / root).resolve()
    jsonl = root / "data" / "messages.jsonl"
    manifest_path = root / "data" / "manifest.json"
    if not jsonl.exists():
        print("没有 messages.jsonl，无需清理")
        return 0

    rows = [
        json.loads(line)
        for line in jsonl.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    def drop(rec: dict) -> bool:
        if rec.get("source") != "live":
            return False
        return args.conv is None or rec.get("conv_id") == args.conv

    keep = [r for r in rows if not drop(r)]
    removed = len(rows) - len(keep)
    with jsonl.open("w", encoding="utf-8", newline="\n") as fh:
        for rec in keep:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    manifest = {"conversations": {}}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.setdefault("conversations", {})
    remaining = {r.get("conv_id") for r in keep}
    for cid in list(manifest["conversations"]):
        entry = manifest["conversations"][cid]
        is_live = "live_pending" in entry or "_live-" in str(entry.get("file", ""))
        if not is_live:
            continue
        if args.conv and cid != args.conv:
            continue
        if cid in remaining:
            continue
        stale = root / "transcripts" / str(entry.get("file", ""))
        if stale.exists():
            stale.unlink()
        print(f"删除实时会话：{entry.get('title', '')[:24]} ({entry.get('file')})")
        del manifest["conversations"][cid]

    manifest["total_messages"] = len(keep)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_index(root, manifest)
    print(f"清掉 {removed} 条实时消息，剩余 {len(keep)} 条，会话 {len(manifest['conversations'])} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
