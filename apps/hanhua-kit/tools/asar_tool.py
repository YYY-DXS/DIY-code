"""asar（Electron 应用包）读取工具：只读列目录 / 导出单个文件。

asar 布局：
    [uint32=4][uint32=headerPickleSize][uint32=jsonSize][json 目录表][padding][文件数据区]

用法：
    python tools/asar_tool.py stat    app.asar
    python tools/asar_tool.py list    app.asar --filter "locales?/.*zh"
    python tools/asar_tool.py extract app.asar webview/index.html out/index.html
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import struct
from pathlib import Path


class Asar:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.size = self.path.stat().st_size
        with self.path.open("rb") as handle:
            head = handle.read(16)
            header_size = struct.unpack("<I", head[4:8])[0]
            text = handle.read(header_size).decode("utf-8", errors="replace")
            self.header, end = json.JSONDecoder().raw_decode(text)
            consumed = len(text[:end].encode("utf-8"))  # 字符下标换算回字节数
        # 数据区起点：16 字节 pickle 头 + JSON 正文，再按 4 字节对齐
        self.base = 16 + consumed
        self.base += (4 - self.base % 4) % 4
        self.entries: list[tuple[str, dict]] = []
        self._walk(self.header["files"], "")
        # 建立数据区索引，便于「按内容找文件」
        self.index = sorted(
            (self.base + int(info.get("offset", 0)), self.base + int(info.get("offset", 0)) + int(info["size"]), full)
            for full, info in self.entries
            if "offset" in info
        )
        self.index_starts = [start for start, _end, _full in self.index]

    def _walk(self, node: dict, prefix: str) -> None:
        for name, info in node.items():
            full = f"{prefix}/{name}" if prefix else name
            if "files" in info:
                self._walk(info["files"], full)
            else:
                self.entries.append((full, info))

    def read(self, inner_path: str) -> bytes:
        inner = "/" + inner_path.lstrip("/")
        for full, info in self.entries:
            if "/" + full == inner:
                offset = self.base + int(info.get("offset", 0))
                with self.path.open("rb") as handle:
                    handle.seek(offset)
                    return handle.read(int(info["size"]))
        raise KeyError(inner_path)

    def find(self, pattern: str) -> list[tuple[str, dict]]:
        regex = re.compile(pattern)
        return [(full, info) for full, info in self.entries if regex.search(full)]

    def locate(self, position: int) -> str | None:
        """把一个文件偏移映射成 asar 内部路径。"""
        slot = bisect.bisect_right(self.index_starts, position) - 1
        if slot < 0:
            return None
        start, end, full = self.index[slot]
        return full if start <= position < end else None

    def grep(self, needle: bytes, limit: int = 20) -> list[tuple[int, str]]:
        """在数据区里搜索字节串，返回 [(偏移, 内部路径)]。"""
        hits: list[tuple[int, str]] = []
        with self.path.open("rb") as handle:
            handle.seek(self.base)
            position = self.base
            overlap = max(0, len(needle) - 1)
            tail = b""
            while len(hits) < limit:
                chunk = handle.read(8 * 1024 * 1024)
                if not chunk:
                    break
                data = tail + chunk
                start = 0
                while True:
                    found = data.find(needle, start)
                    if found < 0:
                        break
                    absolute = position - len(tail) + found
                    inner = self.locate(absolute)
                    if inner:
                        hits.append((absolute, inner))
                        if len(hits) >= limit:
                            break
                    start = found + 1
                tail = data[-overlap:] if overlap else b""
                position += len(chunk)
        return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="读取 Electron app.asar")
    parser.add_argument("command", choices=["stat", "list", "extract", "grep"])
    parser.add_argument("asar")
    parser.add_argument("--filter", default=None, help="正则过滤路径")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--size-gt", type=int, default=0, help="只列大于该字节数的文件")
    parser.add_argument("--inner", default=None, help="extract 时要导出的内部路径")
    parser.add_argument("--out", default=None, help="extract 的输出文件")
    parser.add_argument("--needle", default=None, help="grep 要查找的字符串")
    args = parser.parse_args(argv)

    archive = Asar(args.asar)
    print(f"# {args.asar}: {len(archive.entries)} 个文件，数据区从 {archive.base:#x} 开始")

    if args.command == "stat":
        buckets: dict[str, int] = {}
        sizes: dict[str, int] = {}
        for full, info in archive.entries:
            top = full.split("/", 1)[0]
            buckets[top] = buckets.get(top, 0) + 1
            sizes[top] = sizes.get(top, 0) + int(info.get("size", 0))
        for top, count in sorted(buckets.items(), key=lambda kv: -sizes[kv[0]])[:30]:
            print(f"  {top:<44} {count:>6} 个文件 {sizes[top] / 1048576:>9.1f} MB")
        return 0

    if args.command == "list":
        rows = archive.find(args.filter) if args.filter else archive.entries
        rows = [r for r in rows if int(r[1].get("size", 0)) >= args.size_gt]
        rows.sort(key=lambda r: -int(r[1].get("size", 0)))
        for full, info in rows[: args.limit]:
            print(f"  {int(info['size']):>10}  {full}")
        print(f"  … 共 {len(rows)} 条")
        return 0

    if args.command == "grep":
        if not args.needle:
            parser.error("grep 需要 --needle")
        for offset, inner in archive.grep(args.needle.encode("utf-8"), args.limit):
            print(f"  {offset:#012x}  {inner}")
        return 0

    if not args.inner or not args.out:
        parser.error("extract 需要 --inner 和 --out")
    data = archive.read(args.inner)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"已导出 {len(data)} 字节 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
