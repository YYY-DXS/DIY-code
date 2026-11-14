"""解析与修改 Vite/rolldown 打包出来的语言包 chunk。

这类文件的形态：

    var e,t,n;function de(){return(de=ee((()=>{e=`独立字符串`,t=`…`})))}export{…}
    …以及一个大对象：{"dotted.key":`译文`, "another.key":`译文`}

译文用反引号包住，因为 ICU 消息里有 ``{a, plural, one {…} other {…}}`` 这种嵌套花括号。
写回时必须保持 JS 语法合法、且（为了原地补丁）保持文件字节长度不变。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PAIR_RE = re.compile(r'"([^"\\]{1,200})"\s*:\s*`')
_ASSIGN_RE = re.compile(r"([A-Za-z_$][\w$]*)\s*=\s*`")
_DECL_RE = re.compile(r"\bvar\s+([A-Za-z_$][\w$]*(?:\s*,\s*[A-Za-z_$][\w$]*)*)\s*;")
_EXPORT_RE = re.compile(r"export\s*\{([^}]*)\}")


@dataclass
class Entry:
    key: str
    value: str
    start: int  # 值起点（开头反引号之后）
    end: int  # 值终点（结尾反引号之前）


def _read_template(text: str, index: int) -> tuple[str, int]:
    """从 ``index``（开头反引号之后）读到结尾反引号，返回 (内容, 结尾反引号下标)。"""
    buffer: list[str] = []
    while index < len(text):
        char = text[index]
        if char == "\\":
            buffer.append(text[index : index + 2])
            index += 2
            continue
        if char == "`":
            return "".join(buffer), index
        buffer.append(char)
        index += 1
    raise ValueError("模板字符串缺少结束反引号，文件可能不是语言包 chunk")


def iter_entries(text: str) -> list[Entry]:
    """列出所有 ``"key": `value` `` 条目（重复 key 以第一次为准）。"""
    entries: list[Entry] = []
    seen: set[str] = set()
    for match in _PAIR_RE.finditer(text):
        key = match.group(1)
        if key in seen:
            continue
        value, end = _read_template(text, match.end())
        seen.add(key)
        entries.append(Entry(key, value, match.end(), end))
    return entries


def parse(text: str) -> dict[str, str]:
    """返回 {key: 译文}，同时包含 export 形式的独立字符串。"""
    result = {entry.key: entry.value for entry in iter_entries(text)}
    declarations = list(_DECL_RE.finditer(text))
    for index, declaration in enumerate(declarations):
        end = declarations[index + 1].start() if index + 1 < len(declarations) else len(text)
        body = text[declaration.end() : end]
        if "`" not in body:
            continue
        values: dict[str, str] = {}
        position = 0
        while True:
            match = _ASSIGN_RE.search(body, position)
            if not match:
                break
            value, stop = _read_template(body, match.end())
            values[match.group(1)] = value
            position = stop + 1
        for block in _EXPORT_RE.findall(body):
            for item in block.split(","):
                item = item.strip()
                if not item:
                    continue
                parts = [part.strip() for part in item.split(" as ")]
                source, key = (parts[0], parts[1]) if len(parts) == 2 else (parts[0], parts[0])
                if source in values and key not in result:
                    result[key] = values[source]
    return result


def apply_fixes(text: str, mapping: dict[str, str], pad_to: int | None = None) -> str:
    """把 mapping 里的译文写回 chunk；``pad_to`` 用于补齐到指定字节数（原地打补丁）。"""
    entries = {entry.key: entry for entry in iter_entries(text)}
    missing = [key for key in mapping if key not in entries]
    if missing:
        raise KeyError(f"语言包里没有这些 key：{missing[:5]}")

    # 从后往前替换，避免前面的改动让后面的下标失效
    ordered = sorted(
        (entries[key] for key in mapping), key=lambda entry: entry.start, reverse=True
    )
    for entry in ordered:
        text = text[: entry.start] + mapping[entry.key] + text[entry.end :]

    if pad_to is not None:
        current = len(text.encode("utf-8"))
        if current > pad_to:
            raise ValueError(f"补丁比原文件长 {current - pad_to} 字节，无法原地替换")
        padding = " " * (pad_to - current)
        anchor = text.rfind("export{")
        if anchor < 0:
            anchor = text.rfind("//# sourceMappingURL")
        if anchor < 0:
            anchor = len(text)
        text = text[:anchor] + padding + text[anchor:]
    return text
