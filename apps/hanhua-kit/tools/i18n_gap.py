"""分析应用自带的语言包：有多少条、哪些还没翻译、哪些 key 缺失。

界面语言包是 Vite 打包出来的 JS chunk，形如：
    var e,t,n;  function x(){ e=`译文`, t=`译文2` }
    export{A as some_key, B as x8Kd2p}

用法：
    python tools/i18n_gap.py --asar <path> --locale zh-CN --compare zh-TW,ja-JP,de-DE
    python tools/i18n_gap.py --chunk .recon/zh-CN.js --csv .recon/gaps.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

sys_path = Path(__file__).resolve().parent
import sys  # noqa: E402

sys.path.insert(0, str(sys_path))
from asar_tool import Asar  # noqa: E402

_ASSIGN_RE = re.compile(r"([A-Za-z_$][\w$]*)\s*=\s*`")
_DECL_RE = re.compile(r"\bvar\s+([A-Za-z_$][\w$]*(?:\s*,\s*[A-Za-z_$][\w$]*)*)\s*;")
_EXPORT_RE = re.compile(r"export\s*\{([^}]*)\}")
_DOTTED_RE = re.compile(r'"([^"\\]{2,120})"\s*:\s*`')
_ASCII_ONLY = re.compile(r"^[\x20-\x7e]+$")
_HAS_LETTER = re.compile(r"[A-Za-z]")
# 允许保持英文的短词/品牌/技术名词
_WHITELIST = re.compile(
    r"^(?:[A-Z0-9]{1,6}|ChatGPT|OpenAI|Codex|GPT-?[\w.]*|API|URL|JSON|HTML|CSS|PDF|CSV|MD|ID|OK|"
    r"https?://\S+|[\w.+-]+@[\w-]+\.[\w.]+|\{\w+\}|[\d\s.,%:/#-]+)$"
)


def _extract_template_values(body: str) -> dict[str, str]:
    """按顺序抽取 ``var=\\`文本\\``` 赋值。"""
    values: dict[str, str] = {}
    position = 0
    while True:
        match = _ASSIGN_RE.search(body, position)
        if not match:
            break
        index = match.end()
        buffer: list[str] = []
        while index < len(body):
            char = body[index]
            if char == "\\":
                buffer.append(body[index : index + 2])
                index += 2
                continue
            if char == "`":
                break
            buffer.append(char)
            index += 1
        values[match.group(1)] = "".join(buffer)
        position = index + 1
    return values


def parse_chunk(text: str) -> dict:
    """返回 {key: 值}。

    语言包有两种条目：
      1. ``var e,t,n;function x(){e=`…`,t=`…`}export{…}`` —— 变量名会在不同模块里重用，
         所以按模块分别解析，再用 export 列表还原 key。
      2. ``"点分键名": `译文```（ICU 消息，含嵌套花括号）—— 直接正则配对。
    """
    declarations = list(_DECL_RE.finditer(text))
    exported: dict[str, str] = dict(_extract_dotted(text))
    for index, declaration in enumerate(declarations):
        end = declarations[index + 1].start() if index + 1 < len(declarations) else len(text)
        body = text[declaration.end() : end]
        values = _extract_template_values(body)
        if not values:
            continue
        for block in _EXPORT_RE.findall(body):
            for item in block.split(","):
                item = item.strip()
                if not item:
                    continue
                parts = [p.strip() for p in item.split(" as ")]
                source, key = (parts[0], parts[1]) if len(parts) == 2 else (parts[0], parts[0])
                if source in values:
                    exported[key] = values[source]
    return exported


def _extract_dotted(text: str) -> dict[str, str]:
    """抽取所有 ``"key": `value` `` 形式的条目。"""
    result: dict[str, str] = {}
    position = 0
    while True:
        match = _DOTTED_RE.search(text, position)
        if not match:
            break
        index = match.end()
        buffer: list[str] = []
        while index < len(text):
            char = text[index]
            if char == "\\":
                buffer.append(text[index : index + 2])
                index += 2
                continue
            if char == "`":
                break
            buffer.append(char)
            index += 1
        result[match.group(1)] = "".join(buffer)
        position = index + 1
    return result


def load_chunk(path: Path) -> dict:
    return parse_chunk(path.read_text(encoding="utf-8", errors="replace"))


def looks_untranslated(value: str) -> bool:
    if not value or not _ASCII_ONLY.match(value) or not _HAS_LETTER.search(value):
        return False
    if _WHITELIST.match(value.strip()):
        return False
    return len(value.strip()) >= 3


def find_locale_chunk(asar: Asar, locale: str) -> str:
    pattern = re.compile(rf"^webview/assets/{re.escape(locale)}-[0-9a-f]{{12}}\.js$")
    hits = [full for full, _info in asar.entries if pattern.match(full)]
    if not hits:
        raise SystemExit(f"没找到 {locale} 的语言包")
    return hits[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="分析自带语言包")
    parser.add_argument("--asar", default=None)
    parser.add_argument("--chunk", default=None, help="直接分析已导出的 chunk")
    parser.add_argument("--locale", default="zh-CN")
    parser.add_argument("--compare", default="", help="逗号分隔的其它语言，用于对比 key 覆盖率")
    parser.add_argument("--csv", default=None, help="把疑似未翻译的条目导出成 CSV")
    parser.add_argument("--json", default=None, help="把统计结果写成 JSON")
    args = parser.parse_args(argv)

    chunks: dict[str, dict] = {}
    if args.chunk:
        chunks[args.locale] = load_chunk(Path(args.chunk))
    else:
        if not args.asar:
            parser.error("需要 --asar 或 --chunk")
        archive = Asar(args.asar)
        wanted = [args.locale] + [c for c in args.compare.split(",") if c]
        for locale in wanted:
            inner = find_locale_chunk(archive, locale)
            temp = Path(".recon") / f"{locale}.js"
            temp.parent.mkdir(parents=True, exist_ok=True)
            temp.write_bytes(archive.read(inner))
            chunks[locale] = load_chunk(temp)
            print(f"  {locale}: {inner}")

    summary: dict[str, dict] = {}
    target = chunks[args.locale]
    for locale, data in chunks.items():
        untranslated = [k for k, v in data.items() if looks_untranslated(v)]
        summary[locale] = {
            "keys": len(data),
            "untranslated": len(untranslated),
            "sample": [data[k][:60] for k in untranslated[:8]],
        }

    print(f"\n== 各语言包规模 ==")
    for locale, info in summary.items():
        print(f"  {locale:<8} {info['keys']:>6} 条，疑似未翻译 {info['untranslated']:>5} 条")
        for sample in info["sample"][:3]:
            print(f"           · {sample}")

    if len(chunks) > 1:
        union: set[str] = set()
        for locale, data in chunks.items():
            if locale != args.locale:
                union |= set(data)
        missing = sorted(union - set(target))
        print(f"\n== key 覆盖：相对其它语言缺 {len(missing)} 条 ==")
        for key in missing[:10]:
            print(f"   缺 {key}")

    if args.csv:
        rows = [(k, target[k]) for k in target if looks_untranslated(target[k])]
        path = Path(args.csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["key", "原文", "译文"])
            for key, value in rows:
                writer.writerow([key, value, ""])
        print(f"\n已导出 {len(rows)} 条疑似未翻译 -> {path}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"统计已写入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
