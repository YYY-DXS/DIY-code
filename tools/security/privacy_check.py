#!/usr/bin/env python3
"""推送前的隐私检查：扫出不该公开的内容，有问题就中止提交。

用法:
    python privacy_check.py              # 检查暂存区（提交前用）
    python privacy_check.py --all        # 检查仓库里全部跟踪文件
    python privacy_check.py --files a.md b.py

退出码 0 = 通过，1 = 发现问题（调用方应中止提交/推送）。

设计要点：用户名等敏感字符串从运行时环境读取，不写死在文件里，
否则这个检查脚本自己就会成为泄露源。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- 规则

USER = Path.home().name  # 运行时取，不写死

# 危险文件名 / 扩展名：这些根本不该进仓库
FORBIDDEN_EXT = {".docx", ".html", ".pem", ".key", ".pfx", ".zip", ".7z"}
FORBIDDEN_NAMES = {"state.json", "token.txt", "id_rsa", "id_ed25519", "credentials"}
FORBIDDEN_PARTS = {".ssh", ".keys", "node_modules", "__pycache__"}

# 邮箱白名单（Git 自带的假邮箱、示例邮箱不算泄露）
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
    ("私钥文件内容", "block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("Bearer 令牌", "block", r"[Bb]earer\s+[A-Za-z0-9\-_.]{20,}"),
    ("手机号", "block", r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    ("身份证号", "block", r"(?<!\d)\d{17}[\dXx](?!\d)"),
    ("银行卡号", "block", r"(?<!\d)\d{16,19}(?!\d)"),
    # 只认“引号包起来的、像密钥的值”，避免把 token = payload.get(...) 这类代码误判
    ("密码 / 密钥字段", "block",
     r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|apikey|access[_-]?token)\b"
     r"\s*[:=]\s*[\"']([A-Za-z0-9+/=_\-.]{12,})[\"']"),
    ("身体 / 健康描述", "block", r"腿瘸|右腿|左腿|残疾|行动不便|瘫痪"),
    ("情感 / 心理话题", "block", r"情感困扰|心理问题|抑郁|焦虑症|自残"),
    ("聊天记录链接", "block", r"chat\.deepseek\.com/a/chat/s/[0-9a-fA-F\-]{8,}"),
    ("邮箱地址", "warn", r"[\w.\-+]+@[\w\-]+\.[A-Za-z]{2,}"),
    ("翻墙 / 网络工具", "warn", r"VPN|翻墙|梯子|机场订阅|节点订阅"),
    ("会话 ID", "warn", r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
]

# 占位符：出现在示例代码里的假密码不算泄露
PLACEHOLDER = re.compile(
    r"你的|你的的|自己|替换|修改|示例|xxx|XXX|\*\*\*|your|YOUR|example|placeholder"
    r"|changeme|TODO|<[^>]+>|\$\{|%s|%d|%v",
)

# 这个检查脚本自身会包含规则字样，不扫自己
SKIP_PATHS = {"tools/security/privacy_check.py"}

TEXT_EXT = {
    ".md", ".txt", ".json", ".jsonl", ".py", ".mjs", ".js", ".ts", ".cmd", ".bat",
    ".ps1", ".sh", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".cpp", ".c", ".h",
    ".cs", ".java", ".csv", ".tsv", ".xml", ".manifest", ".gitignore", "",
}


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return proc.stdout


def staged_files() -> list[str]:
    return [f for f in git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines() if f]


def tracked_files() -> list[str]:
    return [f for f in git("ls-files").splitlines() if f]


def read_text(path: Path) -> str | None:
    if path.suffix.lower() not in TEXT_EXT:
        return None
    try:
        return path.read_text(encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, OSError):
        try:
            return path.read_text(encoding="gbk", errors="ignore")
        except OSError:
            return None


def mask(text: str, keep: int = 4) -> str:
    text = text.strip()
    if len(text) <= keep * 2:
        return text[:keep] + "***"
    return f"{text[:keep]}***{text[-2:]}"


def luhn_ok(number: str) -> bool:
    """银行卡号校验，用来过滤长数字的误报。"""
    digits = [int(c) for c in number]
    checksum = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def scan(paths: list[str]) -> list[tuple[str, int, str, str, str]]:
    """返回 [(文件, 行号, 规则名, 脱敏片段, 级别)]"""
    findings: list[tuple[str, int, str, str, str]] = []
    for rel in paths:
        if rel.replace("\\", "/") in SKIP_PATHS:
            continue
        path = Path(rel)
        suffix = path.suffix.lower()
        if suffix in FORBIDDEN_EXT:
            findings.append((rel, 0, "不该上传的文件类型", suffix, "block"))
            continue
        if path.name in FORBIDDEN_NAMES or set(path.parts) & FORBIDDEN_PARTS:
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
                        # 全是重复字符的 ID 是测试用的假数据
                        if len(set(tail.lower())) <= 2:
                            continue
                    if label == "密码 / 密钥字段":
                        value = match.group(2) if match.lastindex else ""
                        if not value or PLACEHOLDER.search(value):
                            continue
                        hit = value
                    findings.append((rel, line_no, label, mask(hit), level))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description="推送前隐私检查")
    ap.add_argument("--all", action="store_true", help="检查全部跟踪文件")
    ap.add_argument("--files", nargs="*", help="指定文件")
    args = ap.parse_args()

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
    blocking = [f for f in findings if f[4] == "block"]
    warnings = [f for f in findings if f[4] != "block"]

    if not findings:
        print(f"隐私检查通过：{len(paths)} 个文件，未发现问题 ✓")
        return 0

    def dump(items: list[tuple[str, int, str, str, str]]) -> None:
        seen: set[tuple[str, str]] = set()
        for rel, line_no, label, snippet, _level in items:
            key = (rel, label)
            if key in seen:
                continue
            seen.add(key)
            where = f"第 {line_no} 行" if line_no else "整个文件"
            print(f"  ● {rel}（{where}）")
            print(f"      {label}：{snippet}")

    if blocking:
        print(f"⚠ 隐私检查没通过：{len(blocking)} 处必须处理\n")
        dump(blocking)
    if warnings:
        print(f"\n提醒（不阻止提交）：{len(warnings)} 处值得看一眼\n")
        dump(warnings)

    if blocking:
        print(
            "\n已中止提交。处理办法：删掉或脱敏这些内容，或把文件加进 .gitignore。\n"
            "确认确实要上传，就手动 git commit 再 git push，检查只拦自动化流程。"
        )
        return 1
    print("\n检查通过（有提醒项，但没有阻断项）✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
