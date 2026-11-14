"""占位符保护：翻译前把 {name}、%s、URL、`code` 换成哨兵标记，翻完再还原。

机器翻译经常会把手伸进占位符里（有道就把 {file} 翻成了 {文件}），所以先挖空再送出去。

标记形式是实测选出来的：私用区字符（U+E000）会被有道和 MyMemory 直接吃掉，
`[[0]]` 在长句里也会被平滑掉；`{{0}}` 在长句、短句、两家接口里都能原样返回。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

OPEN = "{{"
CLOSE = "}}"
_FLAVORS = ("", "x", "y", "z", "q")

# 顺序有意义：代码块要最先挖掉，避免里面的内容被后面的规则重复匹配
PATTERNS: tuple[str, ...] = (
    r"```[\s\S]*?```",                       # 围栏代码块
    r"`[^`\n]+`",                            # 行内代码
    r"\{\{[^}\n]{1,60}\}\}",                 # {{var}}
    r"\{[^{}\n]{1,60}\}",                    # {name} {0}
    r"%\([A-Za-z_][A-Za-z0-9_]*\)[a-zA-Z]",  # %(name)s
    r"%[0-9]+\$[a-zA-Z]",                    # %1$s
    r"%[sdifu]",                             # %s
    r"\$\{[^}\n]{1,60}\}",                   # ${env}
    r"@string/[A-Za-z0-9_.]+",               # Android 资源引用
    r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^<>\n]{0,80})?>",  # <b> <br/> <a href="...">
    r"&[a-zA-Z]{2,8};|&#\d{1,6};",           # HTML 实体
    r"\\[ntr]",                              # \n \t
    r"https?://[^\s，。；、）】\"']+",          # 链接
    r"\b[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9-.]+",  # 邮箱
)

_RE = re.compile("|".join(f"(?:{p})" for p in PATTERNS))


def _token_re(flavor: str) -> re.Pattern[str]:
    return re.compile(r"\{\{" + re.escape(flavor) + r"(\d+)\}\}")


def _pick_flavor(text: str) -> str:
    """原文里本来就有 [[0]] / [[x0]] 这类写法时换个标记，免得还原时误伤。"""

    for flavor in _FLAVORS:
        if not _token_re(flavor).search(text):
            return flavor
    return "k"


@dataclass
class Guard:
    """一次翻译的占位符保护上下文。"""

    masked: str
    store: list[str] = field(default_factory=list)
    flavor: str = ""

    def restore(self, text: str) -> tuple[str, list[int]]:
        """还原占位符，返回（文本，缺失的占位符下标）。"""

        seen: set[int] = set()

        def repl(match: re.Match) -> str:
            index = int(match.group(1))
            seen.add(index)
            if 0 <= index < len(self.store):
                return self.store[index]
            return match.group(0)

        restored = _token_re(self.flavor).sub(repl, text)
        missing = [i for i in range(len(self.store)) if i not in seen]
        return restored, missing

    def strip(self, text: str) -> str:
        """清掉残留标记（翻译器把占位符吃掉了才需要）。"""

        return _token_re(self.flavor).sub(" ", text)


def protect(text: str) -> Guard:
    """挖空文本里的占位符，返回 Guard（含 masked 文本与还原能力）。"""

    store: list[str] = []
    flavor = _pick_flavor(text)

    def repl(match: re.Match) -> str:
        store.append(match.group(0))
        return f"{OPEN}{flavor}{len(store) - 1}{CLOSE}"

    return Guard(masked=_RE.sub(repl, text), store=store, flavor=flavor)


def split(text: str) -> list[tuple[bool, str]]:
    """按占位符把原文切成交替的 (是否占位符, 片段)。

    标记被翻译器吃掉时的兜底：把占位符两边的文字分开翻译，再拼回去，
    这样占位符根本不会进入翻译引擎。
    """

    out: list[tuple[bool, str]] = []
    last = 0
    for match in _RE.finditer(text):
        if match.start() > last:
            out.append((False, text[last : match.start()]))
        out.append((True, match.group(0)))
        last = match.end()
    if last < len(text):
        out.append((False, text[last:]))
    return out


def count(text: str) -> int:
    return len(_RE.findall(text))
