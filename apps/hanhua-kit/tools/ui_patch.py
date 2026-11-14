"""给 Electron 应用自带的语言包打补丁（只改界面文案，不碰程序逻辑）。

流程：
    build  从 app.asar 里取出某个语言包 -> 应用译文修正 -> 补齐到原字节长度 -> 校验
    apply  把补丁原地写回 app.asar（需要管理员权限，并且要先退出应用）
    verify 检查当前 asar 里的语言包是原版还是已打补丁

用法：
    python tools/ui_patch.py build  --asar <app.asar> --locale zh-CN --fixes demo/codex-ui-fixes.csv --outdir out/ui-patch
    python tools/ui_patch.py apply  --patch out/ui-patch/patch.json
    python tools/ui_patch.py verify --patch out/ui-patch/patch.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from asar_tool import Asar  # noqa: E402
from hanhua import locale_chunk, placeholders  # noqa: E402

RUNNING_HINTS = ("chatgpt.exe", "codex.exe")


def read_fixes(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    fixes = []
    for row in rows:
        key = (row.get("key") or "").strip()
        target = (row.get("target") or row.get("译文") or "").strip()
        source = (row.get("source") or row.get("原文") or "").strip()
        if key and target:
            fixes.append({"key": key, "source": source, "target": target})
    return fixes


def check_tokens(fix: dict) -> list[str]:
    """汉化老规矩：占位符一个都不能少。"""
    problems = []
    if not fix["source"]:
        return problems
    source_tokens = placeholders.tokens_of(fix["source"])
    target_tokens = placeholders.tokens_of(fix["target"])
    for token, count in (source_tokens - target_tokens).items():
        problems.append(f"{fix['key']} 少了占位符 {token}（{count} 个）")
    for token, count in (target_tokens - source_tokens).items():
        problems.append(f"{fix['key']} 多了占位符 {token}（{count} 个）")
    return problems


def node_check(path: Path) -> tuple[bool, str]:
    """用 node --check 验证打补丁后的 JS 仍然是合法语法。"""
    node = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
    if not node.exists():
        return True, "（没找到 node，跳过语法校验）"
    result = subprocess.run(
        [str(node), "--check", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return result.returncode == 0, (result.stderr or "").strip()[:400]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def cmd_build(args) -> int:
    archive = Asar(args.asar)
    inner = next(
        (
            full
            for full, _info in archive.entries
            if full.startswith("webview/assets/") and Path(full).name.startswith(f"{args.locale}-")
        ),
        None,
    )
    if not inner:
        raise SystemExit(f"asar 里没有 {args.locale} 语言包")
    entry = next(info for full, info in archive.entries if full == inner)
    original = archive.read(inner)
    text = original.decode("utf-8", errors="replace")
    before = locale_chunk.parse(text)

    fixes = read_fixes(args.fixes)
    problems = [p for fix in fixes for p in check_tokens(fix)]
    if problems:
        raise SystemExit("占位符校验失败：\n  " + "\n  ".join(problems))

    mapping = {fix["key"]: fix["target"] for fix in fixes}
    unknown = [key for key in mapping if key not in before]
    if unknown:
        raise SystemExit(f"这些 key 不在语言包里：{unknown[:5]}")

    patched_text = locale_chunk.apply_fixes(text, mapping, pad_to=len(original))
    patched = patched_text.encode("utf-8")
    if len(patched) != len(original):
        raise SystemExit(f"长度没对齐：原 {len(original)} 字节 / 补丁 {len(patched)} 字节")

    after = locale_chunk.parse(patched.decode("utf-8"))
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    chunk_out = outdir / Path(inner).name
    chunk_out.write_bytes(patched)

    ok, message = node_check(chunk_out)
    descriptor = {
        "asar": str(Path(args.asar)),
        "inner": inner,
        "offset": archive.base + int(entry["offset"]),
        "size": len(original),
        "locale": args.locale,
        "keys_before": len(before),
        "keys_after": len(after),
        "changed": list(mapping),
        "sha256_before": sha256(original),
        "sha256_after": sha256(patched),
        "patched_file": str(chunk_out),
        "js_syntax_ok": ok,
    }
    (outdir / "patch.json").write_text(
        json.dumps(descriptor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"语言包      : {inner}（{len(original)} 字节）")
    print(f"条目        : {len(before)} 条 -> 补丁后 {len(after)} 条")
    print(f"修改        : {len(mapping)} 条")
    for fix in fixes:
        print(f"  · {fix['key'].split('.')[-1]:<7} {fix['target']}")
    print(f"长度对齐    : {len(patched)} 字节（原地替换后 asar 目录表无需改动）")
    print(f"JS 语法校验 : {'通过' if ok else '失败 ' + message}")
    print(f"补丁文件    : {chunk_out}")
    print(f"补丁描述    : {outdir / 'patch.json'}")
    return 0 if ok else 1


def cmd_build_text(args) -> int:
    """在 asar 里的某个 JS 文件做等长文本替换（用于强制特性开关）。"""
    archive = Asar(args.asar)
    inner = args.inner
    if not inner:
        hits = archive.grep(args.entry_needle.encode("utf-8"), 5) if args.entry_needle else []
        if not hits:
            raise SystemExit(f"没找到包含 {args.entry_needle!r} 的文件")
        inner = hits[0][1]
        print(f"按内容定位到 : {inner}")
    entry = next((info for full, info in archive.entries if full == inner), None)
    if entry is None:
        raise SystemExit(f"asar 里没有 {inner}")
    original = archive.read(inner)
    text = original.decode("utf-8", errors="replace")

    find, replace = args.find, args.replace
    occurrences = text.count(find)
    if occurrences != 1:
        raise SystemExit(f"命中 {occurrences} 次（要求恰好 1 次），请检查 --find：{find!r}")

    # 用空格补到等长，保证 asar 目录表不用改
    payload = replace + " " * (len(find) - len(replace))
    if len(payload) != len(find):
        raise SystemExit("替换串比原文长，无法等长替换")
    patched_text = text.replace(find, payload)
    patched = patched_text.encode("utf-8")
    if len(patched) != len(original):
        raise SystemExit(f"长度没对齐：原 {len(original)} / 新 {len(patched)}")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    chunk_out = outdir / Path(inner).name
    chunk_out.write_bytes(patched)
    ok, message = node_check(chunk_out)

    descriptor = {
        "asar": str(Path(args.asar)),
        "inner": inner,
        "offset": archive.base + int(entry["offset"]),
        "size": len(original),
        "kind": "text",
        "find": find,
        "replace": replace,
        "sha256_before": sha256(original),
        "sha256_after": sha256(patched),
        "patched_file": str(chunk_out),
        "js_syntax_ok": ok,
    }
    (outdir / "patch.json").write_text(
        json.dumps(descriptor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"目标文件    : {inner}（{len(original)} 字节）")
    print(f"替换        : {find!r}\n           -> {replace!r}（补 {len(find) - len(replace)} 个空格对齐）")
    print(f"长度对齐    : {len(patched)} 字节")
    print(f"JS 语法校验 : {'通过' if ok else '失败 ' + message}")
    print(f"补丁文件    : {chunk_out}")
    print(f"补丁描述    : {outdir / 'patch.json'}")
    return 0 if ok else 1


def app_running() -> list[str]:
    found: set[str] = set()
    try:
        result = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in result.stdout.splitlines():
            name = line.split(",")[0].strip('"').lower()
            if name in RUNNING_HINTS:
                found.add(name)
    except OSError:
        pass
    if not found:
        try:
            fallback = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-Process | Select-Object -ExpandProperty ProcessName"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            for name in fallback.stdout.split():
                if f"{name.lower()}.exe" in RUNNING_HINTS:
                    found.add(f"{name.lower()}.exe")
        except OSError:
            pass
    return sorted(found)


def cmd_apply(args) -> int:
    descriptor = json.loads(Path(args.patch).read_text(encoding="utf-8"))
    asar_path = Path(args.asar or descriptor["asar"])
    patched = Path(descriptor["patched_file"]).read_bytes()
    offset, size = int(descriptor["offset"]), int(descriptor["size"])

    running = app_running()
    if running and not args.force:
        raise SystemExit(
            f"检测到应用正在运行（{', '.join(running)}），请先完全退出再打补丁。"
            "（asar 被占用时写入会失败，也可能让运行中的窗口读到半截文件）"
        )

    with asar_path.open("rb") as handle:
        handle.seek(offset)
        current = handle.read(size)
    digest = sha256(current)
    if digest == descriptor["sha256_after"]:
        print("当前已是打过补丁的版本，无需处理。")
        return 0
    if digest != descriptor["sha256_before"]:
        raise SystemExit(
            "文件内容与预期不一致（应用可能已更新到新版本），请重新执行 build。"
        )

    # 备份写到补丁目录（WindowsApps 目录本身不可写，别往那里放备份）
    backup = Path(args.backup or (Path(descriptor["patched_file"]).parent / "asar-backup.bin"))
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(current)
    print(f"已备份原始语言包 {len(current)} 字节 -> {backup}")

    try:
        with asar_path.open("r+b") as handle:  # 先探测写权限，失败时给出人话提示
            pass
    except PermissionError:
        raise SystemExit(
            "无法写入 app.asar：WindowsApps 目录归 TrustedInstaller 所有，"
            "管理员身份也默认只有读+执行权限。\n"
            "真要用这个补丁，需要先夺取该文件所有权（takeown/icacls），"
            "这会破坏 MSIX 包的完整性校验，且应用每次更新都会覆盖回去 —— 请确认你接受这些后果。\n"
            f"补丁本身已就绪：{descriptor['patched_file']}（可自行用其它方式替换）"
        )

    try:
        with asar_path.open("r+b") as handle:
            handle.seek(offset)
            handle.write(patched)
    except PermissionError:
        raise SystemExit(
            "写入被系统拒绝。WindowsApps 目录受保护，请用管理员身份重新运行：\n"
            f'  Start-Process powershell -Verb RunAs -ArgumentList \'-Command "python {Path(__file__).resolve()} '
            f'apply --patch {Path(args.patch).resolve()}"\''
        )
    print(f"补丁已写入 {asar_path}（偏移 {offset}，{len(patched)} 字节）")
    print("重启应用后生效。回滚方式：把备份文件写回同一偏移即可。")
    return 0


def cmd_verify(args) -> int:
    descriptor = json.loads(Path(args.patch).read_text(encoding="utf-8"))
    with Path(args.asar or descriptor["asar"]).open("rb") as handle:
        handle.seek(int(descriptor["offset"]))
        current = handle.read(int(descriptor["size"]))
    digest = sha256(current)
    if digest == descriptor["sha256_after"]:
        print("状态：已汉化（补丁生效）")
        return 0
    if digest == descriptor["sha256_before"]:
        print("状态：原版（未打补丁）")
        return 0
    print("状态：未知（文件被改动过，可能应用已更新）")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Electron 语言包补丁工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="构建补丁")
    p.add_argument("--asar", required=True)
    p.add_argument("--locale", default="zh-CN")
    p.add_argument("--fixes", required=True)
    p.add_argument("--outdir", default="out/ui-patch")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("build-text", help="构建等长文本补丁（改开关用）")
    p.add_argument("--asar", required=True)
    p.add_argument("--inner", default=None, help="asar 内部路径；不填则用 --entry-needle 自动定位")
    p.add_argument("--entry-needle", default=None, help="用来定位目标文件的短标记，例如 enable_i18n")
    p.add_argument("--find", required=True)
    p.add_argument("--replace", required=True)
    p.add_argument("--outdir", default="out/ui-patch")
    p.set_defaults(func=cmd_build_text)

    p = sub.add_parser("apply", help="写回 asar（需管理员权限）")
    p.add_argument("--patch", required=True)
    p.add_argument("--backup", default=None)
    p.add_argument("--force", action="store_true", help="即使检测到应用在运行也强行写入")
    p.add_argument("--asar", default=None, help="覆盖补丁描述里的 asar 路径（用于测试/绿色版）")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("verify", help="检查补丁状态")
    p.add_argument("--patch", required=True)
    p.add_argument("--asar", default=None)
    p.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
