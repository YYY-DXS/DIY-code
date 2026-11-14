"""命令行入口。

典型用法：
    hanhua scan   demo/source
    hanhua extract demo/source -o strings.json
    hanhua translate strings.json --translator dict --glossary demo/glossary.csv --lang zh-CN
    hanhua export  strings.json -o review.csv      # 交给人工/Excel
    hanhua import  review.csv strings.json -o strings.zh.json
    hanhua apply   strings.zh.json -o out
    hanhua check   strings.zh.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, pipeline
from .tm import TranslationMemory, load_csv
from .translators import get_translator


def _load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _save(work: dict, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(work, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _memory(args) -> TranslationMemory:
    return TranslationMemory(args.tm)


def cmd_scan(args) -> int:
    report = pipeline.scan(args.path, args.include_all)
    if not report:
        print("没有识别到可汉化的资源文件。")
        return 1
    total = 0
    print(f"{'文件':<52}{'格式':<14}{'条数':>6}")
    print("-" * 74)
    for row in report:
        total += row["units"]
        print(f"{row['file'][-50:]:<52}{row['format']:<14}{row['units']:>6}")
        for sample in row["sample"]:
            print(f"    · {sample[:70]}")
    print("-" * 74)
    print(f"合计 {len(report)} 个文件 / {total} 条待翻译文本")
    return 0


def cmd_extract(args) -> int:
    work = pipeline.extract(args.path, lang=args.lang, include_all=args.include_all)
    _save(work, args.out)
    print(f"已提取 {len(work['units'])} 条 -> {args.out}")
    if work["skipped_files"]:
        print(f"跳过 {len(work['skipped_files'])} 个无法识别的文件")
    return 0


def cmd_translate(args) -> int:
    work = _load(args.work)
    lang = args.lang or work["meta"].get("lang", "en") + "-zh"
    memory = _memory(args)

    if args.glossary:
        for pattern in args.glossary:
            rows = _load_rows(pattern, "词典")
            memory.put_glossary(rows, lang)
            print(f"已载入词典 {pattern}：{len(rows)} 条")

    glossary_rows = memory.glossary(lang)
    if args.translator == "csv":
        if not args.csv:
            raise SystemExit("--translator csv 需要同时给出 --csv 译文表路径")
        _load_rows(args.csv, "译文表")  # 提前校验可读性并给出友好提示
    translator = get_translator(
        args.translator,
        memory=memory,
        lang=lang,
        model=args.model,
        base_url=args.base_url,
        batch_size=args.batch_size,
        allow_term_substitution=args.term_substitution,
        glossary=glossary_rows,
        target_lang=args.target_lang,
        app_context=args.context or work["meta"].get("app_context", ""),
        csv_path=args.csv,
    )

    try:
        stats = pipeline.translate(
            work,
            translator,
            lang,
            memory=memory,
            use_tm=not args.no_tm,
            retranslate=args.retranslate,
        )
    except RuntimeError as exc:  # 例如没配 API Key
        raise SystemExit(str(exc)) from exc
    work["meta"]["lang"] = lang
    work["meta"]["translator"] = translator.name
    _save(work, args.out)
    print(
        f"翻译完成：共 {stats['total']} 条 / 本次处理 {stats['todo']} 条 "
        f"（记忆库 {stats['tm']}，新译 {stats['translated']}，"
        f"待人工 {stats['review']}，校验失败 {stats['invalid']}）-> {args.out}"
    )
    if getattr(translator, "last_error", None):
        print(f"接口告警：{translator.last_error}", file=sys.stderr)
    return 0


def cmd_export(args) -> int:
    work = _load(args.work)
    count = pipeline.export_csv(work, args.out)
    print(f"已导出 {count} 条审校表 -> {args.out}（UTF-8 BOM，Excel 双击即可正确显示中文）")
    return 0


def _load_rows(path: str, label: str) -> list[dict]:
    """读 CSV 时给出人话的错误提示，而不是甩一个 traceback。"""
    from pathlib import Path as _Path

    if not _Path(path).exists():
        raise SystemExit(f"{label}文件不存在：{path}")
    try:
        return load_csv(path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise SystemExit(f"{label}文件读取失败（{path}）：{exc}") from exc


def cmd_import(args) -> int:
    work = _load(args.work)
    stats = pipeline.import_csv(work, args.csv)
    _save(work, args.out)
    print(
        f"已合并人工译文 {stats['applied']} 条"
        f"（新增 {stats['filled']}，覆盖 {stats['unchanged']}）-> {args.out}"
    )
    if stats["kept"]:
        print(f"仍有 {stats['kept']} 条未填译文")
    return 0


def cmd_apply(args) -> int:
    work = _load(args.work)
    result = pipeline.apply_work(
        work,
        root=args.root,
        outdir=args.out,
        in_place=args.in_place,
        include_review=args.include_review,
    )
    for path in result["written"]:
        print(f"已写出 {path}")
    for note in result["notes"]:
        print(f"提示：{note}")
    if result["skipped"]:
        print(f"跳过 {len(result['skipped'])} 条未完成/校验失败的条目（用 --include-review 可强写 review 条目）")
    return 0


def cmd_check(args) -> int:
    work = _load(args.work)
    problems = pipeline.check(work)
    errors = [p for p in problems if p["level"] == "error"]
    warnings = [p for p in problems if p["level"] == "warning"]
    for problem in problems:
        tag = "错误" if problem["level"] == "error" else "警告"
        print(f"[{tag}] {problem['id']}: {problem['message']}")
    total = len(work["units"])
    print(f"\n共 {total} 条：错误 {len(errors)}，警告 {len(warnings)}，通过 {total - len({p['id'] for p in problems})}")
    return 1 if errors else 0


def cmd_memory(args) -> int:
    memory = _memory(args)
    stats = memory.stats(args.lang)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hanhua",
        description="通用软件汉化流水线：提取 -> 翻译 -> 校验 -> 回写",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"hanhua {__version__}")
    parser.add_argument("--tm", default="hanhua-tm.sqlite", help="翻译记忆库文件（默认 hanhua-tm.sqlite）")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="扫描目录，看能抽多少条")
    p.add_argument("path")
    p.add_argument("--include-all", action="store_true", help="连 URL、标识符一起抽")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("extract", help="提取工作文件")
    p.add_argument("path")
    p.add_argument("-o", "--out", default="strings.json")
    p.add_argument("--lang", default="en", help="源语言标记")
    p.add_argument("--include-all", action="store_true")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("translate", help="翻译工作文件")
    p.add_argument("work")
    p.add_argument("-o", "--out", default="strings.zh.json")
    p.add_argument("--translator", default="dict", choices=["dict", "openai", "llm", "csv"])
    p.add_argument("--lang", default=None, help="目标语言代码，例如 zh-CN")
    p.add_argument("--glossary", action="append", help="术语/句段 CSV，可重复")
    p.add_argument("--csv", default=None, help="--translator csv 时的人工译文表")
    p.add_argument("--no-tm", action="store_true", help="不用翻译记忆库")
    p.add_argument("--retranslate", action="store_true", help="重译已有译文")
    p.add_argument("--term-substitution", action="store_true", help="离线模式也做术语替换（会产出半成品，需人工过一遍）")
    p.add_argument("--model", default="gpt-4o-mini")
    p.add_argument("--base-url", default=None, help="OpenAI 兼容接口地址，如 https://api.deepseek.com/v1")
    p.add_argument("--batch-size", type=int, default=20)
    p.add_argument("--target-lang", default="简体中文")
    p.add_argument("--context", default=None, help="给模型的应用背景说明")
    p.set_defaults(func=cmd_translate)

    p = sub.add_parser("export", help="导出审校 CSV")
    p.add_argument("work")
    p.add_argument("-o", "--out", default="review.csv")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("import", help="把人工填好的 CSV 合并回工作文件")
    p.add_argument("csv")
    p.add_argument("work")
    p.add_argument("-o", "--out", default="strings.human.json")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("apply", help="回写到资源文件")
    p.add_argument("work")
    p.add_argument("-o", "--out", default="out", help="输出目录（默认 out/）")
    p.add_argument("--root", default=None, help="资源根目录（默认取工作文件里的记录）")
    p.add_argument("--in-place", action="store_true", help="直接改原文件（会先备份 .bak）")
    p.add_argument("--include-review", action="store_true", help="连 review 状态的条目一起写")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("check", help="质检译文")
    p.add_argument("work")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("memory", help="查看翻译记忆库统计")
    p.add_argument("--lang", default=None)
    p.set_defaults(func=cmd_memory)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
