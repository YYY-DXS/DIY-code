#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Query engine for the dsh query-bridge plugin.

Subcommands (all print one JSON object on stdout):

    github  --repo OWNER/NAME [--commits N] [--runs N]
    deepseek [--key-file PATH]
    search  --query TEXT [--limit N] [--history DIR] [--archive DIR]

The plugin (index.js) renders the JSON into a short Chinese summary, so this
script stays quiet on success and only writes diagnostics to stderr.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

GH_API = "https://api.github.com"
DS_BASE = "https://api.deepseek.com"
KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{10,}")
TRANSCRIPT_SKIP = ("index.md", "README.md")


# ---------------------------------------------------------------- helpers
def iso_local(value: str) -> str:
    if not value:
        return ""
    try:
        return (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            .astimezone()
            .strftime("%Y-%m-%d %H:%M")
        )
    except ValueError:
        return value


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{int(num)} B" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def http_json(url: str, headers: dict[str, str] | None = None) -> tuple[int, object]:
    req = urllib.request.Request(url, headers={"User-Agent": "dsh-query-bridge", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body)
        except Exception:
            return exc.code, {"message": body[:300]}
    except Exception as exc:
        return 0, {"message": str(exc)}


def normalize_repo(repo: str) -> str:
    repo = (repo or "").strip().strip("/")
    for prefix in ("https://github.com/", "http://github.com/", "github.com/", "git@github.com:"):
        if repo.startswith(prefix):
            repo = repo[len(prefix):]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return repo


# ---------------------------------------------------------------- github
def cmd_github(args) -> dict:
    repo = normalize_repo(args.repo)
    if repo.count("/") != 1:
        return {"ok": False, "error": f"仓库名应为 OWNER/NAME，收到：{repo}"}

    code, meta = http_json(f"{GH_API}/repos/{repo}", {"Accept": "application/vnd.github+json"})
    if code != 200 or not isinstance(meta, dict):
        message = meta.get("message") if isinstance(meta, dict) else str(meta)
        return {"ok": False, "error": f"GitHub 返回 HTTP {code}：{message}", "repo": repo}

    def get_list(path: str) -> list:
        _, data = http_json(f"{GH_API}/repos/{repo}{path}", {"Accept": "application/vnd.github+json"})
        return data if isinstance(data, list) else []

    commits = get_list(f"/commits?per_page={max(1, min(int(args.commits), 30))}")
    releases = get_list("/releases?per_page=3")

    _, runs_raw = http_json(
        f"{GH_API}/repos/{repo}/actions/runs?per_page={max(1, min(int(args.runs), 10))}",
        {"Accept": "application/vnd.github+json"},
    )
    runs = runs_raw.get("workflow_runs", []) if isinstance(runs_raw, dict) else []

    return {
        "ok": True,
        "repo": meta.get("full_name"),
        "url": meta.get("html_url"),
        "private": bool(meta.get("private")),
        "license": (meta.get("license") or {}).get("spdx_id") or "",
        "branch": meta.get("default_branch"),
        "created": iso_local(meta.get("created_at")),
        "pushed": iso_local(meta.get("pushed_at")),
        "language": meta.get("language") or "",
        "stars": meta.get("stargazers_count", 0),
        "forks": meta.get("forks_count", 0),
        "openIssues": meta.get("open_issues_count", 0),
        "size": human_size(float(meta.get("size", 0)) * 1024),
        "archived": bool(meta.get("archived")),
        "commits": [
            {
                "sha": item.get("sha", "")[:8],
                "date": iso_local((item.get("commit") or {}).get("committer", {}).get("date")),
                "message": ((item.get("commit") or {}).get("message") or "").splitlines()[0][:100],
            }
            for item in commits
        ],
        "runs": [
            {
                "name": item.get("name") or item.get("display_title") or "workflow",
                "state": item.get("conclusion") or item.get("status") or "",
                "date": iso_local(item.get("created_at")),
            }
            for item in runs
        ],
        "releases": [
            {
                "tag": item.get("tag_name"),
                "name": item.get("name") or "",
                "date": iso_local(item.get("published_at")),
            }
            for item in releases
        ],
    }


# ---------------------------------------------------------------- deepseek
def find_key(explicit_file: str, workspace: str) -> tuple[str, str]:
    env = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env:
        return env, "环境变量 DEEPSEEK_API_KEY"

    candidates: list[Path] = []
    if explicit_file:
        candidates.append(Path(explicit_file).expanduser())
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")
    candidates.extend(
        [
            home / "Desktop" / "api.txt",
            home / "Desktop" / "api-key.txt",
            Path(workspace) / "codex" / "api.txt",
            Path(workspace) / "api.txt",
        ]
    )
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = KEY_RE.search(text)
        if match:
            return match.group(0), str(path)
    return "", ""


def cmd_deepseek(args) -> dict:
    key, source = find_key(args.key_file, args.workspace)
    if not key:
        return {
            "ok": False,
            "error": "没有找到 DeepSeek API key。",
            "hint": "把 key 放到 桌面\\api.txt，或设置环境变量 DEEPSEEK_API_KEY。",
        }

    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    code, balance = http_json(f"{DS_BASE}/user/balance", headers)
    if code != 200:
        message = balance.get("message") if isinstance(balance, dict) else str(balance)
        return {
            "ok": False,
            "error": f"余额查询失败（HTTP {code}）：{message}",
            "hint": "401 表示 key 无效或已被撤销。" if code == 401 else "",
            "keySource": source,
            "keyMasked": f"{key[:6]}…{key[-4:]}",
        }

    mcode, models = http_json(f"{DS_BASE}/models", headers)
    model_ids = [m.get("id") for m in (models or {}).get("data", [])] if mcode == 200 else []

    return {
        "ok": True,
        "keySource": source,
        "keyMasked": f"{key[:6]}…{key[-4:]}",
        "available": balance.get("is_available"),
        "balances": [
            {
                "currency": item.get("currency"),
                "total": item.get("total_balance"),
                "granted": item.get("granted_balance"),
                "toppedUp": item.get("topped_up_balance"),
            }
            for item in balance.get("balance_infos", [])
        ],
        "models": model_ids,
        "modelsError": "" if mcode == 200 else f"模型列表不可用（HTTP {mcode}）",
    }


# ---------------------------------------------------------------- history search
def transcript_title(path: Path) -> str:
    """First headline of a generated transcript, falling back to its filename."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for _ in range(60):
                line = fh.readline()
                if not line:
                    break
                line = line.strip()
                if line.startswith("# "):
                    return line[2:].strip()
    except OSError:
        pass
    return path.stem


def cmd_search(args) -> dict:
    query = (args.query or "").strip()
    if not query:
        return {"ok": False, "error": "搜索词不能为空"}
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    limit = max(1, min(int(args.limit), 50))

    transcripts: list[dict] = []
    history_dir = Path(args.history)
    if history_dir.is_dir():
        for path in sorted(history_dir.glob("*.md")):
            if path.name in TRANSCRIPT_SKIP:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not pattern.search(text):
                continue
            snippets: list[str] = []
            count = 0
            for line in text.splitlines():
                if not pattern.search(line):
                    continue
                count += 1
                stripped = line.strip()
                if stripped and len(snippets) < 2 and stripped not in snippets:
                    snippets.append(stripped[:160])
            transcripts.append(
                {
                    "file": path.name,
                    "title": transcript_title(path),
                    "matches": count,
                    "snippets": snippets,
                }
            )

    transcripts.sort(key=lambda item: item["matches"], reverse=True)

    archive: list[dict] = []
    archive_dir = Path(args.archive)
    index_file = archive_dir / "index.json"
    if index_file.is_file():
        try:
            payload = json.loads(index_file.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        for conv in payload.get("conversations", []):
            haystack = " ".join(
                [conv.get("date", ""), conv.get("name", ""), conv.get("topic", "")]
                + (conv.get("outputs") or [])
                + (conv.get("work") or [])
                + (conv.get("root") or [])
            )
            if pattern.search(haystack):
                archive.append(
                    {
                        "date": conv.get("date"),
                        "name": conv.get("name"),
                        "path": conv.get("path"),
                        "files": conv.get("files"),
                        "size": conv.get("size"),
                        "topic": conv.get("topic") or "",
                    }
                )

    return {
        "ok": True,
        "query": query,
        "limit": limit,
        "transcripts": transcripts[:limit],
        "transcriptTotal": len(transcripts),
        "archive": archive[: max(1, min(limit, 20))],
        "archiveTotal": len(archive),
        "historyDir": str(history_dir),
        "archiveDir": str(archive_dir),
    }


# ---------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=os.getcwd(), help="工作区根目录")
    sub = parser.add_subparsers(dest="command", required=True)

    gh = sub.add_parser("github")
    gh.add_argument("--repo", required=True)
    gh.add_argument("--commits", type=int, default=6)
    gh.add_argument("--runs", type=int, default=3)

    ds = sub.add_parser("deepseek")
    ds.add_argument("--key-file", default="")

    se = sub.add_parser("search")
    se.add_argument("--query", required=True)
    se.add_argument("--limit", type=int, default=8)
    se.add_argument("--history", default="")
    se.add_argument("--archive", default="")

    args = parser.parse_args(argv)
    workspace = Path(args.workspace)
    if args.command == "search":
        args.history = args.history or str(workspace / "codex-history" / "threads")
        args.archive = args.archive or str(workspace / "codex")

    try:
        if args.command == "github":
            result = cmd_github(args)
        elif args.command == "deepseek":
            result = cmd_deepseek(args)
        else:
            result = cmd_search(args)
    except Exception as exc:  # 兜底，保证插件拿到可读错误
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
