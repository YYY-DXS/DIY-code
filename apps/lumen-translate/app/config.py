"""配置读写：默认落在程序目录的 data/config.json，也支持环境变量覆盖密钥。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
CONFIG_PATH = DATA_DIR / "config.json"
HISTORY_PATH = DATA_DIR / "history.jsonl"

# 常见服务商预设，方便一键切换
AI_PRESETS: dict[str, dict[str, str]] = {
    "DeepSeek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "OpenAI": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "智谱 GLM": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash"},
    "通义千问": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "Moonshot": {"base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    "本地 Ollama": {"base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:7b"},
    "自定义": {"base_url": "", "model": ""},
}

ENV_KEYS = ("LUMEN_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "HANHUA_API_KEY")


@dataclass
class Config:
    engine: str = "online"            # online | ai
    source_lang: str = "auto"
    target_lang: str = "zh-CN"
    auto_translate: bool = False
    always_on_top: bool = False
    remember_geometry: bool = True

    ai_preset: str = "DeepSeek"
    ai_base_url: str = "https://api.deepseek.com/v1"
    ai_model: str = "deepseek-chat"
    ai_key: str = ""
    ai_temperature: float = 0.2
    ai_style: str = "通用"
    ai_extra_prompt: str = ""

    proxy: str = ""
    timeout: int = 20
    geometry: str = ""

    # 划词 / 全局快捷键 / 托盘
    enable_tray: bool = True
    close_to_tray: bool = True
    hotkeys_enabled: bool = True
    hotkey_select: str = "ctrl+alt+t"
    hotkey_clipboard: str = "ctrl+alt+c"
    hotkey_show: str = "ctrl+alt+l"
    hotkey_shot: str = "ctrl+alt+s"
    ocr_language: str = ""          # 空 = 跟随系统 OCR 语言
    screenshot_use_vision: bool = False   # 截图交给 AI 视觉模型（需模型支持图片）
    auto_select_popup: bool = False
    popup_auto_close: bool = True
    popup_smart_target: bool = True

    # 选中即翻译（鼠标拖选/双击选词后自动弹窗，不用按快捷键）
    select_instant: bool = True
    select_double_click: bool = True
    select_min_drag: int = 6
    select_skip_console: bool = True
    select_restore_clipboard: bool = True

    def ai_key_resolved(self) -> str:
        if self.ai_key.strip():
            return self.ai_key.strip()
        for name in ENV_KEYS:
            value = os.environ.get(name, "").strip()
            if value:
                return value
        return ""

    def key_source(self) -> str:
        if self.ai_key.strip():
            return "配置文件"
        for name in ENV_KEYS:
            if os.environ.get(name, "").strip():
                return f"环境变量 {name}"
        return "未设置"


def load() -> Config:
    cfg = Config()
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        valid = {f.name for f in fields(Config)}
        for key, value in raw.items():
            if key in valid:
                setattr(cfg, key, value)
    return cfg


def save(cfg: Config) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)
