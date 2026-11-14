#!/usr/bin/env python3
"""Import Codex conversation history into a workspace.

Scans the Codex home directory for rollout JSONL sessions, renders every
conversation as a readable Markdown transcript, writes an index, and can keep a
byte-identical copy of the original rollout files.

Standard library only. Run directly:

    python import_codex_history.py --out ./codex-history

The plugin wrapper calls the same script with --json and parses the summary.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
STATE_FILE = ".codex-import.json"
DEFAULT_TOOL_OUTPUT_LIMIT = 8000
MAX_TITLE_CHARS = 80
MAX_SLUG_CHARS = 36

CONTEXT_MESSAGE_PREFIXES = (
    "<environment_context>",
    "# AGENTS.md instructions",
    "<user_instructions>",
)

FENCE_LANGS = {
    "exec_command": "powershell",
    "shell": "powershell",
}

WARNINGS: list[str] = []


def warn(message: str) -> None:
    WARNINGS.append(message)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value):
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def iso(dt) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_time(dt) -> str:
    if dt is None:
        return ""
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def one_line(text: str, limit: int = 0) -> str:
    flat = re.sub(r"\s+", " ", text or "").strip()
    if limit and len(flat) > limit:
        flat = flat[: limit - 1].rstrip() + "…"
    return flat


def yaml_str(value: str) -> str:
    return json.dumps(value or "", ensure_ascii=False)


def fence(text: str, lang: str = "") -> str:
    runs = re.findall(r"`{3,}", text or "")
    size = max([len(run) for run in runs], default=2) + 1
    size = max(3, size)
    bar = "`" * size
    body = (text or "").rstrip("\n")
    return f"{bar}{lang}\n{body}\n{bar}"


def truncate(text: str, limit: int):
    if limit <= 0 or len(text) <= limit:
        return text, 0
    head = int(limit * 0.6)
    tail = max(0, limit - head)
    omitted = len(text) - head - tail
    marker = f"\n\n…（此处省略 {omitted:,} 个字符；原始记录见 raw/，或用 --full-tool-output 重新导入）…\n\n"
    return text[:head].rstrip("\n") + marker + text[-tail:].lstrip("\n"), omitted


# --------------------------------------------------------------------------- #
# Discovery and metadata
# --------------------------------------------------------------------------- #


@dataclass
class Segment:
    path: Path
    rel: str
    archived: bool
    thread_id: str
    created: str | None
    cwd: str | None
    provider: str | None
    model: str | None
    size: int
    mtime_ns: int


def iter_rollouts(root: Path):
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in sorted(filenames):
            if filename.endswith(".jsonl"):
                yield Path(dirpath) / filename


def read_session_meta(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if record.get("type") == "session_meta":
                    payload = record.get("payload")
                    return payload if isinstance(payload, dict) else {}
                break
    except (OSError, json.JSONDecodeError) as exc:
        warn(f"无法读取会话元数据 {path.name}: {exc}")
    return {}


UUID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I
)


def thread_id_from_name(path: Path) -> str:
    match = UUID_RE.search(path.stem)
    return match.group(1) if match else path.stem


def discover(codex_home: Path, include_archived: bool):
    segments: list[Segment] = []
    roots = [("sessions", codex_home / "sessions", False)]
    if include_archived:
        roots.append(("archived_sessions", codex_home / "archived_sessions", True))
    for prefix, root, archived in roots:
        if not root.is_dir():
            continue
        for path in iter_rollouts(root):
            meta = read_session_meta(path)
            stat = path.stat()
            rel = f"{prefix}/{path.relative_to(root).as_posix()}"
            segments.append(
                Segment(
                    path=path,
                    rel=rel,
                    archived=archived,
                    thread_id=str(meta.get("session_id") or meta.get("id") or thread_id_from_name(path)),
                    created=meta.get("timestamp"),
                    cwd=meta.get("cwd"),
                    provider=meta.get("model_provider"),
                    model=meta.get("model"),
                    size=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                )
            )
    segments.sort(key=lambda seg: (seg.created or "", seg.path.name))
    return segments


def load_titles(codex_home: Path) -> dict[str, str]:
    index = codex_home / "session_index.jsonl"
    best: dict[str, tuple[str, str]] = {}
    if not index.is_file():
        return {}
    try:
        with index.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                thread_id = record.get("id")
                name = one_line(str(record.get("thread_name") or ""))
                if not thread_id or not name:
                    continue
                updated = str(record.get("updated_at") or "")
                if thread_id not in best or updated >= best[thread_id][0]:
                    best[thread_id] = (updated, name)
    except OSError as exc:
        warn(f"无法读取 session_index.jsonl: {exc}")
    return {thread_id: name for thread_id, (_updated, name) in best.items()}


# --------------------------------------------------------------------------- #
# Parsing rollouts into turns
# --------------------------------------------------------------------------- #


@dataclass
class Entry:
    kind: str  # user | assistant | developer | reasoning | tool_call | tool_output | note | unknown
    ts: str | None = None
    text: str = ""
    name: str = ""
    call_id: str = ""
    args: object = None
    raw: object = None
    output: str | None = None
    output_chars: int = 0


@dataclass
class Turn:
    id: str | None
    ts: str | None
    status: str = "unknown"
    entries: list[Entry] = field(default_factory=list)

    def counts(self) -> dict:
        result = {"user": 0, "assistant": 0, "toolCalls": 0}
        for entry in self.entries:
            if entry.kind == "user":
                result["user"] += 1
            elif entry.kind == "assistant":
                result["assistant"] += 1
            elif entry.kind == "tool_call":
                result["toolCalls"] += 1
        return result


def content_text(payload: dict) -> str:
    parts: list[str] = []
    for item in payload.get("content") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind in ("input_text", "output_text", "text", "reasoning_text", "summary_text"):
            parts.append(str(item.get("text") or ""))
        elif kind == "input_image":
            parts.append("![图片]")
    return "".join(parts)


def reasoning_text(payload: dict) -> str:
    parts: list[str] = []
    for item in payload.get("summary") or []:
        if isinstance(item, dict) and item.get("text"):
            parts.append(str(item["text"]))
    if not parts:
        parts.append(content_text(payload))
    return "\n\n".join(part for part in parts if part.strip())


def parse_arguments(value):
    """Turn a JSON-encoded argument string into a value; keep other strings."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def clean_user_text(text: str) -> tuple[str | None, str]:
    """Return (message, attachments) with Codex-injected context removed."""
    stripped = (text or "").strip()
    if not stripped:
        return None, ""
    for prefix in CONTEXT_MESSAGE_PREFIXES:
        if stripped.startswith(prefix):
            return None, ""
    attachments = ""
    wrapper = stripped
    if "## My request:" in stripped:
        head, _, tail = stripped.partition("## My request:")
        names = re.findall(r"^## (.+?): .+$", head, flags=re.M)
        if names:
            attachments = "、".join(name.strip() for name in names)
        stripped = tail.strip()
    elif wrapper.startswith("# Files mentioned by the user:"):
        stripped = wrapper.split("\n\n", 1)[-1].strip()
    if not stripped:
        return None, attachments
    return stripped, attachments


def parse_segment(segment: Segment, seen_users: set[str], segment_index: int):
    turns: list[Turn] = []
    outputs: dict[str, str] = {}
    state = {"turn": None, "tokens": 0, "model": segment.model, "last_ts": segment.created}
    unknown_types: list[str] = []
    developer_messages = 0
    context_messages = 0

    def current_turn(ts):
        if state["turn"] is None:
            turn = Turn(id=None, ts=ts)
            turns.append(turn)
            state["turn"] = turn
        return state["turn"]

    try:
        handle = segment.path.open("r", encoding="utf-8", errors="replace")
    except OSError as exc:
        warn(f"无法打开 {segment.rel}: {exc}")
        return turns, outputs, state, unknown_types, developer_messages, context_messages

    with handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                warn(f"{segment.rel}:{line_no} 不是合法 JSON，已跳过")
                continue
            record_type = record.get("type")
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            ts = record.get("timestamp")
            if ts:
                state["last_ts"] = ts

            if record_type == "event_msg":
                kind = payload.get("type")
                if kind == "task_started":
                    turn = Turn(id=payload.get("turn_id"), ts=ts, status="running")
                    turns.append(turn)
                    state["turn"] = turn
                elif kind == "task_complete":
                    if state["turn"] is not None:
                        state["turn"].status = "completed"
                elif kind == "turn_aborted":
                    if state["turn"] is not None:
                        state["turn"].status = "aborted"
                elif kind == "token_count":
                    info = payload.get("info") or {}
                    total = (info.get("total_token_usage") or {}).get("total_tokens")
                    if isinstance(total, int):
                        state["tokens"] = max(state["tokens"], total)
                elif kind == "thread_settings_applied":
                    settings = payload.get("thread_settings") or {}
                    if isinstance(settings.get("model"), str) and settings["model"]:
                        state["model"] = settings["model"]
                continue

            if record_type == "token_usage_record":
                total = (payload.get("thread_token_usage") or {}).get("total_tokens")
                if isinstance(total, int):
                    state["tokens"] = max(state["tokens"], total)
                continue

            if record_type == "turn_context":
                if isinstance(payload.get("model"), str) and payload["model"]:
                    state["model"] = payload["model"]
                continue

            if record_type == "compacted":
                turn = current_turn(ts)
                turn.entries.append(Entry(kind="note", ts=ts, text="上下文已压缩（compacted）"))
                continue

            if record_type != "response_item":
                if record_type not in unknown_types:
                    unknown_types.append(str(record_type))
                continue

            payload_type = payload.get("type")
            turn = current_turn(ts)

            if payload_type == "message":
                role = payload.get("role")
                text = content_text(payload)
                if role == "user":
                    message, attachments = clean_user_text(text)
                    if message is None:
                        context_messages += 1
                        continue
                    if attachments:
                        message = f"**附件**：{attachments}\n\n{message}"
                    normalized = re.sub(r"\s+", " ", message).strip()
                    if (
                        segment_index > 0
                        and normalized in seen_users
                        and sum(1 for entry in turn.entries if entry.kind == "user") < 5
                    ):
                        continue
                    seen_users.add(normalized)
                    turn.entries.append(Entry(kind="user", ts=ts, text=message))
                elif role == "assistant":
                    if text.strip():
                        turn.entries.append(Entry(kind="assistant", ts=ts, text=text.strip()))
                elif role == "developer":
                    developer_messages += 1
                else:
                    if text.strip():
                        turn.entries.append(Entry(kind="note", ts=ts, text=text.strip()))
                continue

            if payload_type == "reasoning":
                text = reasoning_text(payload)
                if text.strip():
                    turn.entries.append(Entry(kind="reasoning", ts=ts, text=text.strip()))
                continue

            if payload_type in ("function_call", "custom_tool_call") or (
                isinstance(payload_type, str) and payload_type.endswith("_call")
            ):
                arguments = payload.get("arguments")
                if arguments is None:
                    arguments = payload.get("input")
                if arguments is None:
                    arguments = payload.get("action")
                turn.entries.append(
                    Entry(
                        kind="tool_call",
                        ts=ts,
                        name=str(payload.get("name") or payload_type or "tool"),
                        call_id=str(payload.get("call_id") or ""),
                        args=parse_arguments(arguments),
                    )
                )
                continue

            if payload_type in ("function_call_output", "custom_tool_call_output") or (
                isinstance(payload_type, str) and payload_type.endswith("_output")
            ):
                call_id = str(payload.get("call_id") or "")
                output = payload.get("output")
                if not isinstance(output, str):
                    output = json.dumps(output, ensure_ascii=False, indent=2) if output is not None else ""
                outputs[call_id] = output
                continue

            if payload_type not in unknown_types:
                unknown_types.append(str(payload_type))

    return turns, outputs, state, unknown_types, developer_messages, context_messages


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def render_tool_call(entry: Entry, output_limit: int) -> str:
    name = entry.name or "tool"
    args = entry.args
    body_parts: list[str] = []
    if isinstance(args, str) and args.strip():
        body_parts.append(fence(args, FENCE_LANGS.get(name, "text")))
    elif isinstance(args, dict) and args:
        if name in ("exec_command", "shell") and isinstance(args.get("cmd"), str):
            body_parts.append(fence(args["cmd"], "powershell"))
            if isinstance(args.get("workdir"), str) and args["workdir"]:
                body_parts.append(f"_工作目录：`{args['workdir']}`_")
        else:
            body_parts.append(fence(json.dumps(args, ensure_ascii=False, indent=2), "json"))
    elif args is not None:
        body_parts.append(fence(str(args), "text"))

    label = name
    if entry.call_id:
        label = f"{name}"
    if entry.output:
        shown, omitted = truncate(entry.output, output_limit)
        body_parts.append(fence(shown, "text"))
        suffix = f" · 输出 {len(entry.output):,} 字符"
        if omitted:
            suffix += f"（截断 {omitted:,}）"
    else:
        suffix = ""

    if entry.output is None:
        body_parts.append("_（无输出记录）_")
    body = "\n\n".join(part for part in body_parts if part)
    return details(f"工具 · {label}{suffix}", body)


def details(summary: str, body: str) -> str:
    if not body.strip():
        body = "_（空）_"
    return f"<details>\n<summary>{summary}</summary>\n\n{body}\n\n</details>"


def render_turn(turn: Turn, index: int, outputs: dict[str, str], opts) -> str:
    lines: list[str] = []
    status_label = {"completed": "已完成", "aborted": "已中断", "running": "进行中"}.get(
        turn.status, "记录"
    )
    lines.append(f"## Turn {index}")
    lines.append("")
    meta_line = f"_{local_time(parse_ts(turn.ts))} · {status_label}_"
    lines.append(meta_line)
    lines.append("")

    for entry in turn.entries:
        if entry.kind == "user":
            lines.append("### 用户")
            lines.append("")
            lines.append(entry.text)
            lines.append("")
        elif entry.kind == "assistant":
            lines.append("### 助手")
            lines.append("")
            lines.append(entry.text)
            lines.append("")
        elif entry.kind == "reasoning":
            quoted = "\n".join(f"> {line}" if line else ">" for line in entry.text.splitlines())
            lines.append(details(f"推理 · {len(entry.text):,} 字符", quoted))
            lines.append("")
        elif entry.kind == "tool_call":
            entry.output = outputs.get(entry.call_id) if entry.call_id else None
            lines.append(render_tool_call(entry, opts.tool_output_limit))
            lines.append("")
        elif entry.kind == "note":
            lines.append(f"> {entry.text}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def thread_slug(title: str, thread_id: str) -> str:
    slug = re.sub(r'[<>:"/\\|?*\[\]()\x00-\x1f]+', "-", title or "")
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-{2,}", "-", slug).strip("-.")
    if len(slug) > MAX_SLUG_CHARS:
        slug = slug[:MAX_SLUG_CHARS].rstrip("-.")
    return slug or thread_id[:8]


def render_thread(thread: dict, opts) -> str:
    stats = thread["stats"]
    header = [
        "---",
        f"codex_thread_id: {yaml_str(thread['id'])}",
        f"title: {yaml_str(thread['title'])}",
        f"created: {yaml_str(thread['created'] or '')}",
        f"updated: {yaml_str(thread['updated'] or '')}",
        f"cwd: {yaml_str(thread['cwd'] or '')}",
        f"model: {yaml_str(thread['model'] or '')}",
        f"provider: {yaml_str(thread['provider'] or '')}",
        f"archived: {'true' if thread['archived'] else 'false'}",
        f"rollouts: {len(thread['segments'])}",
        f"turns: {stats['turns']}",
        f"user_messages: {stats['user']}",
        f"assistant_messages: {stats['assistant']}",
        f"tool_calls: {stats['toolCalls']}",
        f"tokens: {stats['tokens']}",
        f"generated: {yaml_str(opts.generated_at)}",
        "---",
        "",
        f"# {thread['title']}",
        "",
    ]

    info_rows = [
        ("会话 ID", f"`{thread['id']}`"),
        ("工作目录", f"`{thread['cwd']}`" if thread["cwd"] else "—"),
        ("时间范围", f"{local_time(parse_ts(thread['created']))} → {local_time(parse_ts(thread['updated']))}"),
        ("模型", f"`{thread['model']}`" if thread["model"] else "—"),
        ("轮次 / 消息 / 工具", f"{stats['turns']} / {stats['user'] + stats['assistant']} / {stats['toolCalls']}"),
        ("Token", f"{stats['tokens']:,}" if stats["tokens"] else "—"),
        ("来源", "、".join(f"`{seg.rel}`" for seg in thread["segments"])),
    ]
    if thread["archived"]:
        info_rows.append(("状态", "已归档"))
    header.append("| 项目 | 内容 |")
    header.append("| --- | --- |")
    for key, value in info_rows:
        header.append(f"| {key} | {value} |")
    header.append("")

    if stats["turns"] > 1:
        header.append("## 目录")
        header.append("")
        header.append("| # | 时间 | 用户消息 | 工具 |")
        header.append("| --- | --- | --- | --- |")
        for index, (turn, rendered) in enumerate(thread["turns"], 1):
            counts = turn.counts()
            prompt = next((entry.text for entry in turn.entries if entry.kind == "user"), "")
            prompt = one_line(prompt, 50).replace("|", "\\|") or "—"
            header.append(
                f"| [{index}](#turn-{index}) | {local_time(parse_ts(turn.ts))} | {prompt} | {counts['toolCalls']} |"
            )
        header.append("")

    body = "\n".join(header)
    for index, (_turn, rendered) in enumerate(thread["turns"], 1):
        body += "\n" + rendered
    return body.rstrip() + "\n"


def render_index(threads: list[dict], totals: dict, opts, codex_home: Path) -> str:
    lines = [
        "# Codex 历史记录",
        "",
        f"> 由 **Codex History Bridge** 生成于 {opts.generated_at} · 源目录 `{codex_home}`",
        "",
        "| 总计 | 数量 |",
        "| --- | --- |",
        f"| 会话 | {totals['threads']} |",
        f"| 原始 rollout 文件 | {totals['rollouts']} |",
        f"| 轮次 | {totals['turns']:,} |",
        f"| 用户 / 助手消息 | {totals['user'] + totals['assistant']:,} |",
        f"| 工具调用 | {totals['toolCalls']:,} |",
        f"| 原始数据量 | {totals['bytes'] / 1048576:.1f} MB |",
        "",
        "## 会话列表",
        "",
        "| 日期 | 会话 | 轮次 | 工具 | 状态 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for thread in sorted(threads, key=lambda item: (item["created"] or "", item["id"]), reverse=True):
        stats = thread["stats"]
        date = local_time(parse_ts(thread["created"]))[:10] or "—"
        title = one_line(thread["title"], 60).replace("|", "\\|")
        status = "已归档" if thread["archived"] else "—"
        lines.append(
            f"| {date} | [{title}]({thread['file']}) | {stats['turns']} | {stats['toolCalls']} | {status} |"
        )
    lines.append("")
    lines.append("机器可读索引见 [index.json](index.json)；原始 JSONL 见 `raw/`。")
    return "\n".join(lines) + "\n"


def render_readme(totals: dict, opts, codex_home: Path, script_path: Path, output_dir: Path) -> str:
    tool_note = (
        "工具输出按上限截断，截断处有标记"
        if opts.tool_output_limit > 0
        else "工具输出完整保留"
    )
    raw_note = "已保留全部原始 JSONL（`raw/`）" if opts.include_raw else "未启用原始副本（`--raw` 可开启）"
    return f"""# Codex 历史记录（工作区副本）

本目录由 **Codex History Bridge** 生成，内容来自 `{codex_home}`。

## 内容

- `index.md` / `index.json`：会话总览与机器可读索引
- `threads/*.md`：每个会话一份 Markdown 逐字记录（含用户消息、助手回复、推理、工具调用与输出）
- `raw/`：Codex 原始 rollout JSONL 的字节级副本，便于回溯

## 当前统计

- 会话：{totals['threads']}
- rollout 文件：{totals['rollouts']}（{totals['bytes'] / 1048576:.1f} MB）
- 轮次：{totals['turns']:,}
- 消息：{totals['user'] + totals['assistant']:,}（用户 {totals['user']:,} / 助手 {totals['assistant']:,}）
- 工具调用：{totals['toolCalls']:,}

## 更新

在 DSH 中让 Agent 调用 `codex_history_import` 工具即可增量更新；也可以直接运行：

```text
python "{script_path}" --out "{output_dir}"
```

## 说明

- 开发者上下文（system/developer 注入）与环境注入消息不计入正文，其原始内容仍保存在 `raw/`。
- {tool_note}，{raw_note}。
- 重新导入是增量的：源文件未变化的会话会跳过，除非使用 `--force`。
"""


# --------------------------------------------------------------------------- #
# Output writing and state
# --------------------------------------------------------------------------- #


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temp, path)


def copy_raw(source: Path, destination: Path) -> bool:
    if destination.is_file():
        stat = destination.stat()
        if stat.st_size == source.stat().st_size and stat.st_mtime_ns == source.stat().st_mtime_ns:
            return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def load_state(output_dir: Path) -> dict:
    path = output_dir / STATE_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def settings_fingerprint(opts) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "raw": bool(opts.include_raw),
        "archived": bool(opts.include_archived),
        "toolOutputLimit": int(opts.tool_output_limit),
    }


def thread_file_name(thread_id: str, title: str, created: str | None) -> str:
    local = local_time(parse_ts(created))
    date = local[:10] if local else "undated"
    return f"threads/{date}_{thread_id[:8]}_{thread_slug(title, thread_id)}.md"


def prune_stale(output_dir: Path, state: dict, current_files: set[str]) -> list[str]:
    removed: list[str] = []
    threads_dir = (output_dir / "threads").resolve()
    for record in (state.get("threads") or {}).values():
        relative = record.get("file") if isinstance(record, dict) else None
        if not isinstance(relative, str) or relative in current_files:
            continue
        candidate = (output_dir / relative).resolve()
        if threads_dir not in candidate.parents:
            continue
        if candidate.is_file():
            try:
                candidate.unlink()
                removed.append(relative)
            except OSError as exc:
                warn(f"无法删除过期文件 {relative}: {exc}")
    return removed


# --------------------------------------------------------------------------- #
# Import pipeline
# --------------------------------------------------------------------------- #


def build_threads(segments: list[Segment], titles: dict[str, str], opts):
    grouped: dict[str, list[Segment]] = {}
    for segment in segments:
        grouped.setdefault(segment.thread_id, []).append(segment)

    threads: list[dict] = []
    for thread_id, group in grouped.items():
        group.sort(key=lambda seg: (seg.created or "", seg.path.name))
        seen_users: set[str] = set()
        turns: list[Turn] = []
        outputs: dict[str, str] = {}
        stats = {"turns": 0, "user": 0, "assistant": 0, "toolCalls": 0, "reasoning": 0, "tokens": 0}
        model = None
        last_seen: str | None = None
        developer_messages = 0
        context_messages = 0
        unknown_types: list[str] = []

        for segment_index, segment in enumerate(group):
            seg_turns, seg_outputs, seg_state, seg_unknown, seg_dev, seg_ctx = parse_segment(
                segment, seen_users, segment_index
            )
            turns.extend(seg_turns)
            outputs.update(seg_outputs)
            model = seg_state.get("model") or model
            stats["tokens"] = max(stats["tokens"], int(seg_state.get("tokens") or 0))
            last_seen = max(last_seen or "", str(seg_state.get("last_ts") or "")) or None
            developer_messages += seg_dev
            context_messages += seg_ctx
            for name in seg_unknown:
                if name not in unknown_types:
                    unknown_types.append(name)

        rendered_turns: list[tuple[Turn, str]] = []
        first_prompt = ""
        for turn in turns:
            counts = turn.counts()
            if not turn.entries:
                continue
            if not first_prompt:
                first_prompt = next((entry.text for entry in turn.entries if entry.kind == "user"), "")
            stats["turns"] += 1
            stats["user"] += counts["user"]
            stats["assistant"] += counts["assistant"]
            stats["toolCalls"] += counts["toolCalls"]
            stats["reasoning"] += sum(1 for entry in turn.entries if entry.kind == "reasoning")
            rendered_turns.append((turn, render_turn(turn, len(rendered_turns) + 1, outputs, opts)))

        title = titles.get(thread_id) or one_line(first_prompt, MAX_TITLE_CHARS) or f"Codex 会话 {thread_id[:8]}"
        created = min((seg.created for seg in group if seg.created), default=None)
        updated = max((seg.created for seg in group if seg.created), default=None)
        thread = {
            "id": thread_id,
            "title": title,
            "created": iso(parse_ts(created)),
            "updated": iso(parse_ts(updated)),
            "cwd": next((seg.cwd for seg in group if seg.cwd), None),
            "provider": next((seg.provider for seg in group if seg.provider), None),
            "model": model,
            "archived": all(seg.archived for seg in group),
            "segments": group,
            "turns": rendered_turns,
            "stats": stats,
            "developer_messages": developer_messages,
            "context_messages": context_messages,
            "unknown_types": unknown_types,
            "bytes": sum(seg.size for seg in group),
        }
        thread["created"] = thread["created"] or iso(parse_ts(group[0].created))
        thread["updated"] = iso(parse_ts(last_seen)) or thread["updated"]
        if not thread["updated"]:
            latest = max(group, key=lambda seg: seg.mtime_ns)
            thread["updated"] = iso(datetime.fromtimestamp(latest.mtime_ns / 1e9, tz=timezone.utc))
        thread["file"] = thread_file_name(thread_id, title, thread["created"])
        threads.append(thread)

    threads.sort(key=lambda item: (item["created"] or "", item["id"]), reverse=True)
    return threads


def source_record(segment: Segment) -> dict:
    return {"size": segment.size, "mtimeNs": segment.mtime_ns, "thread": segment.thread_id}


def run_import(args) -> dict:
    codex_home = Path(os.path.expanduser(args.codex_home)).resolve()
    output_dir = Path(os.path.expanduser(args.out)).resolve()
    if not codex_home.is_dir():
        return {"ok": False, "error": f"找不到 Codex 数据目录：{codex_home}"}

    segments = discover(codex_home, args.include_archived)
    if not segments:
        return {
            "ok": False,
            "error": f"{codex_home} 下没有找到 rollout JSONL（--include-archived 是否关闭了已归档会话？）",
        }
    titles = load_titles(codex_home)

    opts = argparse.Namespace(
        generated_at=now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        tool_output_limit=args.tool_output_limit,
        include_raw=args.raw,
        include_archived=args.include_archived,
        full_tool_output=args.full_tool_output,
    )
    threads = build_threads(segments, titles, opts)

    if args.thread:
        wanted = [thread_id.strip().lower() for thread_id in args.thread if thread_id.strip()]
        threads = [
            thread
            for thread in threads
            if any(thread["id"].lower().startswith(value) for value in wanted)
        ]
        if not threads:
            return {"ok": False, "error": f"未找到匹配的会话：{', '.join(args.thread)}"}
        warn("单会话导入：只更新该会话的记录，index.md 与 index.json 保持上次全量导入的结果")

    totals = {
        "threads": len(threads),
        "rollouts": sum(len(thread["segments"]) for thread in threads),
        "bytes": sum(thread["bytes"] for thread in threads),
        "turns": sum(thread["stats"]["turns"] for thread in threads),
        "user": sum(thread["stats"]["user"] for thread in threads),
        "assistant": sum(thread["stats"]["assistant"] for thread in threads),
        "toolCalls": sum(thread["stats"]["toolCalls"] for thread in threads),
        "tokens": sum(thread["stats"]["tokens"] for thread in threads),
    }

    state = load_state(output_dir)
    fingerprint = settings_fingerprint(opts)
    force = args.force or state.get("settings") != fingerprint
    previous_sources = state.get("sources") or {}
    previous_threads = state.get("threads") or {}

    written: list[str] = []
    imported: list[dict] = []
    skipped: list[dict] = []
    thread_records: dict[str, dict] = {}
    current_files: set[str] = set()

    for thread in threads:
        changed = force or not (output_dir / thread["file"]).is_file()
        if not changed:
            for segment in thread["segments"]:
                record = previous_sources.get(segment.rel)
                if (
                    not isinstance(record, dict)
                    or record.get("size") != segment.size
                    or record.get("mtimeNs") != segment.mtime_ns
                ):
                    changed = True
                    break
        record = {
            "file": thread["file"],
            "title": thread["title"],
            "created": thread["created"],
            "updated": thread["updated"],
            "archived": thread["archived"],
            "bytes": thread["bytes"],
            "rollouts": len(thread["segments"]),
            "stats": thread["stats"],
        }
        thread_records[thread["id"]] = record
        current_files.add(thread["file"])
        if changed:
            if not args.dry_run:
                write_text(output_dir / thread["file"], render_thread(thread, opts))
            written.append(thread["file"])
            imported.append(
                {
                    "id": thread["id"],
                    "title": thread["title"],
                    "file": thread["file"],
                    "created": thread["created"],
                    "updated": thread["updated"],
                    "archived": thread["archived"],
                    "rollouts": len(thread["segments"]),
                    **thread["stats"],
                }
            )
        else:
            skipped.append({"id": thread["id"], "title": thread["title"], "file": thread["file"]})

    if not args.thread:
        removed = [] if args.dry_run else prune_stale(output_dir, state, current_files)
    else:
        removed = []
        for thread_id, record in previous_threads.items():
            if thread_id not in thread_records and isinstance(record, dict):
                thread_records[thread_id] = record

    raw_written: list[str] = []
    if args.raw and not args.dry_run:
        for segment in segments:
            if args.thread and segment.thread_id.lower() not in {thread["id"].lower() for thread in threads}:
                continue
            target = output_dir / "raw" / segment.rel
            if copy_raw(segment.path, target):
                raw_written.append(str(Path("raw") / segment.rel).replace("\\", "/"))
        for extra_name in ("session_index.jsonl", "history.jsonl"):
            extra = codex_home / extra_name
            if extra.is_file():
                target = output_dir / "raw" / extra_name
                if copy_raw(extra, target):
                    raw_written.append(f"raw/{extra_name}")

    full_import = not args.thread
    index_files: list[str] = []
    if not args.dry_run:
        if full_import:
            index_payload = {
                "generatedAt": opts.generated_at,
                "codexHome": str(codex_home),
                "outputDir": str(output_dir),
                "settings": fingerprint,
                "totals": totals,
                "threads": [
                    {
                        "id": thread["id"],
                        "title": thread["title"],
                        "file": thread["file"],
                        "created": thread["created"],
                        "updated": thread["updated"],
                        "archived": thread["archived"],
                        "rollouts": len(thread["segments"]),
                        "bytes": thread["bytes"],
                        **thread["stats"],
                    }
                    for thread in threads
                ],
            }
            index_threads = [
                {
                    "id": record.get("id") or thread_id,
                    "title": record.get("title", ""),
                    "file": record.get("file", ""),
                    "created": record.get("created"),
                    "updated": record.get("updated"),
                    "archived": bool(record.get("archived")),
                    "stats": record.get("stats", {}),
                }
                for thread_id, record in thread_records.items()
                if isinstance(record, dict) and record.get("file")
            ]
            write_text(output_dir / "index.json", json.dumps(index_payload, ensure_ascii=False, indent=2) + "\n")
            write_text(output_dir / "index.md", render_index(index_threads, totals, opts, codex_home))
            write_text(
                output_dir / "README.md",
                render_readme(totals, opts, codex_home, Path(__file__).resolve(), output_dir),
            )
            index_files = ["index.md", "index.json", "README.md"]

        new_state = {
            "schema": SCHEMA_VERSION,
            "codexHome": str(codex_home),
            "outputDir": str(output_dir),
            "importedAt": opts.generated_at,
            "settings": fingerprint,
            "sources": {segment.rel: source_record(segment) for segment in segments},
            "threads": thread_records,
        }
        write_text(output_dir / STATE_FILE, json.dumps(new_state, ensure_ascii=False, indent=2) + "\n")

    result = {
        "ok": True,
        "mode": "import" if not args.dry_run else "dry-run",
        "partial": bool(args.thread),
        "codexHome": str(codex_home),
        "outputDir": str(output_dir),
        "generatedAt": opts.generated_at,
        "totals": totals,
        "imported": imported,
        "skipped": skipped,
        "written": written + raw_written + index_files,
        "removed": removed,
        "warnings": WARNINGS,
    }
    return result


def run_status(args) -> dict:
    codex_home = Path(os.path.expanduser(args.codex_home)).resolve()
    output_dir = Path(os.path.expanduser(args.out)).resolve()
    if not codex_home.is_dir():
        return {"ok": False, "error": f"找不到 Codex 数据目录：{codex_home}"}

    segments = discover(codex_home, args.include_archived)
    state = load_state(output_dir)
    previous_sources = state.get("sources") or {}
    threads_seen = {segment.thread_id for segment in segments}
    pending = set()
    for segment in segments:
        record = previous_sources.get(segment.rel)
        if (
            not isinstance(record, dict)
            or record.get("size") != segment.size
            or record.get("mtimeNs") != segment.mtime_ns
        ):
            pending.add(segment.thread_id)
    for rel, record in previous_sources.items():
        if isinstance(record, dict) and record.get("thread") not in threads_seen:
            pending.add(str(record.get("thread")))

    created = sorted(seg.created for seg in segments if seg.created)
    imported = None
    if state.get("importedAt"):
        imported = {
            "importedAt": state.get("importedAt"),
            "codexHome": state.get("codexHome"),
            "outputDir": state.get("outputDir"),
            "threads": len(state.get("threads") or {}),
            "sources": len(previous_sources),
        }
    return {
        "ok": True,
        "mode": "status",
        "codexHome": str(codex_home),
        "outputDir": str(output_dir),
        "source": {
            "files": len(segments),
            "threads": len(threads_seen),
            "bytes": sum(segment.size for segment in segments),
            "oldest": iso(parse_ts(created[0])) if created else None,
            "newest": iso(parse_ts(created[-1])) if created else None,
            "archivedFiles": sum(1 for segment in segments if segment.archived),
        },
        "imported": imported,
        "pendingThreads": len(pending),
        "warnings": WARNINGS,
    }


def emit(payload: dict, as_json: bool) -> None:
    if as_json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return
    if not payload.get("ok"):
        sys.stderr.write(f"错误：{payload.get('error')}\n")
        return
    if payload["mode"] == "status":
        source = payload["source"]
        sys.stdout.write(
            f"Codex 数据：{source['threads']} 个会话 / {source['files']} 个 rollout / "
            f"{source['bytes'] / 1048576:.1f} MB\n"
        )
        if payload.get("imported"):
            sys.stdout.write(f"上次导入：{payload['imported']['importedAt']}，{payload['imported']['threads']} 个会话\n")
        else:
            sys.stdout.write("尚未导入到该目录\n")
        sys.stdout.write(f"待更新会话：{payload['pendingThreads']}\n")
        return
    totals = payload["totals"]
    sys.stdout.write(
        f"{'预演' if payload['mode'] == 'dry-run' else '导入完成'}：{totals['threads']} 个会话 / "
        f"{totals['rollouts']} 个 rollout / {totals['bytes'] / 1048576:.1f} MB\n"
    )
    sys.stdout.write(f"输出目录：{payload['outputDir']}\n")
    sys.stdout.write(
        f"轮次 {totals['turns']}，消息 {totals['user'] + totals['assistant']}，工具调用 {totals['toolCalls']}\n"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="把本机 Codex 会话历史导入工作区（Markdown 逐字记录 + 索引 + 可选原始 JSONL）。"
    )
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME") or "~/.codex")
    parser.add_argument("--out", default="codex-history", help="输出目录（默认 ./codex-history）")
    parser.add_argument("--thread", action="append", default=None, help="只导入指定会话，可重复")
    parser.add_argument("--no-archived", dest="include_archived", action="store_false", help="忽略 archived_sessions")
    parser.add_argument("--no-raw", dest="raw", action="store_false", help="不复制原始 JSONL")
    parser.add_argument("--full-tool-output", action="store_true", help="工具输出不截断")
    parser.add_argument(
        "--tool-output-limit",
        type=int,
        default=DEFAULT_TOOL_OUTPUT_LIMIT,
        help=f"工具输出字符上限（默认 {DEFAULT_TOOL_OUTPUT_LIMIT}，0 表示不截断）",
    )
    parser.add_argument("--force", action="store_true", help="忽略增量状态，全部重新生成")
    parser.add_argument("--dry-run", action="store_true", help="只报告将要写入的内容")
    parser.add_argument("--status", action="store_true", help="只报告源数据与上次导入状态")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    return parser


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    parser = build_parser()
    args = parser.parse_args(argv)
    args.include_archived = getattr(args, "include_archived", True)
    args.raw = getattr(args, "raw", True)
    if args.full_tool_output:
        args.tool_output_limit = 0
    if args.tool_output_limit < 0:
        parser.error("--tool-output-limit 不能为负数")

    payload = run_status(args) if args.status else run_import(args)
    emit(payload, args.json)
    if not payload.get("ok"):
        return 1
    if payload.get("warnings"):
        for message in payload["warnings"]:
            sys.stderr.write(f"警告：{message}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
