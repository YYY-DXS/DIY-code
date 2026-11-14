"""翻译历史：追加式 JSONL，读最近 N 条。"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from .config import DATA_DIR, HISTORY_PATH


@dataclass
class Entry:
    ts: float
    engine: str
    source_lang: str
    target_lang: str
    src: str
    dst: str
    latency_ms: int = 0

    def when(self) -> str:
        return time.strftime("%m-%d %H:%M", time.localtime(self.ts))


def append(entry: Entry, limit: int = 500) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
    _trim(limit)


def _trim(limit: int) -> None:
    try:
        lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
        if len(lines) > limit:
            HISTORY_PATH.write_text("\n".join(lines[-limit:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def load_recent(limit: int = 60) -> list[Entry]:
    if not HISTORY_PATH.exists():
        return []
    out: list[Entry] = []
    try:
        lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
    except Exception:
        return []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
            out.append(
                Entry(
                    ts=raw.get("ts", 0.0),
                    engine=raw.get("engine", ""),
                    source_lang=raw.get("source_lang", ""),
                    target_lang=raw.get("target_lang", ""),
                    src=raw.get("src", ""),
                    dst=raw.get("dst", ""),
                    latency_ms=raw.get("latency_ms", 0),
                )
            )
        except Exception:
            continue
    return out


def clear() -> None:
    if HISTORY_PATH.exists():
        HISTORY_PATH.unlink()
