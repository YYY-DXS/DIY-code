"""翻译记忆库(TM) + 术语表，落盘为单个 SQLite 文件。

TM 的价值：同一句话第二次出现时直接复用，重跑不会漂移，也省 API 费用。
术语表的价值：让 Backup/Restore/Repository 这种词在全文里译法一致。
"""

from __future__ import annotations

import csv
import hashlib
import re
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS segments (
    source_hash TEXT NOT NULL,
    lang        TEXT NOT NULL,
    source      TEXT NOT NULL,
    target      TEXT NOT NULL,
    translator  TEXT,
    status      TEXT,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (source_hash, lang)
);
CREATE TABLE IF NOT EXISTS glossary (
    source TEXT NOT NULL,
    lang   TEXT NOT NULL,
    target TEXT NOT NULL,
    kind   TEXT NOT NULL DEFAULT 'term',
    note   TEXT,
    PRIMARY KEY (source, lang)
);
"""

_SOURCE_ALIASES = {"source", "src", "en", "english", "term", "原文", "原词", "英文"}
_TARGET_ALIASES = {"target", "dst", "zh", "chinese", "translation", "译文", "中文"}
_KIND_ALIASES = {"kind", "type", "类型"}


def norm(text: str) -> str:
    """归一化：折叠空白、去掉首尾空白、大小写无关。"""
    return re.sub(r"\s+", " ", text).strip().casefold()


def digest(text: str) -> str:
    return hashlib.sha1(norm(text).encode("utf-8")).hexdigest()


def load_csv(path: str | Path) -> list[dict]:
    """读取 CSV/TSV 词典。列名灵活：source/target/kind 或 原文/译文/类型。"""
    path = Path(path)
    delimiter = "\t" if path.suffix.lower() in (".tsv", ".tab") else ","
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=delimiter))
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        return []

    header = [cell.strip().lower() for cell in rows[0]]
    mapped = {}
    for index, name in enumerate(header):
        if name in _SOURCE_ALIASES:
            mapped["source"] = index
        elif name in _TARGET_ALIASES:
            mapped["target"] = index
        elif name in _KIND_ALIASES:
            mapped["kind"] = index

    if "source" in mapped and "target" in mapped:
        body = rows[1:]
    else:  # 无表头，按 原文,译文[,类型] 处理
        mapped = {"source": 0, "target": 1, "kind": 2}
        body = rows

    result: list[dict] = []
    for row in body:
        if len(row) <= max(mapped["source"], mapped["target"]):
            continue
        source = row[mapped["source"]].strip()
        target = row[mapped["target"]].strip()
        if not source or not target:
            continue
        kind = "term"
        if "kind" in mapped and len(row) > mapped["kind"]:
            kind = row[mapped["kind"]].strip().lower() or "term"
        result.append({"source": source, "target": target, "kind": kind})
    return result


class TranslationMemory:
    def __init__(self, path: str | Path = "tm.sqlite") -> None:
        self.path = Path(path)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------------- 句段记忆 ---------------- #
    def get(self, source: str, lang: str) -> str | None:
        row = self.conn.execute(
            "SELECT target FROM segments WHERE source_hash = ? AND lang = ?",
            (digest(source), lang),
        ).fetchone()
        return row[0] if row else None

    def get_many(self, sources: list[str], lang: str) -> dict[str, str]:
        wanted = {digest(s): s for s in sources}
        found: dict[str, str] = {}
        for source_hash, target in self.conn.execute(
            "SELECT source_hash, target FROM segments WHERE lang = ?", (lang,)
        ):
            if source_hash in wanted:
                found[wanted[source_hash]] = target
        return found

    def put_many(self, rows: list[tuple[str, str, str, str]], lang: str) -> int:
        """rows: [(source, target, translator, status)]"""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.conn.executemany(
            "INSERT INTO segments(source_hash, lang, source, target, translator, status, updated_at)"
            " VALUES(?,?,?,?,?,?,?)"
            " ON CONFLICT(source_hash, lang) DO UPDATE SET"
            " target=excluded.target, translator=excluded.translator,"
            " status=excluded.status, updated_at=excluded.updated_at",
            [(digest(s), lang, s, t, who, status, now) for s, t, who, status in rows],
        )
        self.conn.commit()
        return len(rows)

    # ---------------- 术语表 ---------------- #
    def put_glossary(self, rows: list[dict], lang: str) -> int:
        self.conn.executemany(
            "INSERT INTO glossary(source, lang, target, kind, note) VALUES(?,?,?,?,?)"
            " ON CONFLICT(source, lang) DO UPDATE SET target=excluded.target, kind=excluded.kind",
            [
                (row["source"], lang, row["target"], row.get("kind", "term"), row.get("note"))
                for row in rows
            ],
        )
        self.conn.commit()
        return len(rows)

    def glossary(self, lang: str, kind: str | None = None) -> list[dict]:
        sql = "SELECT source, target, kind FROM glossary WHERE lang = ?"
        params: list = [lang]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        return [
            {"source": s, "target": t, "kind": k}
            for s, t, k in self.conn.execute(sql, params)
        ]

    def stats(self, lang: str | None = None) -> dict:
        where, params = ("WHERE lang = ?", [lang]) if lang else ("", [])
        segments = self.conn.execute(
            f"SELECT COUNT(*) FROM segments {where}", params
        ).fetchone()[0]
        terms = self.conn.execute(
            "SELECT COUNT(*) FROM glossary" + (" WHERE lang = ?" if lang else ""), params
        ).fetchone()[0]
        return {"segments": segments, "glossary": terms, "path": str(self.path)}

    def close(self) -> None:
        self.conn.close()
