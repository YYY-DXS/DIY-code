"""翻译器：离线词典 / OpenAI 兼容接口 / 人工往返。

所有翻译器收到的都是「已打码」的文本（占位符已被哨兵包住），
返回同样带哨兵的译文；还原和校验由流水线统一负责。
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import placeholders
from .tm import TranslationMemory, norm


@dataclass
class Item:
    """一条待翻译单元。"""

    source: str
    masked: str
    file: str = ""
    key: str = ""
    meta: dict = field(default_factory=dict)


class Translator:
    name = "base"
    #: 翻译结果是否需要写回 TM（人工/权威来源为 True）
    trusted = False

    def translate(self, items: list[Item]) -> list[str | None]:
        raise NotImplementedError


class DictTranslator(Translator):
    """离线词典：整句精确命中用 phrase，术语替换用 term（默认关闭）。"""

    name = "dict"
    trusted = True

    def __init__(
        self,
        phrases: dict[str, str] | None = None,
        terms: list[tuple[str, str]] | None = None,
        allow_term_substitution: bool = False,
    ) -> None:
        self.phrases = {norm(k): v for k, v in (phrases or {}).items()}
        self.terms = sorted(terms or [], key=lambda pair: -len(pair[0]))
        self.allow_term_substitution = allow_term_substitution

    @classmethod
    def from_memory(
        cls, memory: TranslationMemory, lang: str, allow_term_substitution: bool = False
    ) -> "DictTranslator":
        rows = memory.glossary(lang)
        phrases = {r["source"]: r["target"] for r in rows if r["kind"] == "phrase"}
        terms = [(r["source"], r["target"]) for r in rows if r["kind"] == "term"]
        return cls(phrases, terms, allow_term_substitution)

    def translate(self, items: list[Item]) -> list[str | None]:
        results: list[str | None] = []
        for item in items:
            hit = self.phrases.get(norm(placeholders.restore(item.masked)))
            if hit is None:
                hit = self.phrases.get(norm(item.masked))
            if hit is not None:
                masked_hit, _ = placeholders.protect(hit)
                results.append(masked_hit)
                continue
            if self.allow_term_substitution:
                results.append(self._substitute(item.masked))
            else:
                results.append(None)
        return results

    def _substitute(self, masked: str) -> str | None:
        text = masked
        hits = 0
        for source, target in self.terms:
            pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(source)}(?![A-Za-z0-9_])", re.I)
            text, count = pattern.subn(target, text)
            hits += count
        return text if hits else None


class OpenAITranslator(Translator):
    """OpenAI 兼容的 /chat/completions 接口（OpenAI、DeepSeek、通义、本地 vLLM 都行）。

    密钥从环境变量读：HANHUA_API_KEY 或 OPENAI_API_KEY。
    """

    name = "openai"
    trusted = True

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
        api_key: str | None = None,
        batch_size: int = 20,
        timeout: int = 90,
        retries: int = 3,
        glossary: list[dict] | None = None,
        target_lang: str = "简体中文",
        app_context: str = "",
        temperature: float = 0.2,
    ) -> None:
        self.model = model
        self.base_url = (base_url or os.environ.get("HANHUA_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("HANHUA_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        self.batch_size = max(1, batch_size)
        self.timeout = timeout
        self.retries = retries
        self.glossary = glossary or []
        self.target_lang = target_lang
        self.app_context = app_context
        self.temperature = temperature
        self.last_error: str | None = None

    def translate(self, items: list[Item]) -> list[str | None]:
        if not self.api_key:
            raise RuntimeError(
                "缺少 API Key：请设置环境变量 HANHUA_API_KEY（或 OPENAI_API_KEY），"
                "或改用 --translator dict / 人工 CSV 流程。"
            )
        results: list[str | None] = []
        for start in range(0, len(items), self.batch_size):
            batch = items[start : start + self.batch_size]
            results.extend(self._translate_batch(batch))
        return results

    def _translate_batch(self, batch: list[Item]) -> list[str | None]:
        payload = [
            {"id": index, "file": item.file, "key": item.key, "text": item.masked}
            for index, item in enumerate(batch)
        ]
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
        }
        for attempt in range(1, self.retries + 1):
            try:
                data = self._post("/chat/completions", body)
                content = data["choices"][0]["message"]["content"]
                parsed = _parse_json_array(content)
                by_id = {}
                for entry in parsed:
                    if isinstance(entry, dict) and "id" in entry:
                        by_id[int(entry["id"])] = entry.get("text")
                    elif isinstance(entry, str):
                        by_id[len(by_id)] = entry
                return [by_id.get(i) for i in range(len(batch))]
            except Exception as exc:  # noqa: BLE001 - 统一降级为「未翻译」
                self.last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.retries:
                    time.sleep(min(2 ** attempt, 10))
        return [None] * len(batch)

    def _system_prompt(self) -> str:
        terms = self._relevant_terms()
        lines = [
            f"你是资深软件本地化译者，把软件界面文本翻译成{self.target_lang}。",
            "要求：",
            "1. 只输出 JSON 数组，形如 [{\"id\":0,\"text\":\"译文\"}]，不要输出解释或 Markdown 代码块。",
            "2. 保留 U+E000 与 U+E001 包裹的占位符片段，原样复制，顺序可调整，内容一个字符都不能改。",
            "3. 术语表优先于你的习惯译法。",
            "4. 保持简洁，符合软件界面用语；不要加句号，不要意译出原文没有的内容。",
            "5. 原文里的换行、空格数量尽量保持。",
        ]
        if self.app_context:
            lines.append(f"应用背景：{self.app_context}")
        if terms:
            lines.append("术语表：")
            lines.extend(f"  {src} -> {dst}" for src, dst in terms)
        return "\n".join(lines)

    def _relevant_terms(self, limit: int = 60) -> list[tuple[str, str]]:
        return [(t["source"], t["target"]) for t in self.glossary[:limit]]

    def _post(self, path: str, body: dict) -> dict:
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


class CsvTranslator(Translator):
    """人工翻译结果：从已有 target 的 CSV 里读，用于「导出 -> 人工填 -> 回灌」。"""

    name = "csv"
    trusted = True

    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = {norm(k): v for k, v in mapping.items()}

    @classmethod
    def from_csv(cls, path: str | Path) -> "CsvTranslator":
        from .tm import load_csv

        rows = load_csv(path)
        return cls({row["source"]: row["target"] for row in rows})

    def translate(self, items: list[Item]) -> list[str | None]:
        results: list[str | None] = []
        for item in items:
            hit = self.mapping.get(norm(placeholders.restore(item.masked)))
            results.append(placeholders.protect(hit)[0] if hit else None)
        return results


def _parse_json_array(content: str) -> list:
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.S)
        if not match:
            raise
        data = json.loads(match.group(0))
    if isinstance(data, dict):
        data = data.get("items") or data.get("results") or []
    return data


def get_translator(name: str, memory: TranslationMemory | None = None, **kwargs) -> Translator:
    name = (name or "dict").lower()
    if name == "dict":
        if memory is None:
            return DictTranslator(kwargs.get("phrases"), kwargs.get("terms"), kwargs.get("allow_term_substitution", False))
        return DictTranslator.from_memory(
            memory, kwargs["lang"], kwargs.get("allow_term_substitution", False)
        )
    if name in ("openai", "llm"):
        return OpenAITranslator(
            model=kwargs.get("model", "gpt-4o-mini"),
            base_url=kwargs.get("base_url"),
            api_key=kwargs.get("api_key"),
            batch_size=kwargs.get("batch_size", 20),
            glossary=kwargs.get("glossary"),
            target_lang=kwargs.get("target_lang", "简体中文"),
            app_context=kwargs.get("app_context", ""),
        )
    if name == "csv":
        if not kwargs.get("csv_path"):
            raise SystemExit("--translator csv 需要同时给出 --csv 译文表路径")
        return CsvTranslator.from_csv(kwargs["csv_path"])
    raise SystemExit(f"未知翻译器：{name}（可用：dict / openai / csv）")
