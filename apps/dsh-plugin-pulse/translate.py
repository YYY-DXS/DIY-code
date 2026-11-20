"""英文→中文翻译（有道公开线路，和 Lumen 译用的是同一个接口）。

- 只翻真正像英文的文本，纯中文/纯数字直接跳过
- 内存 + 磁盘缓存，同一句话只请求一次
- 后台线程执行，UI 线程只读缓存，不阻塞
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

YOUDAO_URL = "https://aidemo.youdao.com/trans"
MYMEMORY_URL = "https://api.mymemory.translated.net/get"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DSH-Panel/2"

_CJK = re.compile(r"[\u3400-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")


def needs_translation(text: str) -> bool:
    text = (text or "").strip()
    if len(text) < 3:
        return False
    latin = len(_LATIN.findall(text))
    if latin < 3:
        return False
    cjk = len(_CJK.findall(text))
    return cjk / max(1, cjk + latin) < 0.45


def _split(text: str, limit: int = 900):
    if len(text) <= limit:
        return [text]
    chunks, rest = [], text
    while len(rest) > limit:
        cut = rest.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = rest.rfind("。", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip()
    if rest:
        chunks.append(rest)
    return chunks


class Translator:
    def __init__(self, cache_path=None, max_entries: int = 3000):
        self.cache_path = str(cache_path) if cache_path else None
        self.max_entries = max_entries
        self.lock = threading.Lock()
        self.cache: dict[str, str] = {}
        self.pending: set[str] = set()
        self.dirty = False
        self.load()

    # ---------------------------------------------------------- 缓存
    def load(self):
        if not self.cache_path:
            return
        try:
            with open(self.cache_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self.cache = {k: v for k, v in data.items() if isinstance(v, str) and v}
        except Exception:
            self.cache = {}

    def save(self):
        if not self.cache_path or not self.dirty:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.cache, fh, ensure_ascii=False)
            os.replace(tmp, self.cache_path)
            self.dirty = False
        except Exception:
            pass

    def get(self, text: str) -> str:
        with self.lock:
            return self.cache.get((text or "").strip(), "")

    def translate_many(self, texts, workers: int = 3):
        """同步批量翻译（给 Web 面板的 /api/translate 用）。"""
        from concurrent.futures import ThreadPoolExecutor

        values = [str(t or "") for t in (texts or [])]
        results = list(values)
        todo = []
        for value in values:
            text = value.strip()
            if not text or not needs_translation(text):
                continue
            hit = self.get(text)
            if hit:
                continue
            if text not in todo:
                todo.append(text)

        if todo:
            with ThreadPoolExecutor(max_workers=max(1, min(workers, len(todo)))) as pool:
                for text, translated in zip(todo, pool.map(self._translate, todo)):
                    if translated:
                        with self.lock:
                            self.cache[text] = translated
                        self.dirty = True
            self.save()

        for index, value in enumerate(values):
            text = value.strip()
            hit = self.get(text)
            if hit:
                results[index] = hit
        return results

    # ---------------------------------------------------------- 请求
    def request(self, text: str, on_done=None):
        """后台翻译一段文本；完成后调用 on_done()（在工作线程里）。"""
        text = (text or "").strip()
        if not text or not needs_translation(text):
            return
        with self.lock:
            if text in self.cache or text in self.pending:
                return
            self.pending.add(text)

        def worker():
            try:
                translated = self._translate(text)
                if translated:
                    with self.lock:
                        self.cache[text] = translated
                        self.dirty = True
                        while len(self.cache) > self.max_entries:
                            self.cache.pop(next(iter(self.cache)), None)
                    self.save()
            finally:
                with self.lock:
                    self.pending.discard(text)
                if on_done:
                    try:
                        on_done()
                    except Exception:
                        pass

        threading.Thread(target=worker, daemon=True).start()

    def _translate(self, text: str) -> str:
        parts = []
        for chunk in _split(text):
            piece = self._youdao(chunk) or self._mymemory(chunk)
            if not piece:
                return ""
            parts.append(piece)
        return "".join(parts).strip()

    def _post(self, data: dict, timeout: int = 12):
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(
            YOUDAO_URL,
            data=body,
            headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    def _youdao(self, text: str) -> str:
        for attempt in (1, 2):
            try:
                data = self._post({"q": text, "from": "auto", "to": "zh-CHS"})
                code = str(data.get("errorCode", "")).strip()
                if code in ("0", ""):
                    return "".join(data.get("translation") or []).strip()
                if code in ("411", "429") and attempt == 1:
                    time.sleep(0.9)
                    continue
                return ""
            except Exception:
                if attempt == 1:
                    time.sleep(0.4)
        return ""

    def _mymemory(self, text: str) -> str:
        try:
            query = urllib.parse.urlencode({"q": text, "langpair": "Autodetect|zh-CN"})
            req = urllib.request.Request(MYMEMORY_URL + "?" + query, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            translated = str((data.get("responseData") or {}).get("translatedText") or "").strip()
            if re.search(r"MYMEMORY WARNING|QUERY LENGTH LIMIT|INVALID (SOURCE|LANGUAGE)", translated, re.I):
                return ""
            return translated
        except Exception:
            return ""
