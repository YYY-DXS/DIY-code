"""翻译引擎：免费在线接口（无需注册）与 AI 大模型（OpenAI 兼容协议）。"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from . import placeholders

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LumenTranslate/0.1"

# 语言代码 -> 界面显示名
LANGUAGES: dict[str, str] = {
    "auto": "自动检测",
    "zh-CN": "简体中文",
    "zh-TW": "繁體中文",
    "en": "English 英语",
    "ja": "日本語 日语",
    "ko": "한국어 韩语",
    "fr": "Français 法语",
    "de": "Deutsch 德语",
    "es": "Español 西班牙语",
    "ru": "Русский 俄语",
    "pt": "Português 葡萄牙语",
    "it": "Italiano 意大利语",
    "ar": "العربية 阿拉伯语",
    "th": "ไทย 泰语",
    "vi": "Tiếng Việt 越南语",
    "id": "Bahasa Indonesia 印尼语",
    "nl": "Nederlands 荷兰语",
    "pl": "Polski 波兰语",
    "tr": "Türkçe 土耳其语",
    "hi": "हिन्दी 印地语",
}

TARGET_LANGUAGES = {k: v for k, v in LANGUAGES.items() if k != "auto"}
SOURCE_LANGUAGES = LANGUAGES


def short_lang_name(code: str) -> str:
    """把 'English 英语' 缩成 '英语'，中文名本来就在前面的保持原样。"""

    name = LANGUAGES.get(code, code)
    parts = name.split(" ")
    if len(parts) > 1 and any("\u4e00" <= ch <= "\u9fff" for ch in parts[-1]):
        return parts[-1]
    return name

AI_STYLES = {
    "通用": "自然、通顺、符合目标语言母语者的表达习惯。",
    "直译": "尽量贴近原文结构与字面含义，便于对照阅读。",
    "口语": "像日常聊天那样表达，允许使用口语化短语。",
    "学术": "保持严谨、正式的学术书面语，术语准确。",
    "技术文档": "保留技术术语与代码/命令原文，界面文案简洁。",
    "润色": "不逐字翻译，先理解再用地道的目标语言重写。",
}


class EngineError(RuntimeError):
    """带用户可读提示的翻译失败。"""


@dataclass
class Result:
    text: str
    engine: str
    detected: str = ""
    latency_ms: int = 0


def _opener(proxy: str = "") -> urllib.request.OpenerDirector:
    handlers: list = []
    if proxy.strip():
        handlers.append(urllib.request.ProxyHandler({"http": proxy.strip(), "https": proxy.strip()}))
    return urllib.request.build_opener(*handlers)


def _read_json(url: str, data: bytes | None, headers: dict, timeout: int, opener: urllib.request.OpenerDirector):
    request = urllib.request.Request(url, data=data, headers=headers)
    with opener.open(request, timeout=timeout) as resp:
        payload = resp.read()
    return json.loads(payload.decode("utf-8", "replace"))


def _describe_http_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        hint = {
            400: "请求被拒绝（参数或模型名不对）",
            401: "鉴权失败，API Key 可能无效",
            403: "没有访问权限（Key 或额度问题）",
            404: "接口地址或模型不存在",
            429: "触发限流或余额不足",
            500: "服务端错误",
            502: "网关错误，稍后重试",
            503: "服务不可用",
        }.get(exc.code, "服务返回错误")
        detail = ""
        try:
            body = exc.read().decode("utf-8", "replace")
            parsed = json.loads(body)
            detail = parsed.get("error", {}).get("message") or parsed.get("message") or ""
        except Exception:
            detail = ""
        return f"HTTP {exc.code} · {hint}" + (f"\n{detail[:300]}" if detail else "")
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", exc)
        return f"网络不可达：{reason}"
    if isinstance(exc, TimeoutError):
        return "请求超时，检查网络或在设置里加大超时时间。"
    return f"{type(exc).__name__}: {exc}"


# ------------------------------------------------------------ 免费在线接口
class RateLimited(EngineError):
    """线路被限流，冷却一段时间后再试。"""


class RouteBlocked(EngineError):
    """线路连不通（被墙 / DNS / 超时），长时间内不必再试。"""


def _split_chunks(text: str, limit: int = 1500) -> list[str]:
    """按行切块，尽量不破坏段落结构。"""

    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:  # 超长单行硬切
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks or [text]


# 各线路的语言代码差异
_YOUDAO_CODES = {
    "zh-CN": "zh-CHS",
    "zh-TW": "zh-CHT",
    "he": "he",
}


def _youdao_code(code: str, is_source: bool) -> str:
    if code in ("auto", ""):
        return "auto" if is_source else "zh-CHS"
    return _YOUDAO_CODES.get(code, code)


def youdao_free(
    text: str,
    src: str,
    dst: str,
    timeout: int = 12,
    proxy: str = "",
    cancel: threading.Event | None = None,
) -> tuple[str, str]:
    """有道公开演示接口：国内直连、速度快，但有限流。"""

    opener = _opener(proxy)
    parts: list[str] = []
    detected = ""
    for chunk in _split_chunks(text, 900):
        if cancel is not None and cancel.is_set():
            raise EngineError("已取消")
        body = urllib.parse.urlencode(
            {"q": chunk, "from": _youdao_code(src, True), "to": _youdao_code(dst, False)}
        ).encode()
        data = _read_json(
            "https://aidemo.youdao.com/trans",
            body,
            {"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"},
            timeout,
            opener,
        )
        # 有道有时返回数字 0，有时返回字符串 "0"，统一成字符串比较
        code = str(data.get("errorCode", "")).strip()
        if code in ("0", ""):
            for piece in data.get("translation") or []:
                parts.append(piece)
            direction = data.get("l") or ""
            if isinstance(direction, list):  # 有时是 ["en2zh-CHS"]，有时直接是字符串
                direction = direction[0] if direction else ""
            if "2" in direction:
                found = direction.split("2")[0]
                detected = detected or {"zh-CHS": "zh-CN", "zh-CHT": "zh-TW"}.get(found, found)
        elif code in ("411", "429"):
            raise RateLimited(f"有道线路限流（errorCode={code}）")
        elif code == "103":
            raise RouteBlocked("有道线路限制了单次文本长度")
        else:
            raise EngineError(f"有道线路返回 errorCode={code} {data.get('msg') or ''}".strip())
    result = "".join(parts).strip()
    if not result:
        raise EngineError("有道线路返回了空结果")
    return result, detected


_MYMEMORY_BAD = ("INVALID SOURCE LANGUAGE", "INVALID LANGUAGE PAIR", "MYMEMORY WARNING", "QUERY LENGTH LIMIT", "AUTO' IS")


def mymemory_free(
    text: str,
    src: str,
    dst: str,
    timeout: int = 15,
    proxy: str = "",
    cancel: threading.Event | None = None,
) -> tuple[str, str]:
    """MyMemory 免费接口，单次 500 字节，作为第二线路。"""

    opener = _opener(proxy)
    source = "Autodetect" if src in ("", "auto") else src
    chunks = _split_chunks(text, 450)

    def one(chunk: str) -> str:
        if cancel is not None and cancel.is_set():
            raise EngineError("已取消")
        query = urllib.parse.urlencode({"q": chunk, "langpair": f"{source}|{dst}"})
        url = f"https://api.mymemory.translated.net/get?{query}"
        data = _read_json(url, None, {"User-Agent": UA}, timeout, opener)
        status = data.get("responseStatus")
        translated = ((data.get("responseData") or {}).get("translatedText") or "").strip()
        if status == 403 or any(bad in translated.upper() for bad in _MYMEMORY_BAD):
            raise RateLimited("MyMemory 拒绝了这个语向或已限额")
        if status == 429:
            raise RateLimited("MyMemory 触发限流")
        if not translated:
            raise EngineError("MyMemory 返回了空结果")
        return translated

    if len(chunks) == 1:
        parts = [one(chunks[0])]
    else:  # 分块并发，长文本不至于太慢
        with ThreadPoolExecutor(max_workers=min(3, len(chunks))) as pool:
            parts = list(pool.map(one, chunks))
    return "\n".join(parts).strip(), ("" if source == "Autodetect" else src)


def google_free(
    text: str,
    src: str,
    dst: str,
    timeout: int = 8,
    proxy: str = "",
    cancel: threading.Event | None = None,
) -> tuple[str, str]:
    """translate.googleapis.com 免密钥端点：国外 / 有代理时最快，国内通常被墙。"""

    opener = _opener(proxy)
    parts: list[str] = []
    detected = ""
    for chunk in _split_chunks(text, 1500):
        if cancel is not None and cancel.is_set():
            raise EngineError("已取消")
        query = urllib.parse.urlencode(
            {"client": "gtx", "sl": src or "auto", "tl": dst, "dt": "t", "dj": "1", "q": chunk}
        )
        url = f"https://translate.googleapis.com/translate_a/single?{query}"
        try:
            data = _read_json(url, None, {"User-Agent": UA}, timeout, opener)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise RateLimited("Google 线路限流") from exc
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RouteBlocked(f"Google 线路不可达（{getattr(exc, 'reason', exc)}）") from exc
        detected = detected or data.get("src", "")
        for sentence in data.get("sentences", []):
            parts.append(sentence.get("trans", ""))
    result = "".join(parts).strip()
    if not result:
        raise EngineError("Google 线路返回了空结果")
    return result, detected


@dataclass(frozen=True)
class Route:
    key: str
    label: str
    fn: Callable
    cooldown: int  # 限流后的冷却秒数


ROUTES: tuple[Route, ...] = (
    Route("youdao", "有道线路", youdao_free, 60),
    Route("mymemory", "MyMemory 线路", mymemory_free, 120),
    Route("google", "Google 线路", google_free, 900),
)

# 线路健康状态：key -> 冷却截止时间戳
_COOLDOWN: dict[str, float] = {}
_COOLDOWN_REASON: dict[str, str] = {}


def route_health() -> dict[str, str]:
    """给 UI 用：哪些线路正在冷却。"""

    now = time.time()
    out: dict[str, str] = {}
    for route in ROUTES:
        until = _COOLDOWN.get(route.key, 0.0)
        if until > now:
            out[route.label] = f"冷却中 {int(until - now)}s（{_COOLDOWN_REASON.get(route.key, '')}）"
    return out


def _mark_cooldown(route: Route, reason: str, blocked: bool = False) -> None:
    seconds = route.cooldown * (6 if blocked else 1)
    _COOLDOWN[route.key] = time.time() + seconds
    _COOLDOWN_REASON[route.key] = reason


def _translate_by_segments(
    route: Route,
    text: str,
    src: str,
    dst: str,
    timeout: int,
    proxy: str,
    cancel: threading.Event | None,
) -> str | None:
    """哨兵被吃掉时的兜底：把占位符两边的文字分开翻译再拼回。

    片段太多就不做了（请求数会爆），返回 None 交给上层决定。
    """

    pieces = placeholders.split(text)
    texts = [p for is_ph, p in pieces if not is_ph and p.strip()]
    if not texts or len(texts) > 6:
        return None
    out: list[str] = []
    for is_ph, piece in pieces:
        if is_ph or not piece.strip():
            out.append(piece)
            continue
        translated, _ = route.fn(piece, src, dst, timeout, proxy, cancel)
        out.append(translated)
    return "".join(out)


class OnlineEngine:
    """有道 → MyMemory → Google 依次尝试，失败的线路进入冷却，避免每次都白等超时。"""

    name = "在线翻译"
    _cache: "OrderedDict[tuple[str, str, str], tuple[str, str]]" = OrderedDict()
    _cache_limit = 300

    def __init__(self, timeout: int = 15, proxy: str = ""):
        self.timeout = timeout
        self.proxy = proxy

    def translate(
        self,
        text: str,
        src: str,
        dst: str,
        cancel: threading.Event | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> Result:
        started = time.perf_counter()
        guard = placeholders.protect(text)
        masked = guard.masked
        cache_key = (text, src, dst)
        cached = self._cache.get(cache_key)
        if cached:
            self._cache.move_to_end(cache_key)
            if on_delta:
                on_delta(cached[0])
            return Result(text=cached[0], engine=f"{cached[1]} · 缓存", detected=cached[2], latency_ms=0)

        errors: list[str] = []
        now = time.time()
        for route in ROUTES:
            if _COOLDOWN.get(route.key, 0.0) > now:
                errors.append(f"{route.label}：冷却中，跳过")
                continue
            try:
                translated, detected = route.fn(masked, src, dst, self.timeout, self.proxy, cancel)
            except EngineError as exc:
                if not isinstance(exc, (RateLimited, RouteBlocked)):
                    raise
                _mark_cooldown(route, str(exc), blocked=isinstance(exc, RouteBlocked))
                errors.append(f"{route.label}：{exc}")
                continue
            except Exception as exc:
                errors.append(f"{route.label}：{_describe_http_error(exc)}")
                continue

            restored, missing = guard.restore(translated)
            if missing:
                # 标记被翻译器吃掉：先试按占位符切段翻译，保证占位符一个不少
                try:
                    segmented = _translate_by_segments(route, text, src, dst, self.timeout, self.proxy, cancel)
                except Exception:
                    segmented = None
                if segmented:
                    restored = segmented
                else:
                    # 片段太多或者切段也失败，退到未保护版本，至少保住译文
                    try:
                        retry, detected = route.fn(text, src, dst, self.timeout, self.proxy, cancel)
                        restored = guard.strip(retry)
                    except Exception:
                        restored = guard.strip(restored)
            result_text = restored.strip()
            if on_delta:
                on_delta(result_text)
            self._remember(cache_key, result_text, route.label, detected)
            return Result(
                text=result_text,
                engine=route.label,
                detected=detected,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        raise EngineError("所有在线线路都不通\n" + "\n".join(errors) + "\n（可以在设置里填代理，或切换到 AI 引擎）")

    @classmethod
    def _remember(cls, key: tuple[str, str, str], text: str, label: str, detected: str) -> None:
        cls._cache[key] = (text, label, detected)
        cls._cache.move_to_end(key)
        while len(cls._cache) > cls._cache_limit:
            cls._cache.popitem(last=False)


# ------------------------------------------------------------ AI 大模型
def build_prompt(text: str, src: str, dst: str, style: str, extra: str = "") -> tuple[str, str]:
    src_name = LANGUAGES.get(src, src)
    dst_name = LANGUAGES.get(dst, dst)
    style_hint = AI_STYLES.get(style, AI_STYLES["通用"])
    system = (
        "你是一个专业的翻译引擎，只做翻译，不做解释。\n"
        f"目标语言：{dst_name}。\n"
        f"翻译风格：{style_hint}\n"
        "硬性要求：\n"
        "1. 只输出译文本身，不要加引号、不要加“译文：”之类的前缀、不要写任何说明或注释。\n"
        "2. 严格保留原文的换行、空行、列表、Markdown 标记、代码块、缩进。\n"
        "3. 严格保留占位符与变量原样，例如 {name}、%s、%1$s、{{var}}、<b>、%d、$HOME。\n"
        "4. 数字、时间、单位、专有名词（人名/品牌/型号）保持准确。\n"
        "5. 如果原文只是词或短语，给出最常用的对应译法即可。"
    )
    if extra.strip():
        system += f"\n6. 额外的用户要求：{extra.strip()}"
    if src != "auto":
        system += f"\n源语言是 {src_name}。"
    return system, text


def _iter_sse(lines: Iterable[bytes]) -> Iterable[dict]:
    for raw in lines:
        line = raw.decode("utf-8", "replace").strip()
        if not line or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            return
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


class AIEngine:
    """任意 OpenAI 兼容接口：OpenAI / DeepSeek / 通义 / 智谱 / Ollama ..."""

    name = "AI 翻译"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.2,
        timeout: int = 30,
        proxy: str = "",
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.proxy = proxy

    def _endpoint(self) -> str:
        base = self.base_url
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def translate(
        self,
        text: str,
        src: str,
        dst: str,
        style: str = "通用",
        extra: str = "",
        cancel: threading.Event | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> Result:
        if not self.api_key and "localhost" not in self.base_url and "127.0.0.1" not in self.base_url:
            raise EngineError("还没填 AI 的 API Key。打开「设置 → AI 引擎」填写，或设置环境变量 LUMEN_API_KEY。")
        system, user = build_prompt(text, src, dst, style, extra)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "stream": on_delta is not None,
        }
        started = time.perf_counter()
        content = _chat_completions(self, payload, cancel, on_delta)
        return Result(
            text=content,
            engine=f"AI · {self.model}",
            detected=src,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


# ------------------------------------------------------------ 统一入口
def _chat_completions(
    engine: "AIEngine",
    payload: dict,
    cancel: threading.Event | None,
    on_delta: Callable[[str], None] | None,
) -> str:
    """发一次 /chat/completions 并返回助手文本（on_delta 非空时走流式）。"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {engine.api_key}",
        "User-Agent": UA,
    }
    opener = _opener(engine.proxy)
    request = urllib.request.Request(
        engine._endpoint(), data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with opener.open(request, timeout=engine.timeout) as resp:
            if on_delta is None:
                data = json.loads(resp.read().decode("utf-8", "replace"))
                content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            else:
                buffer: list[str] = []
                for event in _iter_sse(resp):
                    if cancel is not None and cancel.is_set():
                        raise EngineError("已取消")
                    delta = (event.get("choices") or [{}])[0].get("delta", {})
                    piece = delta.get("content")
                    if piece:
                        buffer.append(piece)
                        on_delta("".join(buffer))
                content = "".join(buffer)
    except EngineError:
        raise
    except Exception as exc:
        raise EngineError(_describe_http_error(exc)) from exc

    content = (content or "").strip()
    if not content:
        raise EngineError("模型返回了空结果，换个模型或缩短原文再试。")
    return content


# ------------------------------------------------------------ 截图（视觉）翻译
VISION_PROMPT = (
    "你是一个截图 OCR + 翻译引擎。用户会给你一张屏幕截图。\n"
    "第一步：识别图里所有可见的文字（忽略纯图标、按钮形状、装饰线条）。\n"
    "第二步：把这些文字翻译成 {target}。\n"
    "硬性要求：\n"
    "1. 只输出 JSON，格式为 {{\"text\": 识别到的原文, \"translation\": 译文}}，不要任何解释、不要代码块。\n"
    "2. 保留原本的换行和先后顺序；同一行不要拆开。\n"
    "3. 如果原文已经是{target}，translation 原样重复 text。\n"
    "4. 不要翻译界面上的单个字母/符号碎片，那多半是图标。"
)


def _parse_vision_reply(raw: str) -> tuple[str, str]:
    """从模型回复里取出 (原文, 译文)；不是 JSON 就整体当译文。"""

    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            original = str(data.get("text") or "").strip()
            translated = str(data.get("translation") or "").strip()
            if translated:
                return original, translated
    except json.JSONDecodeError:
        pass
    return "", text


def vision_translate(
    image_path: str,
    dst: str,
    engine: "AIEngine",
    cancel: threading.Event | None = None,
    on_delta: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    """把整张图交给视觉模型：一次调用同时完成识别和翻译。

    返回 (识别到的原文, 译文)。
    """

    import base64

    path = Path(image_path)
    if not path.exists():
        raise EngineError(f"截图文件不见了：{image_path}")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    target = LANGUAGES.get(dst, dst)
    payload = {
        "model": engine.model,
        "messages": [
            {"role": "system", "content": VISION_PROMPT.format(target=target)},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"请识别这张截图里的文字并翻译成{target}。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}},
                ],
            },
        ],
        "temperature": 0.1,
        "stream": on_delta is not None,
    }
    raw = _chat_completions(engine, payload, cancel, on_delta)
    return _parse_vision_reply(raw)


class EngineRunner:
    """按配置挑引擎，给界面层一个统一调用入口（主窗口和划词浮窗都用它）。"""

    def __init__(self, cfg):
        self.cfg = cfg

    @property
    def label(self) -> str:
        return "在线翻译" if self.cfg.engine == "online" else f"AI · {self.cfg.ai_model}"

    def has_api_key(self) -> bool:
        return bool(self.cfg.ai_key_resolved())

    def vision_available(self) -> bool:
        """截图能不能交给 AI 视觉模型处理（要求开了开关、填了地址模型、有 Key）。"""

        if not getattr(self.cfg, "screenshot_use_vision", False):
            return False
        if not self.cfg.ai_base_url.strip() or not self.cfg.ai_model.strip():
            return False
        if self.cfg.ai_key_resolved():
            return True
        base = self.cfg.ai_base_url
        return "localhost" in base or "127.0.0.1" in base

    def vision(self, image_path: str, dst: str, cancel=None, on_delta=None) -> tuple[str, str]:
        engine = AIEngine(
            base_url=self.cfg.ai_base_url,
            api_key=self.cfg.ai_key_resolved(),
            model=self.cfg.ai_model,
            temperature=0.1,
            timeout=int(self.cfg.timeout),
            proxy=self.cfg.proxy,
        )
        return vision_translate(image_path, dst, engine, cancel=cancel, on_delta=on_delta)

    def translate(
        self,
        text: str,
        src: str = "auto",
        dst: str = "zh-CN",
        cancel: threading.Event | None = None,
        on_delta: Callable[[str], None] | None = None,
        style: str | None = None,
    ) -> Result:
        if self.cfg.engine == "ai":
            engine = AIEngine(
                base_url=self.cfg.ai_base_url,
                api_key=self.cfg.ai_key_resolved(),
                model=self.cfg.ai_model,
                temperature=float(self.cfg.ai_temperature),
                timeout=int(self.cfg.timeout),
                proxy=self.cfg.proxy,
            )
            return engine.translate(
                text,
                src,
                dst,
                style=style or self.cfg.ai_style,
                extra=self.cfg.ai_extra_prompt,
                cancel=cancel,
                on_delta=on_delta,
            )
        engine = OnlineEngine(timeout=int(self.cfg.timeout), proxy=self.cfg.proxy)
        return engine.translate(text, src, dst, cancel=cancel, on_delta=on_delta)


def looks_chinese(text: str) -> bool:
    """粗略判断是不是中文，用来决定划词浮窗的翻译方向。"""

    sample = [ch for ch in text[:200] if not ch.isspace()]
    if not sample:
        return False
    cjk = sum(1 for ch in sample if "\u4e00" <= ch <= "\u9fff")
    # 阈值定在 0.5：中英混排（比如一屏英文夹杂几句中文）应该按"其它语言"处理，
    # 译成用户设定的目标语言，而不是反过来。
    return cjk / len(sample) > 0.5


def is_target_language(line: str, dst: str) -> bool:
    """这一行是不是已经是目标语言？（是的话不用翻，省得引擎原样返回）"""

    stripped = line.strip()
    if not stripped:
        return True
    if not any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in stripped):
        return True  # 纯符号/数字，翻它没意义
    if dst.startswith("zh"):
        return looks_chinese(stripped)
    if dst.startswith("en"):
        latin = sum(1 for ch in stripped if ch.isascii() and ch.isalpha())
        cjk = sum(1 for ch in stripped if "\u4e00" <= ch <= "\u9fff")
        return latin > 0 and cjk == 0
    return False


def split_language_blocks(text: str, dst: str) -> list[tuple[bool, str]]:
    """把文本按"要不要翻"切成若干块。

    截图里的内容经常是中英混排，整段丢给引擎会被判成"已经是目标语言"然后原样
    返回。所以按行判断语言，连续的同语言行合成一块。
    """

    blocks: list[list] = []
    for line in text.split("\n"):
        needs = not is_target_language(line, dst)
        if blocks and blocks[-1][0] == needs:
            blocks[-1][1].append(line)
        else:
            blocks.append([needs, [line]])
    return [(needs, "\n".join(lines)) for needs, lines in blocks]
