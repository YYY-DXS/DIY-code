"""占位符 / 格式符保护与校验。

汉化最容易翻车的地方：翻译之后 ``{0}``、``%s``、``%1$s``、``${name}``、``<b>``
被吃掉或被改写，程序轻则显示错乱，重则直接抛异常崩掉。

做法：翻译前把它们包进私用区哨兵 ``\\ue000{0}\\ue001``（哨兵内容就是占位符本身，
翻译器倾向于原样保留），翻译后再拆掉哨兵还原，并独立校验一遍数量与顺序。

为什么用「内容命名」而不是「位置编号」：``{0} of {1}`` 译成中文常要写成
``{1} / {0}``，位置编号方案会还原错位，内容命名方案天然支持换序。
"""

from __future__ import annotations

import re
from collections import Counter

PH_OPEN = "\ue000"
PH_CLOSE = "\ue001"

# 顺序很重要：长模式必须排在短模式前面，否则 {0} 会被 {{...}} 之类的模式截胡。
_PATTERN_SPECS: list[tuple[str, str]] = [
    ("double_brace", r"\{\{[^{}]{1,64}\}\}"),
    ("indexed_brace", r"\{[0-9]{1,3}\}"),
    ("named_brace", r"\{[A-Za-z_][A-Za-z0-9_.]{0,40}\}"),
    ("percent_positional", r"%\d+\$[-+#0-9.]*[sdifegxX]"),
    ("percent_named", r"%\([A-Za-z_][A-Za-z0-9_]*\)[-+#0-9.]*[sdifegxX]"),
    ("percent_plain", r"%[-+#0-9.]*[sdifegxX%]"),
    ("dollar_brace", r"\$\{[A-Za-z_][A-Za-z0-9_.]*\}"),
    ("dollar_var", r"\$[A-Za-z_][A-Za-z0-9_]*"),
    ("at_string", r"@string/[A-Za-z0-9_.]+"),
    ("xml_tag", r"</?[A-Za-z][A-Za-z0-9:_-]*(?:\s[^<>]{0,120})?/?>"),
    ("entity", r"&(?:[A-Za-z][A-Za-z0-9]{1,20}|#[0-9]{1,6}|#x[0-9A-Fa-f]{1,6});"),
    ("escape_seq", r"\\[ntr\\\"']"),
]

_MASTER = re.compile(
    "|".join(f"(?P<{name}>{pattern})" for name, pattern in _PATTERN_SPECS),
    re.UNICODE,
)

_SENTINEL_RE = re.compile(rf"{PH_OPEN}(.*?){PH_CLOSE}", re.S)

# 位置敏感的模式：这些占位符不允许交换顺序。
_ORDER_SENSITIVE = {"percent_plain", "percent_positional"}


def protect(text: str) -> tuple[str, list[str]]:
    """把占位符替换成哨兵字符，返回 (打码后的文本, 原始占位符列表)。"""
    tokens: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        tokens.append(match.group(0))
        return f"{PH_OPEN}{match.group(0)}{PH_CLOSE}"

    return _MASTER.sub(_sub, text), tokens


def restore(text: str, tokens: list[str] | None = None) -> str:
    """把哨兵字符还原成原始占位符。"""
    return _SENTINEL_RE.sub(lambda match: match.group(1), text)


def leftovers(text: str) -> list[str]:
    """找出残缺的哨兵（翻译器删掉了半个哨兵，或改写了内容）。"""
    problems: list[str] = []
    if text.count(PH_OPEN) != text.count(PH_CLOSE):
        problems.append(
            f"[错误] 哨兵字符不成对：开 {text.count(PH_OPEN)} 个 / 闭 {text.count(PH_CLOSE)} 个"
        )
    return problems


def tokens_of(text: str) -> Counter[str]:
    """按出现次数统计文本里的占位符。"""
    return Counter(m.group(0) for m in _MASTER.finditer(text))


def token_sequence(text: str) -> list[str]:
    """按出现顺序返回占位符，用于判断位置敏感的模式有没有被换序。"""
    return [m.group(0) for m in _MASTER.finditer(text)]


def validate(source: str, target: str) -> list[str]:
    """校验译文是否安全。返回问题列表，以 ``[错误]`` 开头的代表不可接受。"""
    problems: list[str] = []
    if not target:
        return ["[错误] 译文为空"]

    src, tgt = tokens_of(source), tokens_of(target)
    for token, count in sorted((src - tgt).items()):
        problems.append(f"[错误] 译文缺少占位符 {token!r}（源文出现 {count} 次）")
    for token, count in sorted((tgt - src).items()):
        problems.append(f"[错误] 译文多出占位符 {token!r}（多了 {count} 个）")

    if not problems and src:
        src_seq = [
            t
            for t in token_sequence(source)
            if _kind_of(t) in _ORDER_SENSITIVE
        ]
        tgt_seq = [
            t
            for t in token_sequence(target)
            if _kind_of(t) in _ORDER_SENSITIVE
        ]
        if src_seq != tgt_seq:
            problems.append(
                f"[警告] 位置敏感占位符顺序被改变：{src_seq} -> {tgt_seq}"
            )

    if source.count("\n") != target.count("\n"):
        problems.append(
            f"[警告] 换行数不一致：源文 {source.count(chr(10))} 行，译文 {target.count(chr(10))} 行"
        )

    if _looks_markup(source):
        open_tags = re.findall(r"</?([A-Za-z][A-Za-z0-9:_-]*)", source)
        target_tags = re.findall(r"</?([A-Za-z][A-Za-z0-9:_-]*)", target)
        if Counter(open_tags) != Counter(target_tags):
            problems.append(
                f"[警告] 标签集合不一致：{sorted(set(open_tags) ^ set(target_tags))}"
            )

    return problems


def is_valid(problems: list[str]) -> bool:
    return not any(p.startswith("[错误]") for p in problems)


def _kind_of(token: str) -> str:
    for name, pattern in _PATTERN_SPECS:
        if re.fullmatch(pattern, token):
            return name
    return "unknown"


def _looks_markup(text: str) -> bool:
    return bool(re.search(r"</?[A-Za-z][A-Za-z0-9:_-]*\s*/?>", text))
