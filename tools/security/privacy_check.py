#!/usr/bin/env python3
"""推送前的隐私检查与自动脱敏。

三种模式：
    python privacy_check.py --check   只检查（默认），发现问题返回 1
    python privacy_check.py --fix     检查并就地脱敏，改不掉的仍然返回 1
    python privacy_check.py --auto    全自动：能改的就改，改不掉的文件自动撤出提交

`--auto` 是给自动推送流程用的：先脱敏，再把含整段私人文字的文件撤出本次提交，
最后重新检查一遍，全部干净才让提交继续。

改动前会把原文件备份到 tools/security/backup/，日志写进 tools/security/fix-log.txt。
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 中文 Windows 控制台默认 GBK，直接打印 ✓ / ⚠ 会崩，强制 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

HERE = Path(__file__).resolve().parent
BACKUP_ROOT = HERE / "backup"
LOG_FILE = HERE / "fix-log.txt"

USER = Path.home().name  # 运行时取，不写死

# ---------------------------------------------------------------- 规则

BLOCK_EXT = {".docx", ".html", ".pem", ".key", ".pfx", ".zip", ".7z"}
BLOCK_NAMES = {
    "state.json", "token.txt", "seed_published.json", "id_rsa", "id_ed25519", "credentials",
}
BLOCK_PARTS = {".ssh", ".keys", "node_modules", "__pycache__"}

EMAIL_OK = re.compile(
    r"(git@github\.com|git@gitee\.com|.*@users\.noreply\.github\.com"
    r"|.*@users\.noreply\.gitee\.com|.*@example\.(com|org)|.*@localhost"
    r"|.*@.*\.local|no-?reply@.*)",
    re.I,
)

PATTERNS: list[tuple[str, str, str]] = [
    ("本机用户路径", "block", rf"[A-Za-z]:[\\/]Users[\\/]{re.escape(USER)}(?![A-Za-z0-9])"),
    ("API 密钥（sk-）", "block", r"sk-[A-Za-z0-9_\-]{16,}"),
    ("GitHub 令牌", "block", r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"),
    ("云服务密钥", "block", r"AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{30,}"),
    ("私钥内容", "block",
     r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    ("Bearer 令牌", "block", r"[Bb]earer\s+[A-Za-z0-9\-_.]{20,}"),
    ("手机号", "block", r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    ("身份证号", "block", r"(?<!\d)\d{17}[\dXx](?!\d)"),
    ("银行卡号", "block", r"(?<!\d)\d{16,19}(?!\d)"),
    ("密码 / 密钥字段", "block",
     r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|apikey|access[_-]?token)\b"
     r"\s*[:=]\s*[\"']([A-Za-z0-9+/=_\-.]{12,})[\"']"),
    ("身体 / 健康描述", "prose", r"腿瘸|右腿|左腿|残疾|行动不便|瘫痪"),
    ("情感 / 心理话题", "prose", r"情感困扰|心理问题|抑郁|焦虑症|自残"),
    ("聊天记录链接", "block", r"chat\.deepseek\.com/a/chat/s/[0-9a-fA-F\-]{8,}"),
    ("邮箱地址", "warn", r"[\w.\-+]+@[\w\-]+\.[A-Za-z]{2,}"),
    ("翻墙 / 网络工具", "warn", r"VPN|翻墙|梯子|机场订阅|节点订阅"),
    ("会话 ID", "warn", r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
]

# 可以机械替换的规则：规则名 → (匹配模式, 替换成什么)
FIXERS: dict[str, tuple[str, str]] = {
    "本机用户路径": (rf"[A-Za-z]:[\\/]Users[\\/]{re.escape(USER)}", r"C:\Users\<用户>"),
    "API 密钥（sk-）": (r"sk-[A-Za-z0-9_\-]{16,}", "sk-***已移除***"),
    "GitHub 令牌": (
        r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}",
        "***令牌已移除***",
    ),
    "云服务密钥": (r"AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{30,}", "***密钥已移除***"),
    "私钥内容": (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
        "***私钥内容已移除***",
    ),
    "Bearer 令牌": (r"[Bb]earer\s+[A-Za-z0-9\-_.]{20,}", "Bearer ***已移除***"),
    "手机号": (r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号已隐藏]"),
    "身份证号": (r"(?<!\d)\d{17}[\dXx](?!\d)", "[身份证号已隐藏]"),
    "银行卡号": (r"(?<!\d)\d{16,19}(?!\d)", "[银行卡号已隐藏]"),
    "聊天记录链接": (
        r"chat\.deepseek\.com/a/chat/s/[0-9a-fA-F\-]{8,}",
        "chat.deepseek.com/a/chat/s/***",
    ),
    "会话 ID": (
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "00000000-0000-0000-0000-000000000000",
    ),
    "邮箱地址": (r"[\w.\-+]+@[\w\-]+\.[A-Za-z]{2,}", "[邮箱已隐藏]"),
}

PLACEHOLDER = re.compile(
    r"你的|自己|替换|修改|示例|xxx|XXX|\*\*\*|your|YOUR|example|placeholder"
    r"|changeme|TODO|<[^>]+>|\$\{|%s|%d|%v|已隐藏|已移除"
)

SKIP_PATHS = {"tools/security/privacy_check.py"}

TEXT_EXT = {
    ".md", ".txt", ".json", ".jsonl", ".py", ".mjs", ".js", ".ts", ".cmd", ".bat",
    ".ps1", ".sh", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".cpp", ".c", ".h",
    ".cs", ".java", ".csv", ".tsv", ".xml", ".manifest", ".gitignore", "",
}


# ---------------------------------------------------------------- 基础工具


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return proc.stdout


def staged_files() -> list[str]:
    return [
        f
        for f in git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines()
        if f
    ]


def tracked_files() -> list[str]:
    return [f for f in git("ls-files").splitlines() if f]


def read_text(path: Path) -> str | None:
    if path.suffix.lower() not in TEXT_EXT:
        return None
    for encoding in ("utf-8", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        except OSError:
            return None
    return None


def mask(text: str, keep: int = 4) -> str:
    text = text.strip()
    return text[:keep] + "***" if len(text) > keep else "***"


def luhn_ok(number: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(number)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def log(text: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {text}\n")
    except OSError:
        pass


# ---------------------------------------------------------------- 扫描


def scan(paths: list[str]) -> list[tuple[str, int, str, str, str]]:
    """返回 [(文件, 行号, 规则名, 脱敏片段, 级别)]"""
    findings: list[tuple[str, int, str, str, str]] = []
    for rel in paths:
        if rel.replace("\\", "/") in SKIP_PATHS:
            continue
        path = Path(rel)
        suffix = path.suffix.lower()
        if suffix in BLOCK_EXT:
            findings.append((rel, 0, "不该上传的文件类型", suffix, "block"))
            continue
        if path.name in BLOCK_NAMES or set(path.parts) & BLOCK_PARTS:
            findings.append((rel, 0, "不该上传的文件名", path.name, "block"))
            continue
        text = read_text(path)
        if text is None:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            for label, level, pattern in PATTERNS:
                for match in re.finditer(pattern, line):
                    hit = match.group(0)
                    if label == "邮箱地址" and EMAIL_OK.match(hit):
                        continue
                    if label == "银行卡号" and not luhn_ok(hit):
                        continue
                    if label == "聊天记录链接":
                        tail = hit.rstrip("/").split("/")[-1]
                        if len(set(tail.lower())) <= 2:
                            continue
                    if label == "密码 / 密钥字段":
                        value = match.group(2) if match.lastindex else ""
                        if not value or PLACEHOLDER.search(value):
                            continue
                        hit = value
                    findings.append((rel, line_no, label, mask(hit), level))
    return findings


# ---------------------------------------------------------------- 脱敏


def sanitize(path: Path) -> list[tuple[str, int]]:
    """就地脱敏，返回 [(规则名, 替换次数)]"""
    text = read_text(path)
    if text is None:
        return []
    original = text
    applied: list[tuple[str, int]] = []

    # 替换文本里有反斜杠（比如 C:\Users），必须用函数替换，否则会被当成正则转义
    def literal(value: str):
        return lambda _match: value

    for label, (pattern, replacement) in FIXERS.items():
        if label == "邮箱地址":
            text, count = re.subn(
                pattern,
                lambda m: m.group(0) if EMAIL_OK.match(m.group(0)) else replacement,
                text,
            )
        elif label == "密码 / 密钥字段":
            def repl(match):
                value = match.group(2)
                if not value or PLACEHOLDER.search(value):
                    return match.group(0)
                return match.group(0).replace(value, "***已移除***")

            text, count = re.subn(PATTERNS[9][2], repl, text)
        else:
            text, count = re.subn(pattern, literal(replacement), text)
        if count:
            applied.append((label, count))

    if text != original:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = BACKUP_ROOT / stamp / path.name
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
        path.write_text(text, encoding="utf-8")
    return applied


def dump(items: list[tuple[str, int, str, str, str]], title: str) -> None:
    if not items:
        return
    print(f"\n{title}（{len(items)} 处）")
    seen: set[tuple[str, str]] = set()
    for rel, line_no, label, snippet, _level in items:
        if (rel, label) in seen:
            continue
        seen.add((rel, label))
        where = f"第 {line_no} 行" if line_no else "整个文件"
        print(f"  ● {rel}（{where}）")
        print(f"      {label}：{snippet}")


# ---------------------------------------------------------------- 主流程


def main() -> int:
    ap = argparse.ArgumentParser(description="推送前隐私检查与自动脱敏")
    ap.add_argument("--check", action="store_true", help="只检查（默认）")
    ap.add_argument("--fix", action="store_true", help="就地脱敏，改不掉的仍拦截")
    ap.add_argument("--auto", action="store_true", help="全自动：能改的改，改不掉的文件撤出提交")
    ap.add_argument("--all", action="store_true", help="检查全部跟踪文件（配合 --check）")
    ap.add_argument("--files", nargs="*", help="指定文件")
    args = ap.parse_args()

    mode = "auto" if args.auto else ("fix" if args.fix else "check")

    if args.files:
        paths = args.files
    elif args.all:
        paths = tracked_files()
    else:
        paths = staged_files()
        if not paths:
            print("暂存区没有改动，跳过检查。")
            return 0

    findings = scan(paths)
    if not findings:
        print(f"隐私检查通过：{len(paths)} 个文件，未发现问题 ✓")
        return 0

    if mode == "check":
        blocking = [f for f in findings if f[4] in ("block", "prose")]
        warnings = [f for f in findings if f[4] == "warn"]
        dump(blocking, "⚠ 没通过：这些内容必须处理")
        dump(warnings, "提醒（不阻止提交）")
        if blocking:
            print("\n已中止。用 --fix 自动脱敏，或用 --auto 全自动处理。")
            return 1
        print("\n检查通过（有提醒项，但没有阻断项）✓")
        return 0

    # ---- 脱敏模式 ----
    fixable = [f for f in findings if f[2] in FIXERS]
    unfixable = [f for f in findings if f[2] not in FIXERS and f[4] in ("block", "prose")]
    warnings = [f for f in findings if f[4] == "warn" and f[2] not in FIXERS]

    changed_files = sorted({f[0] for f in fixable})
    print(f"自动脱敏：{len(changed_files)} 个文件、{len(fixable)} 处")
    for rel in changed_files:
        applied = sanitize(Path(rel))
        if not applied:
            continue
        detail = "、".join(f"{label}×{count}" for label, count in applied)
        print(f"  ● {rel}：{detail}")
        log(f"脱敏 {rel}：{detail}")
        for label, _count in applied:
            sample = next((f[3] for f in fixable if f[0] == rel and f[2] == label), "")
            if sample:
                log(f"    命中示例 {label}：{sample}")
        subprocess.run(["git", "add", "--", rel], capture_output=True)

    if unfixable:
        files = sorted({f[0] for f in unfixable})
        print(f"\n改不掉的内容（整段私人文字）：{len(files)} 个文件")
        for rel in files:
            labels = sorted({f[2] for f in unfixable if f[0] == rel})
            print(f"  ● {rel}：{'、'.join(labels)}")
            log(f"撤出提交 {rel}：{'、'.join(labels)}")
        if mode == "auto":
            for rel in files:
                subprocess.run(["git", "restore", "--staged", "--", rel], capture_output=True)
            print("  已撤出本次提交（本地文件保留，只是不推上去）")
        else:
            print("\n--fix 不会自动撤出文件。处理掉这些内容，或改用 --auto。")
            return 1

    dump(warnings, "提醒（不阻止提交）")

    remaining = [f for f in scan(staged_files()) if f[4] in ("block", "prose")]
    if remaining:
        dump(remaining, "⚠ 复查仍有问题")
        return 1

    print("\n处理完成，可以继续提交 ✓")
    log(f"运行模式 {mode}：完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
