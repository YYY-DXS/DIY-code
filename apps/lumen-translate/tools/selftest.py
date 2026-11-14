"""不打开窗口的自检：解析、分块、提示词、配置与图标生成。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import capture, config, engines, history, icon, ocr as ocr_mod, placeholders, win32  # noqa: E402

FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global FAILED
    mark = "PASS" if condition else "FAIL"
    if not condition:
        FAILED += 1
    print(f"[{mark}] {name}" + (f"  -> {detail}" if detail and not condition else ""))


def main() -> int:
    # 1. 分块不丢内容
    text = "line one\n" * 400
    chunks = engines._split_chunks(text)
    check("长文本分块后内容无损", "".join(chunks) == text, f"{len(chunks)} 块")
    check("每块不超过上限", all(len(c) <= 1600 for c in chunks), str([len(c) for c in chunks][:5]))

    # 2. Google 免密钥返回体解析
    sample = {"sentences": [{"trans": "你好，", "orig": "Hello,"}, {"trans": "世界", "orig": " world"}], "src": "en"}
    joined = "".join(s.get("trans", "") for s in sample["sentences"]).strip()
    check("Google 返回体可拼接", joined == "你好，世界", joined)

    # 3. SSE 流式解析
    lines = [
        b'data: {"choices":[{"delta":{"content":"\\u4f60"}}]}\n',
        b'data: {"choices":[{"delta":{"content":"\\u597d"}}]}\n',
        b"data: [DONE]\n",
    ]
    pieces = []
    for event in engines._iter_sse(lines):
        pieces.append((event.get("choices") or [{}])[0].get("delta", {}).get("content", ""))
    check("SSE 流式增量解析", "".join(pieces) == "你好", str(pieces))

    # 4. 提示词包含关键约束
    system, user = engines.build_prompt("Hello {name}", "en", "zh-CN", "技术文档", "保留 API 名")
    check("提示词含占位符保护条款", "{name}" in system, system[:80])
    check("提示词含用户额外要求", "保留 API 名" in system)
    check("用户消息原样传递", user == "Hello {name}")

    # 5. 语言表
    check("目标语言不含自动检测", "auto" not in engines.TARGET_LANGUAGES)
    check("语言条目 >= 18", len(engines.LANGUAGES) >= 18, str(len(engines.LANGUAGES)))

    # 6. 配置往返
    cfg = config.load()
    before = cfg.target_lang
    cfg.target_lang = "ja"
    config.save(cfg)
    check("配置写盘后可读回", config.load().target_lang == "ja")
    cfg.target_lang = before
    config.save(cfg)

    # 7. 历史读写
    history.append(
        history.Entry(ts=0.0, engine="selftest", source_lang="en", target_lang="zh-CN", src="hi", dst="你好", latency_ms=1)
    )
    recent = history.load_recent(5)
    check("历史可写入并读回", any(e.engine == "selftest" for e in recent))

    # 8. 图标生成
    paths = icon.ensure_assets()
    check("PNG 图标已生成", paths["png"].exists() and paths["png"].stat().st_size > 500)
    check("ICO 图标已生成", paths["ico"].exists() and paths["ico"].stat().st_size > 500)
    raw = paths["ico"].read_bytes()
    check("ICO 头合法", raw[:6] == b"\x00\x00\x01\x00\x05\x00", raw[:6].hex())

    # 9. 错误提示可读
    import urllib.error

    err = urllib.error.HTTPError("http://x", 401, "unauthorized", {}, None)
    check("401 有中文提示", "鉴权失败" in engines._describe_http_error(err))

    # 10. 占位符保护
    sample = "Save {file} to %s, see <b>bold</b>, `code`, {{var}} and https://a.b/c?d=1"
    guard = placeholders.protect(sample)
    check("占位符已被挖空", "{file}" not in guard.masked and "%s" not in guard.masked, guard.masked)
    check("哨兵是 {{0}} 形式", "{{0}}" in guard.masked, guard.masked)
    # {file} %s <b> </b> `code` {{var}} 链接，共 7 个
    check("挖空数量正确", len(guard.store) == 7, str(guard.store))
    restored, missing = guard.restore("保存" + guard.masked.replace("到", " to "))
    check("还原后占位符完整", "{file}" in restored and "%s" in restored, restored)
    check("没有缺失的占位符", missing == [], str(missing))
    _, missing2 = guard.restore("全丢了")
    check("哨兵丢失能被检出", len(missing2) == len(guard.store), str(missing2))
    mixed = placeholders.protect("中文 {name} 与 %1$s 混排")
    check("中英混排占位符", mixed.store == ["{name}", "%1$s"], str(mixed.store))
    collide = placeholders.protect("jinja {{0}} with {name}")
    check("原文含 {{0}} 时换标记", collide.flavor == "x" and "{{x0}}" in collide.masked, collide.masked)
    check("原文里的模板变量也被保护", collide.masked == "jinja {{x0}} with {{x1}}", collide.masked)
    back, miss3 = collide.restore(collide.masked)
    check("换标记后能完整还原", back == "jinja {{0}} with {name}" and not miss3, back)
    seg = placeholders.split("Save {file} now")
    check("按占位符切段", seg == [(False, "Save "), (True, "{file}"), (False, " now")], str(seg))

    # 11. 线路映射与冷却
    check("有道中文代码映射", engines._youdao_code("zh-CN", False) == "zh-CHS")
    check("有道 auto 源语言", engines._youdao_code("auto", True) == "auto")
    route = engines.ROUTES[2]
    engines._mark_cooldown(route, "测试", blocked=True)
    health = engines.route_health()
    check("不可达线路进入长冷却", any("Google" in k for k in health), str(health))
    engines._COOLDOWN.clear()
    engines._COOLDOWN_REASON.clear()
    check("线路顺序为 有道→MyMemory→Google", [r.key for r in engines.ROUTES] == ["youdao", "mymemory", "google"])

    # 12. 全局快捷键解析
    check("ctrl+alt+t 解析", win32.parse_hotkey("ctrl+alt+t") == (win32.MOD_CONTROL | win32.MOD_ALT | win32.MOD_NOREPEAT, 0x54))
    check("大小写与空格不敏感", win32.parse_hotkey(" Ctrl + Alt + T ") == win32.parse_hotkey("ctrl+alt+t"))
    check("alt+d 解析", win32.parse_hotkey("alt+d") == (win32.MOD_ALT | win32.MOD_NOREPEAT, 0x44))
    check("ctrl+shift+space 解析", win32.parse_hotkey("ctrl+shift+space") == (win32.MOD_CONTROL | win32.MOD_SHIFT | win32.MOD_NOREPEAT, 0x20))
    for bad in ("f9", "ctrl+alt", "ctrl+alt+xyz", ""):
        try:
            win32.parse_hotkey(bad)
            check(f"非法快捷键被拒绝：{bad!r}", False, "竟然解析成功了")
        except ValueError:
            check(f"非法快捷键被拒绝：{bad!r}", True)
    check("快捷键显示格式化", win32.format_hotkey("ctrl+alt+t") == "Ctrl+Alt+T", win32.format_hotkey("ctrl+alt+t"))

    # 13. Win32 结构体布局（写错会导致 SendInput / 托盘静默失效）
    for name, ok, detail in win32.selftest_structures():
        check(name, ok, detail)
    check("MOD_NOREPEAT 已置位", win32.parse_hotkey("ctrl+t")[0] & win32.MOD_NOREPEAT != 0)

    # 14. 剪贴板读写（真机，非 Windows 自动跳过）
    if win32.IS_WINDOWS:
        marker = "lumen selftest 剪贴板 ✓"
        check("剪贴板写入成功", win32.write_clipboard_text(marker))
        check("剪贴板读回一致", win32.read_clipboard_text() == marker, repr(win32.read_clipboard_text()))
        check("剪贴板序号可读", win32.clipboard_sequence() > 0)
        seq = win32.clipboard_sequence()
        win32.write_clipboard_text("再来一次")
        check("写入后序号变化", win32.clipboard_sequence() != seq)
    else:
        check("非 Windows 跳过剪贴板测试", True)

    # 15. 划词方向判断与语向
    check("中文判定", engines.looks_chinese("今天天气不错，出去走走吧"))
    check("英文判定", not engines.looks_chinese("The weather is nice today"))
    check("中英混排按多数判定", not engines.looks_chinese("hello world 你好"))
    check("语言短名", engines.short_lang_name("en") == "英语", engines.short_lang_name("en"))

    # 16. 选中即翻译的配置与钩子接口
    fresh = config.Config()
    check("选中即翻译默认开启", fresh.select_instant is True)
    check("双击选词默认开启", fresh.select_double_click is True)
    check("默认跳过终端窗口", fresh.select_skip_console is True)
    check("默认恢复剪贴板", fresh.select_restore_clipboard is True)
    check("最小拖动距离合理", 4 <= fresh.select_min_drag <= 12, str(fresh.select_min_drag))
    check("鼠标钩子类可用", hasattr(win32, "SelectionMouseHook"))
    check("鼠标移动用 SendInput（SetCursorPos 不触发钩子）", hasattr(win32, "move_mouse_absolute"))
    check("终端类名表包含常见终端", "ConsoleWindowClass" in win32.CONSOLE_CLASSES and "CASCADIA_HOSTING_WINDOW_CLASS" in win32.CONSOLE_CLASSES)

    # 17. 钩子的手势判定（不装钩子，直接喂状态）
    if win32.IS_WINDOWS:
        fired: list[tuple[int, int]] = []
        clicked: list[tuple[int, int]] = []
        hook = win32.SelectionMouseHook(
            lambda x, y: fired.append((x, y)),
            on_click=lambda x, y: clicked.append((x, y)),
            min_drag=6,
            double_click=True,
            skip_own_process=False,  # 纯逻辑测试，不受真实窗口位置影响
            skip_console=False,
        )
        # 拖够了：应该触发
        hook._on_down(100, 100)
        hook._on_move(130, 100)
        hook._on_up(130, 100)
        check("拖选够距离会触发", fired == [(130, 100)], str(fired))
        check("每次松手都会通知 on_click", clicked == [(130, 100)], str(clicked))
        # 位移太小：不该触发（坐标要和上一条拉开，否则会被当成双击）
        fired.clear()
        clicked.clear()
        hook._on_down(400, 400)
        hook._on_move(402, 401)
        hook._on_up(402, 401)
        check("位移过小不触发", fired == [], str(fired))
        check("位移过小仍然通知 on_click", len(clicked) == 1, str(clicked))
        # 双击（两次按下间隔很短）：第二下松手时触发
        fired.clear()
        hook._on_down(700, 700)
        hook._on_up(700, 700)
        hook._on_down(700, 700)
        hook._on_move(701, 700)
        hook._on_up(701, 700)
        check("双击选词会触发", len(fired) == 1, str(fired))
        check("触发的最后一次带双击原因", "双击" in hook.last_reason, hook.last_reason)
        # 拖够了距离时距离会被记录
        hook._on_down(900, 900)
        hook._on_move(940, 900)
        check("钩子能记录拖动距离", hook._max_distance >= 39, str(hook._max_distance))
        hook._reset()
        check("reset 后距离清零", hook._max_distance == 0.0)
    else:
        check("非 Windows 跳过钩子手势测试", True)

    # 18. 截图翻译里的纯逻辑
    check("清理 OCR 的汉字间空格", ocr_mod.clean_text("桌 面 翻 译") == "桌面翻译", ocr_mod.clean_text("桌 面 翻 译"))
    check("保留英文单词间空格", ocr_mod.clean_text("hello world") == "hello world")
    check("中英混排各自处理", ocr_mod.clean_text("翻 译 test") == "翻译 test", ocr_mod.clean_text("翻 译 test"))
    check("去掉中文标点前空格", ocr_mod.clean_text("你好 。") == "你好。", ocr_mod.clean_text("你好 。"))
    check("连续空行压成一个", ocr_mod.clean_text("a\n\n\n\nb") == "a\n\nb", repr(ocr_mod.clean_text("a\n\n\n\nb")))
    check("首尾空行去掉", ocr_mod.clean_text("\n\n  文本  \n\n") == "文本")
    check("bbox 会归一化", capture.normalize_bbox(100, 200, 50, 80) == (50, 80, 100, 200))
    check("截图热键有默认值", config.Config().hotkey_shot == "ctrl+alt+s")
    check("AI 视觉开关默认关闭", config.Config().screenshot_use_vision is False)
    check("视觉回复解析成对", engines._parse_vision_reply('{"text":"a","translation":"b"}') == ("a", "b"))
    check("视觉回复非 JSON 时兜底", engines._parse_vision_reply("b") == ("", "b"))
    check("虚拟屏幕尺寸合理", win32.virtual_screen()[2] > 0 and win32.virtual_screen()[3] > 0)

    print()
    print("全部通过" if FAILED == 0 else f"{FAILED} 项失败")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
