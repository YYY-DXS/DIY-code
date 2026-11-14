"""格式适配层：从各种资源文件里提取待翻译文本，并把译文手术式写回去。

每个适配器只做两件事：
  * ``extract(path)`` -> [Unit]：拿到「文本 + 位置(key)」。
  * ``apply(path, mapping, out_path)``：按位置替换，文件其余部分一个字节都不动。

目前支持：json / po(gettext) / ini|cfg|lang|properties / Android strings.xml / .resx
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import locale_chunk


@dataclass
class Unit:
    file: str
    format: str
    key: str
    source: str
    line: int | None = None
    meta: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# 过滤规则：默认跳过明显不该翻译的东西，`--include-all` 可以全都要
# --------------------------------------------------------------------------- #

_SKIP_PATTERNS = [
    re.compile(r"^(?:https?|ftp|mailto|file)://", re.I),
    re.compile(r"^[\w.+-]+@[\w-]+\.[\w.]+$"),
    re.compile(r"^[A-Za-z]:\\"),  # Windows 路径
    re.compile(r"^\.?/?[\w./-]+\.(?:png|jpe?g|gif|svg|ico|json|ini|xml|dll|exe|so|dylib|zip|log)$", re.I),
    re.compile(r"^#[0-9A-Fa-f]{3,8}$"),  # 颜色
    re.compile(r"^[A-Za-z0-9_]*_[A-Za-z0-9_]*$"),  # 带下划线的标识符
    re.compile(r"^(?:true|false|null)$", re.I),  # 配置里的布尔值
]


def is_translatable(text: str, include_all: bool = False) -> bool:
    if include_all:
        return bool(text.strip())
    if not text.strip():
        return False
    if not any(ch.isalpha() for ch in text):
        return False  # 纯数字 / 纯符号 / 占位符
    for pattern in _SKIP_PATTERNS:
        if pattern.match(text.strip()):
            return False
    return True


# --------------------------------------------------------------------------- #
# JSON：支持嵌套对象、数组，位置用 JSON Pointer（/menu/file/open）
# --------------------------------------------------------------------------- #

def _ptr_escape(part: str) -> str:
    return str(part).replace("~", "~0").replace("/", "~1")


def _ptr_unescape(part: str) -> str:
    return part.replace("~1", "/").replace("~0", "~")


def extract_json(path: Path, include_all: bool = False) -> list[Unit]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    units: list[Unit] = []

    def walk(node, pointer: str) -> None:
        if isinstance(node, str):
            if is_translatable(node, include_all):
                units.append(Unit(str(path), "json", pointer or "/", node))
        elif isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{pointer}/{_ptr_escape(key)}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{pointer}/{index}")

    walk(data, "")
    return units


def apply_json(path: Path, mapping: dict[str, str], out_path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    for pointer, text in mapping.items():
        if pointer in ("", "/"):
            data = text
            continue
        parts = [_ptr_unescape(p) for p in pointer.strip("/").split("/")]
        node = data
        for part in parts[:-1]:
            node = node[int(part)] if isinstance(node, list) else node[part]
        last = parts[-1]
        if isinstance(node, list):
            node[int(last)] = text
        else:
            node[last] = text
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# gettext .po / .pot
# --------------------------------------------------------------------------- #

_PO_FIELD_RE = re.compile(r'^(msgid_plural|msgid|msgstr(?:\[\d+\])?)\s+(".*")\s*$')


def _po_unquote(literal: str) -> str:
    body = literal.strip()
    if body.startswith('"') and body.endswith('"'):
        body = body[1:-1]
    return (
        body.replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .replace("\\\\", "\\")
    )


def _po_quote(text: str) -> str:
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _parse_po(text: str) -> list[dict]:
    entries: list[dict] = []
    current: dict | None = None
    field_name: str | None = None

    def new_entry() -> dict:
        return {"fields": {}, "lines": {}, "comments": [], "other": []}

    for index, raw in enumerate(text.splitlines()):
        stripped = raw.strip()
        if stripped == "":
            if current is not None:
                entries.append(current)
                current, field_name = None, None
            continue
        if stripped.startswith("#"):
            if current is None:
                current = new_entry()
            current["comments"].append(index)
            field_name = None
            continue
        match = _PO_FIELD_RE.match(stripped)
        if match:
            if current is None:
                current = new_entry()
            name, literal = match.group(1), match.group(2)
            current["fields"].setdefault(name, []).append(_po_unquote(literal))
            current["lines"].setdefault(name, []).append(index)
            field_name = name
            continue
        if stripped.startswith('"'):
            if current is None or field_name is None:
                continue
            current["fields"][field_name].append(_po_unquote(stripped))
            current["lines"][field_name].append(index)
            continue
        if current is None:
            current = new_entry()
        current["other"].append(index)

    if current is not None:
        entries.append(current)
    return entries


def extract_po(path: Path, include_all: bool = False) -> list[Unit]:
    text = path.read_text(encoding="utf-8-sig")
    units: list[Unit] = []
    for order, entry in enumerate(_parse_po(text)):
        msgid = "".join(entry["fields"].get("msgid", []))
        if not msgid.strip():
            continue  # po 头部
        if not is_translatable(msgid, include_all):
            continue
        lines = entry["lines"].get("msgid", [])
        plural = "".join(entry["fields"].get("msgid_plural", []))
        plural_forms = sorted(k for k in entry["fields"] if k.startswith("msgstr["))
        units.append(
            Unit(
                str(path),
                "po",
                f"po#{order}",
                msgid,
                line=(lines[0] + 1) if lines else None,
                meta={
                    "plural": plural,
                    "plural_forms": len(plural_forms),
                    "msgstr": "".join(entry["fields"].get("msgstr", [])),
                },
            )
        )
    return units


def apply_po(path: Path, mapping: dict[str, str], out_path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    entries = _parse_po(text)
    notes: list[str] = []
    replacements: list[tuple[int, int, list[str]]] = []

    for order, entry in enumerate(entries):
        key = f"po#{order}"
        if key not in mapping:
            continue
        target = mapping[key]
        if "msgid_plural" in entry["fields"]:
            forms = [k for k in sorted(entry["fields"]) if k.startswith("msgstr[")]
            if not forms:
                continue
            parts = [p.strip() for p in target.split("|")]
            if len(parts) == 1:
                notes.append(
                    f"{path.name}:{key} 复数条目只填了 1 种形式，其余 msgstr[n] 保持原文"
                )
            while len(parts) < len(forms):
                parts.append(parts[-1])
            for name, value in zip(forms, parts):
                start, end = _contiguous(entry["lines"][name])
                replacements.append((start, end, [f"{name} {_po_quote(value)}"]))
        else:
            names = [k for k in entry["fields"] if k == "msgstr"]
            name = names[0] if names else "msgstr"
            if name in entry["lines"]:
                start, end = _contiguous(entry["lines"][name])
            else:
                # 原来没有 msgstr（例如 .pot 模板），插在 msgid 之后
                msgid_lines = entry["lines"].get("msgid", [0])
                start = end = _contiguous(msgid_lines)[1]
            replacements.append((start, end, [f"msgstr {_po_quote(target)}"]))

    for start, end, new_lines in sorted(replacements, reverse=True):
        lines[start:end] = new_lines

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return notes


def _contiguous(indices: list[int]) -> tuple[int, int]:
    return min(indices), max(indices) + 1


# --------------------------------------------------------------------------- #
# ini / cfg / lang / properties
# --------------------------------------------------------------------------- #

_KV_RE = re.compile(r"^(?P<lead>\s*)(?P<key>[A-Za-z0-9_.\-\[\]]+)(?P<sep>\s*[=:]\s*)(?P<value>.*)$")
_SECTION_RE = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")


def _unescape_java(text: str) -> str:
    def _u(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 16))

    text = re.sub(r"\\u([0-9A-Fa-f]{4})", _u, text)
    return (
        text.replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\r", "\r")
        .replace("\\=", "=")
        .replace("\\:", ":")
        .replace("\\\\", "\\")
    )


def _escape_java(text: str, ascii_only: bool) -> str:
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04X}")
        elif ascii_only and ord(ch) > 0x7E:
            if ord(ch) <= 0xFFFF:
                out.append(f"\\u{ord(ch):04X}")
            else:
                # .properties 用 UTF-16 代理对表示增补平面字符
                value = ord(ch) - 0x10000
                out.append(f"\\u{0xD800 + (value >> 10):04X}\\u{0xDC00 + (value & 0x3FF):04X}")
        else:
            out.append(ch)
    return "".join(out)


def _iter_kv(path: Path):
    """产出 (行号, section, key, value, 原始行)。"""
    section = ""
    for index, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines()):
        section_match = _SECTION_RE.match(line)
        if section_match:
            section = section_match.group("name").strip()
            continue
        if line.strip().startswith(("#", ";", "!")) or not line.strip():
            continue
        match = _KV_RE.match(line)
        if not match:
            continue
        key = match.group("key")
        full_key = f"{section}/{key}" if section else key
        yield index, section, full_key, _unescape_java(match.group("value")), line


def extract_keyvalue(path: Path, include_all: bool = False) -> list[Unit]:
    units: list[Unit] = []
    for index, _section, key, value, _raw in _iter_kv(path):
        if is_translatable(value, include_all):
            units.append(Unit(str(path), "keyvalue", key, value, line=index + 1))
    return units


def apply_keyvalue(
    path: Path, mapping: dict[str, str], out_path: Path, ascii_only: bool | None = None
) -> None:
    raw_text = path.read_text(encoding="utf-8-sig")
    if ascii_only is None:
        ascii_only = "\\u" in raw_text  # 原文件用了 \uXXXX 转义，就跟着用
    lines = raw_text.splitlines()
    section = ""
    for index, line in enumerate(lines):
        section_match = _SECTION_RE.match(line)
        if section_match:
            section = section_match.group("name").strip()
            continue
        match = _KV_RE.match(line)
        if not match:
            continue
        key = match.group("key")
        full_key = f"{section}/{key}" if section else key
        if full_key not in mapping:
            continue
        value = _escape_java(mapping[full_key].strip(), ascii_only)
        lines[index] = f"{match.group('lead')}{key}{match.group('sep')}{value}"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# XML：Android strings.xml 与 .NET .resx —— 正则手术式替换，保留原始排版
# --------------------------------------------------------------------------- #

_ANDROID_RE = re.compile(
    r'(?P<open><string(?=[\s>])[^>]*\bname\s*=\s*"(?P<name>[^"]+)"(?P<attrs>[^>]*)>)'
    r"(?P<body>.*?)(?P<close></string>)",
    re.S,
)
_RESX_RE = re.compile(
    r'(?P<open><data\b[^>]*\bname="(?P<name>[^"]+)"[^>]*>\s*<value>)(?P<body>.*?)(?P<close></value>)',
    re.S,
)


def _xml_text(target: str) -> str:
    target = re.sub(r"&(?!\w+;|#\d+;|#x[0-9A-Fa-f]+;)", "&amp;", target)
    return re.sub(r"<(?![A-Za-z/!?])", "&lt;", target)


def _retext(body: str, target: str) -> str:
    lead = body[: len(body) - len(body.lstrip())]
    trail = body[len(body.rstrip()) :]
    return f"{lead}{_xml_text(target.strip())}{trail}"


def extract_android(path: Path, include_all: bool = False) -> list[Unit]:
    text = path.read_text(encoding="utf-8-sig")
    units: list[Unit] = []
    for match in _ANDROID_RE.finditer(text):
        if 'translatable="false"' in match.group("attrs"):
            continue
        source = match.group("body")
        if is_translatable(source, include_all):
            line = text[: match.start()].count("\n") + 1
            units.append(Unit(str(path), "android_xml", match.group("name"), source, line=line))
    return units


def apply_android(path: Path, mapping: dict[str, str], out_path: Path) -> None:
    text = path.read_text(encoding="utf-8-sig")

    def _sub(match: re.Match[str]) -> str:
        name = match.group("name")
        if name not in mapping:
            return match.group(0)
        return f"{match.group('open')}{_retext(match.group('body'), mapping[name])}{match.group('close')}"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_ANDROID_RE.sub(_sub, text), encoding="utf-8")


def extract_resx(path: Path, include_all: bool = False) -> list[Unit]:
    text = path.read_text(encoding="utf-8-sig")
    units: list[Unit] = []
    for match in _RESX_RE.finditer(text):
        source = match.group("body")
        if is_translatable(source, include_all):
            line = text[: match.start()].count("\n") + 1
            units.append(Unit(str(path), "resx", match.group("name"), source, line=line))
    return units


def apply_resx(path: Path, mapping: dict[str, str], out_path: Path) -> None:
    text = path.read_text(encoding="utf-8-sig")

    def _sub(match: re.Match[str]) -> str:
        name = match.group("name")
        if name not in mapping:
            return match.group(0)
        return f"{match.group('open')}{_retext(match.group('body'), mapping[name])}{match.group('close')}"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_RESX_RE.sub(_sub, text), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 注册表
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Vite / rolldown 语言包 chunk（Electron 应用常见，例如 app.asar 里的 zh-CN-<hash>.js）
# --------------------------------------------------------------------------- #

_MAX_LOCALE_CHUNK_BYTES = 32 * 1024 * 1024


def looks_like_locale_chunk(path: Path) -> bool:
    """靠内容判断是否语言包 chunk，避免把普通 .js 当语言包解析。"""
    try:
        if path.stat().st_size > _MAX_LOCALE_CHUNK_BYTES:
            return False
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    if "export{" not in text or "`" not in text:
        return False
    return len(locale_chunk.iter_entries(text)) >= 5


def extract_locale_chunk(path: Path, include_all: bool = False) -> list[Unit]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    units: list[Unit] = []
    for entry in locale_chunk.iter_entries(text):
        if is_translatable(entry.value, include_all):
            units.append(Unit(str(path), "locale_chunk", entry.key, entry.value))
    return units


def apply_locale_chunk(
    path: Path, mapping: dict[str, str], out_path: Path, pad_to: int | None = None
) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    result = locale_chunk.apply_fixes(text, mapping, pad_to=pad_to)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result, encoding="utf-8")


@dataclass
class Adapter:
    name: str
    extract: object
    apply: object
    extensions: tuple[str, ...]
    needs_content_probe: bool = False


ADAPTERS: dict[str, Adapter] = {
    "json": Adapter("json", extract_json, apply_json, (".json",)),
    "po": Adapter("po", extract_po, apply_po, (".po", ".pot")),
    "keyvalue": Adapter(
        "keyvalue",
        extract_keyvalue,
        apply_keyvalue,
        (".ini", ".cfg", ".lang", ".properties", ".conf", ".strings"),
    ),
    "android_xml": Adapter(
        "android_xml", extract_android, apply_android, (".xml",), needs_content_probe=True
    ),
    "resx": Adapter(
        "resx", extract_resx, apply_resx, (".resx", ".xml"), needs_content_probe=True
    ),
    "locale_chunk": Adapter(
        "locale_chunk", extract_locale_chunk, apply_locale_chunk, (".js",), needs_content_probe=True
    ),
}

SCAN_EXTENSIONS = (".json", ".po", ".pot", ".ini", ".cfg", ".lang", ".properties", ".xml", ".resx")


def detect_format(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in (".json", ".po", ".pot", ".properties", ".resx"):
        return {".pot": "po"}.get(suffix, suffix.lstrip("."))
    if suffix in (".ini", ".cfg", ".lang", ".conf", ".strings"):
        return "keyvalue"
    if suffix == ".xml":
        try:
            head = path.read_text(encoding="utf-8-sig", errors="ignore")[:4096]
        except OSError:
            return None
        if "<string" in head and "name=" in head:
            return "android_xml"
        if "<data" in head and "<value>" in head:
            return "resx"
        return None
    if suffix == ".js" and looks_like_locale_chunk(path):
        return "locale_chunk"
    return None


def extract_file(path: Path, fmt: str | None = None, include_all: bool = False) -> list[Unit]:
    fmt = fmt or detect_format(path)
    if fmt is None or fmt not in ADAPTERS:
        return []
    units = ADAPTERS[fmt].extract(path, include_all)
    for unit in units:
        if fmt == "po" or fmt == "keyvalue":
            unit.meta.setdefault("intact", True)
    return units


def apply_file(
    path: Path, mapping: dict[str, str], out_path: Path, fmt: str | None = None
) -> list[str]:
    fmt = fmt or detect_format(path)
    if fmt is None or fmt not in ADAPTERS:
        return []
    result = ADAPTERS[fmt].apply(path, mapping, out_path)
    return result if isinstance(result, list) else []
