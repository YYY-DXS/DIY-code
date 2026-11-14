"""二进制侦察：在原生程序里定位内嵌的界面资源。

用法：
    python tools/binpeek.py codex.exe --find "index.html" --context 600
    python tools/binpeek.py codex.exe --find "zh-CN" --count
    python tools/binpeek.py codex.exe --strings 6 --limit 200
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def find_offsets(data: bytes, pattern: bytes, limit: int) -> list[int]:
    offsets: list[int] = []
    start = 0
    while len(offsets) < limit:
        index = data.find(pattern, start)
        if index < 0:
            break
        offsets.append(index)
        start = index + 1
    return offsets


def render(data: bytes, offset: int, span: int) -> str:
    chunk = data[max(0, offset - span) : offset + span]
    text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
    lines = []
    width = 96
    for i in range(0, len(text), width):
        absolute = max(0, offset - span) + i
        lines.append(f"  {absolute:#010x}  {text[i:i + width]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="在二进制文件里找内嵌资源")
    parser.add_argument("file")
    parser.add_argument("--find", action="append", default=[], help="要查找的字符串，可重复")
    parser.add_argument("--count", action="store_true", help="只统计出现次数")
    parser.add_argument("--context", type=int, default=400, help="每个命中点前后显示多少字节")
    parser.add_argument("--limit", type=int, default=5, help="每个模式最多显示几处")
    parser.add_argument("--strings", type=int, default=0, help="列出长度 >= N 的可打印字符串")
    parser.add_argument("--filter", default=None, help="--strings 时用正则过滤")
    args = parser.parse_args(argv)

    data = Path(args.file).read_bytes()
    print(f"# {args.file}  {len(data) / 1048576:.1f} MB")

    if args.strings:
        pattern = re.compile(args.filter) if args.filter else None
        found = 0
        for match in re.finditer(rb"[\x20-\x7e]{%d,}" % args.strings, data):
            text = match.group(0).decode("ascii", "replace")
            if pattern and not pattern.search(text):
                continue
            print(f"  {match.start():#010x}  {text[:200]}")
            found += 1
            if found >= args.limit:
                break
        return 0

    for needle in args.find:
        pattern = needle.encode("utf-8")
        offsets = find_offsets(data, pattern, 10_000)
        print(f'\n== "{needle}" 命中 {len(offsets)} 次')
        if args.count:
            continue
        for offset in offsets[: args.limit]:
            print(render(data, offset, args.context))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
