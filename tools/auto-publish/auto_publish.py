#!/usr/bin/env python3
"""自动推送：从本地知识库里发现新的 DIY 项目讨论，生成项目文档并推送到仓库。

判断逻辑是分层的：
  1. 打分挑选：置顶加权、关键词命中、方案类特征（材料清单/步骤/预算…）、篇幅
  2. 达到阈值的才生成文档并推送；没达到的记进「候选清单」，留待人工确认

常用参数：
    --dry-run     只看会做什么，不写文件、不推送
    --min-score N 调整门槛（默认 3）
    --list        只列出打分结果
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- 配置

HOME = Path.home()
DEFAULT_KB = HOME / "Documents" / "ChatGPT" / "New project" / "knowledge" / "deepseek"
DEFAULT_REPO = HOME / "Desktop" / "codex" / "2026-09-27" / "github" / "DIY-"
DEFAULT_KEYS = HOME / "Desktop" / "codex" / "2026-09-27" / "github" / ".keys"
GIT_BIN = (
    HOME
    / ".cache"
    / "codex-runtimes"
    / "codex-primary-runtime"
    / "dependencies"
    / "native"
    / "git"
    / "mingw64"
    / "bin"
)

DIY_KEYWORDS = [
    "模型", "模组", "手工", "外骨骼", "飞艇", "航模", "无人机",
    "改装", "改造", "装配", "喷漆", "3D打印", "3D建模", "电路", "硬件",
    "Arduino", "arduino", "ESP32", "esp32", "单片机", "舵机", "电磁铁",
    "台历", "木工", "焊接", "建模", "装置", "机械", "传动", "轴承",
    "支架", "骨架", "Minecraft", "minecraft",
]
PLAN_MARKERS = [
    "材料清单", "工具清单", "步骤", "方案", "规格", "预算", "流程",
    "参数", "尺寸", "工艺流程", "时间规划", "物料",
]

# 已经人工整理过的，不再重复推送
SEED_PUBLISHED = {
    "00000000-0000-0000-0000-000000000000": "齐柏林飞艇模型",
    "00000000-0000-0000-0000-000000000000": "外骨骼",
    "00000000-0000-0000-0000-000000000000": "外骨骼",
    "00000000-0000-0000-0000-000000000000": "马年台历",
    "00000000-0000-0000-0000-000000000000": "航空模型",
}


# ---------------------------------------------------------------- 工具


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def safe_name(text: str, limit: int = 40) -> str:
    text = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", text or "")
    text = re.sub(r"\s+", " ", text).strip().strip(".")
    return text[:limit] or "未命名项目"


def git_env(keys_dir: Path) -> dict:
    env = dict(**__import__("os").environ)
    if GIT_BIN.exists():
        env["GIT_EXEC_PATH"] = str(GIT_BIN)
        env["PATH"] = f"{GIT_BIN};{env.get('PATH', '')}"
    key = keys_dir / "id_ed25519"
    if key.exists():
        env["GIT_SSH_COMMAND"] = (
            f'ssh -i "{key}" -o UserKnownHostsFile="{keys_dir / "known_hosts"}" '
            "-o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
        )
    return env


def run_git(repo: Path, env: dict, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], cwd=repo, env=env, capture_output=True, text=True, encoding="utf-8"
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def repo_slug(repo: Path, env: dict) -> str | None:
    code, out = run_git(repo, env, "remote", "get-url", "origin")
    if code != 0:
        return None
    url = out.strip()
    match = re.search(r"github\.com[:/]([\w.\-]+/[\w.\-]+?)(?:\.git)?$", url)
    return match.group(1) if match else None


def is_public_repo(slug: str) -> bool | None:
    """GitHub API 能匿名读到 → 公开仓库。读不到或出错返回 None（当作未知）。"""
    url = f"https://api.github.com/repos/{slug}"
    request = urllib.request.Request(url, headers={"User-Agent": "auto-publish"})
    try:
        with urllib.request.urlopen(request, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("private")) is False
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False  # 私有或不存在，匿名看不到
        return None
    except Exception:
        return None


# ---------------------------------------------------------------- 打分


def score_conversation(rec: dict, pinned: bool) -> tuple[int, list[str]]:
    """打分。硬性要求：必须命中至少一个 DIY 关键词，否则直接淘汰。

    这样能把「VPN 教程」「街车价格」这类只有步骤/预算特征、但和动手做东西
    无关的对话挡在外面。
    """
    title = rec.get("title", "")
    ask = rec.get("first_request", "")
    title_hits = [k for k in DIY_KEYWORDS if k in title]
    ask_hits = [k for k in DIY_KEYWORDS if k in ask]
    if not title_hits and not ask_hits:
        return 0, ["与动手制作无关"]

    score = 0
    why: list[str] = []
    if pinned:
        score += 2
        why.append("置顶")
    if title_hits:
        score += 3 + min(len(title_hits) - 1, 1)
        why.append("标题:" + "/".join(title_hits[:3]))
    if ask_hits:
        score += min(len(ask_hits), 2)
        why.append("需求:" + "/".join(ask_hits[:3]))
    if any(m in rec.get("first_response", "") for m in PLAN_MARKERS):
        score += 1
        why.append("含方案要素")
    if rec.get("messages", 0) >= 10:
        score += 1
        why.append(f"篇幅{rec['messages']}条")
    return score, why


def collect_conversations(kb: Path) -> dict:
    """从 messages.jsonl 汇总每个会话的关键信息。"""
    out: dict[str, dict] = {}
    jsonl = kb / "data" / "messages.jsonl"
    for line in jsonl.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("on_path") is False:
            continue
        cid = rec.get("conv_id")
        if not cid:
            continue
        slot = out.setdefault(
            cid,
            {
                "id": cid,
                "title": rec.get("title") or "未命名",
                "created": (rec.get("conv_created") or "")[:10],
                "messages": 0,
                "first_request": "",
                "first_response": "",
            },
        )
        slot["messages"] += 1
        if not slot["first_request"] and rec.get("request"):
            slot["first_request"] = rec["request"]
        if not slot["first_response"] and rec.get("response"):
            slot["first_response"] = rec["response"]
    return out


def pinned_ids(kb: Path) -> set[str]:
    snap = load_json(kb / "data" / "sessions.json", {})
    return {s["id"] for s in snap.get("sessions", []) if s.get("pinned")}


# ---------------------------------------------------------------- 生成文档


def build_doc(rec: dict, why: list[str]) -> str:
    def trim(text: str, limit: int) -> str:
        text = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
        return text[:limit] + "\n\n……（节选，完整讨论在本地记录里）" if len(text) > limit else text

    return "\n".join(
        [
            f"# {rec['title']}",
            "",
            f"> ⚙️ 本文由自动推送于 {datetime.now().strftime('%Y-%m-%d')} 生成，"
            "内容取自讨论开头，尚未人工整理。",
            f"> 入选理由：{'、'.join(why)}",
            "",
            f"- 讨论日期：{rec['created']}",
            f"- 消息数：{rec['messages']}",
            "",
            "## 原始需求",
            "",
            trim(rec["first_request"], 600) or "（无）",
            "",
            "## 初步方案",
            "",
            trim(rec["first_response"], 1800) or "（无）",
            "",
            "## 待办",
            "",
            "- [ ] 整理成正式项目文档（补材料清单、规格、时间安排）",
            "- [ ] 补充后续讨论里新增的结论",
            "",
        ]
    )


def update_index(repo: Path, entries: list[dict]) -> None:
    index = repo / "projects" / "README.md"
    lines = [
        "# 项目目录",
        "",
        "| 项目 | 来源 | 状态 |",
        "| --- | --- | --- |",
    ]
    for item in entries:
        lines.append(f"| [{item['title']}]({item['dir']}/README.md) | {item['source']} | {item['status']} |")
    lines.append("")
    lines.append("> 标有「自动收录」的条目由自动推送生成，等待人工整理。")
    lines.append("")
    index.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- 主流程


def main() -> int:
    ap = argparse.ArgumentParser(description="自动推送新的 DIY 项目")
    ap.add_argument("--kb", default=str(DEFAULT_KB))
    ap.add_argument("--repo", default=str(DEFAULT_REPO))
    ap.add_argument("--keys", default=str(DEFAULT_KEYS))
    ap.add_argument("--min-score", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--exclude", help="把某个会话 ID 加入永不推送名单")
    ap.add_argument(
        "--allow-public",
        action="store_true",
        help="允许推送到公开仓库（默认只推私有仓库，避免把个人讨论发到公网）",
    )
    args = ap.parse_args()

    kb = Path(args.kb)
    repo = Path(args.repo)
    keys = Path(args.keys)
    state_path = Path(__file__).resolve().parent / "state.json"
    state = load_json(state_path, {"published": {}, "candidates": {}})
    published = dict(SEED_PUBLISHED)
    published.update(state.get("published", {}))
    blocked = set(state.get("blocked", []))

    if args.exclude:
        blocked.add(args.exclude)
        state["blocked"] = sorted(blocked)
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"已加入排除名单：{args.exclude}")
        return 0

    if not (kb / "data" / "messages.jsonl").exists():
        print(f"找不到知识库：{kb}")
        return 1
    if not (repo / ".git").exists():
        print(f"找不到仓库：{repo}")
        return 1

    convs = collect_conversations(kb)
    pinned = pinned_ids(kb)
    fresh = {
        cid: rec for cid, rec in convs.items() if cid not in published and cid not in blocked
    }
    print(f"知识库共 {len(convs)} 个会话，未推送过 {len(fresh)} 个")

    scored = []
    for cid, rec in fresh.items():
        value, why = score_conversation(rec, cid in pinned)
        scored.append((value, why, rec))
    scored.sort(key=lambda x: -x[0])

    if args.list or args.dry_run:
        for value, why, rec in scored[:15]:
            mark = "✓ 推送" if value >= args.min_score else "  跳过"
            print(f"  {mark} [{value:>2}分] {rec['created']} {rec['title'][:24]}  {'、'.join(why)}")
        if args.list:
            return 0

    picked = [(v, w, r) for v, w, r in scored if v >= args.min_score]
    skipped = [(v, w, r) for v, w, r in scored if v < args.min_score]
    print(f"达到门槛（{args.min_score} 分）的有 {len(picked)} 个")

    if args.dry_run:
        print("dry-run：不写文件、不推送")
        return 0

    # 安全检查：不往公开仓库自动发个人讨论
    env = git_env(keys)
    slug = repo_slug(repo, env)
    if slug and not args.allow_public:
        public = is_public_repo(slug)
        if public:
            print(
                f"\n⚠ 仓库 {slug} 目前是公开的，已跳过推送。\n"
                "  自动生成的内容来自你的私人对话，放到公网上不太合适。\n"
                "  两个选择：\n"
                "    1. 把仓库改成私有（推荐）：仓库页 → Settings → Danger Zone → Change visibility\n"
                "    2. 确认无所谓，就加参数重跑：--allow-public"
            )
            return 0
    if not picked:
        state["candidates"] = {
            r["id"]: {"title": r["title"], "date": r["created"], "score": v}
            for v, _, r in skipped
        }
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print("没有新项目需要推送。")
        return 0

    # 生成文档
    projects_dir = repo / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    added: list[dict] = []
    for value, why, rec in picked:
        name = safe_name(rec["title"])
        folder = projects_dir / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "README.md").write_text(build_doc(rec, why), encoding="utf-8")
        added.append(
            {
                "title": rec["title"],
                "dir": name,
                "source": f"自动收录（{rec['created']}）",
                "status": "待整理",
                "id": rec["id"],
            }
        )
        print(f"  已生成：projects/{name}/README.md（{value} 分）")

    # 更新索引：保留已有条目
    entries = []
    seen_dirs = set()
    for cid, title in published.items():
        folder = safe_name(title)
        if (projects_dir / folder).exists() and folder not in seen_dirs:
            entries.append({"title": title, "dir": folder, "source": "人工整理", "status": "进行中"})
            seen_dirs.add(folder)
    for item in added:
        if item["dir"] not in seen_dirs:
            entries.append(item)
            seen_dirs.add(item["dir"])
    update_index(repo, entries)

    # 提交并推送
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    run_git(repo, env, "pull", "--ff-only")
    run_git(repo, env, "add", "-A")
    code, out = run_git(repo, env, "commit", "-m", f"自动收录 {len(added)} 个新项目（{stamp}）")
    print(out.strip().splitlines()[0] if out.strip() else "")
    code, out = run_git(repo, env, "push")
    print(out.strip())

    state["published"] = dict(state.get("published", {}))
    for item in added:
        state["published"][item["id"]] = item["title"]
    state["candidates"] = {
        r["id"]: {"title": r["title"], "date": r["created"], "score": v}
        for v, _, r in skipped
    }
    state["last_run"] = datetime.now().isoformat(timespec="seconds")
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    pushed = "main -> main" in out or "Everything up-to-date" in out
    print(f"\n{'推送完成' if pushed else '推送可能失败，看上面的输出'}")
    if skipped:
        print(f"另有 {len(skipped)} 个会话未达门槛，已记入候选清单")
    return 0


if __name__ == "__main__":
    sys.exit(main())
