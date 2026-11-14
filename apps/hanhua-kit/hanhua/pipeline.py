"""流水线：提取 -> 翻译 -> 校验 -> 回写。"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import formats, placeholders
from .formats import SCAN_EXTENSIONS, detect_format, extract_file
from .tm import TranslationMemory
from .translators import Item, Translator

# 译文相对原文的长度上限，超过就提示可能撑破界面
LENGTH_RATIO_WARN = 2.2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def plural_forms(unit: dict, target: str) -> list[str]:
    """复数条目用 ``|`` 分隔多种形式，校验时逐个 form 检查占位符。"""
    if unit.get("meta", {}).get("plural_forms", 0) > 1 and "|" in target:
        forms = [part.strip() for part in target.split("|")]
        return [form for form in forms if form] or [target]
    return [target]


def target_problems(unit: dict, target: str) -> list[str]:
    """针对某条译文的问题列表（去重后返回）。"""
    problems = list(placeholders.leftovers(target))
    for form in plural_forms(unit, target):
        problems.extend(placeholders.validate(unit["source"], form))
    unique: list[str] = []
    for problem in problems:
        if problem not in unique:
            unique.append(problem)
    return unique


def scan_paths(root: str | Path) -> list[Path]:
    root = Path(root)
    if root.is_file():
        return [root]
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SCAN_EXTENSIONS
    )


def scan(root: str | Path, include_all: bool = False) -> list[dict]:
    """扫描目录，报告每个文件能抽多少条文本。"""
    report = []
    for path in scan_paths(root):
        fmt = detect_format(path)
        if not fmt:
            continue
        units = extract_file(path, fmt, include_all)
        report.append(
            {
                "file": str(path),
                "format": fmt,
                "units": len(units),
                "sample": [unit.source for unit in units[:3]],
            }
        )
    return report


def extract(root: str | Path, lang: str = "en", include_all: bool = False) -> dict:
    """把待翻译文本抽成工作文件（JSON）。"""
    root = Path(root).resolve()
    files = scan_paths(root)
    base = root if root.is_dir() else root.parent
    units: list[dict] = []
    skipped: list[str] = []
    for path in files:
        fmt = detect_format(path)
        if not fmt:
            skipped.append(str(path.relative_to(base)) if path.is_relative_to(base) else str(path))
            continue
        for unit in extract_file(path, fmt, include_all):
            relative = path.relative_to(base).as_posix() if path.is_relative_to(base) else path.name
            units.append(
                {
                    "id": f"u{len(units) + 1:05d}",
                    "file": relative,
                    "format": fmt,
                    "key": unit.key,
                    "line": unit.line,
                    "source": unit.source,
                    "target": "",
                    "status": "new",
                    "note": "",
                    "meta": unit.meta,
                }
            )
    return {
        "meta": {
            "tool": "hanhua",
            "root": str(base),
            "lang": lang,
            "created": _now(),
            "include_all": include_all,
        },
        "units": units,
        "skipped_files": skipped,
    }


def translate(
    work: dict,
    translator: Translator,
    lang: str,
    memory: TranslationMemory | None = None,
    use_tm: bool = True,
    retranslate: bool = False,
) -> dict:
    """把工作文件里的 unit 翻出来。返回统计信息。"""
    units = work["units"]
    todo = [
        unit
        for unit in units
        if retranslate or not unit.get("target") or unit.get("status") in ("new", "invalid")
    ]
    stats = {"total": len(units), "todo": len(todo), "tm": 0, "translated": 0, "review": 0, "invalid": 0}

    # 1) 优先查翻译记忆库
    pending: list[dict] = []
    if use_tm and memory is not None:
        cached = memory.get_many([unit["source"] for unit in todo], lang)
        for unit in todo:
            hit = cached.get(unit["source"])
            if hit:
                unit["target"] = hit
                unit["status"] = "tm"
                stats["tm"] += 1
            else:
                pending.append(unit)
    else:
        pending = list(todo)

    # 2) 真正调用翻译器（占位符先打码）
    items: list[Item] = []
    for unit in pending:
        masked, _tokens = placeholders.protect(unit["source"])
        items.append(
            Item(
                source=unit["source"],
                masked=masked,
                file=unit["file"],
                key=unit["key"],
                meta=unit.get("meta", {}),
            )
        )
    results = list(translator.translate(items)) if items else []
    if len(results) < len(pending):  # 翻译器漏返回时，剩余条目降级为待人工
        results.extend([None] * (len(pending) - len(results)))

    fresh: list[tuple[str, str, str, str]] = []
    for unit, masked_target in zip(pending, results):
        if masked_target is None:
            unit["status"] = "review"
            unit["note"] = "翻译器未给出结果，需人工处理"
            stats["review"] += 1
            continue
        target = placeholders.restore(masked_target).strip()
        problems = placeholders.leftovers(masked_target) + target_problems(unit, target)
        if not placeholders.is_valid(problems):
            unit["target"] = target
            unit["status"] = "invalid"
            unit["note"] = "；".join(problems)
            stats["invalid"] += 1
            continue
        unit["target"] = target
        unit["status"] = "translated"
        unit["note"] = "；".join(problems)
        stats["translated"] += 1
        if translator.trusted:
            fresh.append((unit["source"], target, translator.name, "translated"))

    if memory is not None and fresh:
        memory.put_many(fresh, lang)
    return stats


def check(work: dict) -> list[dict]:
    """独立质检：占位符、换行、标签、长度溢出、未翻译。"""
    problems: list[dict] = []
    for unit in work["units"]:
        target = unit.get("target") or ""
        if not target:
            problems.append({"id": unit["id"], "level": "error", "message": "未翻译"})
            continue
        for message in target_problems(unit, target):
            level = "error" if message.startswith("[错误]") else "warning"
            problems.append({"id": unit["id"], "level": level, "message": message})
        source, target_text = unit["source"], target
        longest = max(plural_forms(unit, target_text), key=len)
        if source and len(longest) / max(len(source), 1) > LENGTH_RATIO_WARN:
            problems.append(
                {
                    "id": unit["id"],
                    "level": "warning",
                    "message": f"译文长度是原文的 {len(longest) / len(source):.1f} 倍，可能撑破界面",
                }
            )
        if unit.get("meta", {}).get("plural_forms", 0) > 1 and "|" not in target_text:
            problems.append(
                {
                    "id": unit["id"],
                    "level": "warning",
                    "message": "复数条目只填了 1 种形式，请在译文里用 | 分隔复数形式",
                }
            )
    return problems


def apply_work(
    work: dict,
    root: str | Path | None = None,
    outdir: str | Path | None = None,
    in_place: bool = False,
    include_review: bool = False,
) -> dict:
    """把译文写回资源文件。默认写到 outdir（不碰原文件）。"""
    base = Path(root or work["meta"]["root"])
    ok_status = {"translated", "tm", "human"}
    if include_review:
        ok_status |= {"review"}

    grouped: dict[tuple[str, str], dict[str, str]] = {}
    skipped: list[dict] = []
    for unit in work["units"]:
        target = unit.get("target") or ""
        if unit.get("status") not in ok_status or not target:
            skipped.append({"id": unit["id"], "status": unit.get("status"), "source": unit["source"]})
            continue
        grouped.setdefault((unit["file"], unit["format"]), {})[unit["key"]] = target

    written: list[str] = []
    notes: list[str] = []
    for (relative, fmt), mapping in grouped.items():
        source_path = base / relative
        if in_place:
            out_path = source_path
            backup = source_path.with_name(source_path.name + ".bak")
            if not backup.exists():
                shutil.copy2(source_path, backup)
        else:
            out_path = Path(outdir or "out") / relative
        notes.extend(formats.apply_file(source_path, mapping, out_path, fmt))
        written.append(str(out_path))

    return {"written": written, "skipped": skipped, "notes": notes}


# --------------------------------------------------------------------------- #
# 人工往返：工作文件 <-> 审校 CSV
# --------------------------------------------------------------------------- #

CSV_COLUMNS = ["id", "文件", "位置", "原文", "译文", "状态", "备注"]


def export_csv(work: dict, path: str | Path) -> int:
    import csv

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for unit in work["units"]:
            writer.writerow(
                {
                    "id": unit["id"],
                    "文件": unit["file"],
                    "位置": unit["key"],
                    "原文": unit["source"],
                    "译文": unit.get("target") or "",
                    "状态": unit.get("status") or "",
                    "备注": unit.get("note") or "",
                }
            )
    return len(work["units"])


def import_csv(work: dict, path: str | Path) -> dict:
    """把人工填好的 CSV 合并回工作文件。"""
    import csv

    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_id = {row["id"]: row for row in rows if row.get("id")}
    updated = added = kept = 0
    for unit in work["units"]:
        row = by_id.get(unit["id"])
        if not row:
            kept += 1
            continue
        target = (row.get("译文") or row.get("target") or "").strip()
        if not target:
            kept += 1
            continue
        if target != unit.get("target"):
            added += 1
        else:
            updated += 1
        unit["target"] = target
        unit["status"] = "human"
        unit["note"] = (row.get("备注") or "").strip()
    return {"rows": len(rows), "applied": added + updated, "filled": added, "unchanged": updated, "kept": kept}
