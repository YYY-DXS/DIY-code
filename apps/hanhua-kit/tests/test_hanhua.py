"""hanhua 自测：占位符保护、各格式读写、端到端流水线。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hanhua import formats, locale_chunk, pipeline, placeholders  # noqa: E402
from hanhua.tm import TranslationMemory, load_csv  # noqa: E402
from hanhua.translators import DictTranslator  # noqa: E402

DEMO = ROOT / "demo"


class PlaceholderTests(unittest.TestCase):
    def test_roundtrip_is_identity(self):
        text = "Only {free} free on {drive}, 100% done. <b>x</b> ${env} %1$s"
        masked, tokens = placeholders.protect(text)
        self.assertIn(f"{placeholders.PH_OPEN}{{free}}{placeholders.PH_CLOSE}", masked)
        self.assertEqual(placeholders.restore(masked), text)
        self.assertIn("{free}", tokens)
        self.assertEqual(placeholders.PH_OPEN in text, False)

    def test_no_false_positive_on_plain_percent(self):
        self.assertEqual(placeholders.tokens_of("100% free"), {})

    def test_missing_placeholder_is_error(self):
        problems = placeholders.validate("Delete {0} files", "删除文件")
        self.assertTrue(any(p.startswith("[错误]") for p in problems))

    def test_named_placeholder_can_be_reordered(self):
        source = "Only {free} free on {drive}. Continue?"
        target = "{drive} 上仅剩 {free} 可用空间，是否继续？"
        self.assertEqual(placeholders.validate(source, target), [])

    def test_positional_placeholder_reorder_is_warning(self):
        problems = placeholders.validate("%1$s and %2$s", "%2$s 与 %1$s")
        self.assertTrue(any("顺序" in p for p in problems))

    def test_broken_sentinel_detected(self):
        masked, _ = placeholders.protect("Hello {name}")
        broken = masked.replace(placeholders.PH_CLOSE, "")
        self.assertTrue(placeholders.leftovers(broken))

    def test_extra_placeholder_is_error(self):
        problems = placeholders.validate("Hello {name}", "你好 {name}{0}")
        self.assertTrue(any("多出" in p for p in problems))


class JsonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_extract_and_apply_only_touch_targets(self):
        source = self.tmp / "en.json"
        source.write_text(
            json.dumps({"a": "Hello", "b": {"c": "https://x.com", "d": "World"}}),
            encoding="utf-8",
        )
        units = formats.extract_json(source)
        keys = {u.key for u in units}
        self.assertEqual(keys, {"/a", "/b/d"})  # URL 被过滤

        out = self.tmp / "zh.json"
        formats.apply_json(source, {"/a": "你好", "/b/d": "世界"}, out)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["a"], "你好")
        self.assertEqual(data["b"]["d"], "世界")
        self.assertEqual(data["b"]["c"], "https://x.com")


class PoTests(unittest.TestCase):
    def test_extract_includes_plural(self):
        units = formats.extract_po(DEMO / "source" / "locale" / "messages.po")
        self.assertEqual(len(units), 5)
        plural = [u for u in units if u.meta.get("plural_forms")]
        self.assertEqual(len(plural), 1)
        self.assertEqual(plural[0].meta["plural"], "Delete {count} snapshots")

    def test_apply_writes_singular_and_plural(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        out = tmp / "zh.po"
        mapping = {
            "po#1": "已创建快照",
            "po#5": "删除 {count} 个快照|删除 {count} 个快照",
        }
        formats.apply_po(DEMO / "source" / "locale" / "messages.po", mapping, out)
        text = out.read_text(encoding="utf-8")
        self.assertIn('msgstr "已创建快照"', text)
        self.assertIn('msgstr[0] "删除 {count} 个快照"', text)
        self.assertIn('msgstr[1] "删除 {count} 个快照"', text)
        self.assertIn("Content-Type: text/plain; charset=UTF-8", text)  # 头部原样保留
        self.assertEqual(text.count('msgstr ""'), 4)  # 头部 + 其余 3 个未翻译条目


class KeyValueTests(unittest.TestCase):
    def test_ini_extract_skips_booleans(self):
        units = formats.extract_keyvalue(DEMO / "source" / "config" / "app.ini")
        values = {u.key: u.source for u in units}
        self.assertNotIn("general/version", values)  # 纯版本号不抽
        self.assertNotIn("backup/skip_hidden", values)  # 布尔值不抽
        self.assertEqual(values["general/product.name"], "Nimbus Backup")

    def test_properties_unicode_escape(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        source = tmp / "messages.properties"
        source.write_text("welcome=\\u6b22\\u8fce\nplain=Hello\n", encoding="utf-8")
        units = formats.extract_keyvalue(source)
        self.assertEqual({u.key: u.source for u in units}, {"welcome": "欢迎", "plain": "Hello"})
        out = tmp / "out.properties"
        formats.apply_keyvalue(source, {"plain": "你好"}, out)
        self.assertIn("welcome=\\u6b22\\u8fce", out.read_text(encoding="utf-8"))
        self.assertIn("plain=\\u4F60\\u597D", out.read_text(encoding="utf-8"))


class XmlTests(unittest.TestCase):
    def test_android_extract_skips_untranslatable(self):
        units = formats.extract_android(DEMO / "source" / "res" / "values" / "strings.xml")
        names = {u.key for u in units}
        self.assertIn("welcome_message", names)
        self.assertNotIn("api_endpoint", names)

    def test_android_apply_preserves_layout(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        import xml.etree.ElementTree as ET

        source = DEMO / "source" / "res" / "values" / "strings.xml"
        out = tmp / "strings.xml"
        formats.apply_android(source, {"app_name": "Nimbus 备份", "action_restore": "恢复 <这里>"}, out)
        original = source.read_text(encoding="utf-8").splitlines()
        written = out.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(original), len(written))  # 行数不变，排版未动
        self.assertTrue(any('<string name="app_name">Nimbus 备份</string>' in line for line in written))
        self.assertTrue(any("恢复 &lt;这里>" in line for line in written))  # 尖括号被转义
        self.assertTrue(any('translatable="false"' in line for line in written))
        ET.parse(out)  # 改完仍必须是合法 XML

    def test_resx_extract(self):
        units = formats.extract_resx(DEMO / "source" / "Properties" / "Resources.resx")
        self.assertEqual({u.key for u in units}, {"ConnectionFailed", "Retry", "CopiedItems"})


# 迷你语言包，结构模仿 Vite/rolldown 打出来的 zh-CN chunk
LOCALE_CHUNK = (
    'import{n as e}from"./runtime.js";'
    "var a,b;function f(){return(f=e((()=>{a=`单独字符串`,b=`另一条`})))}"
    "export{a as greeting,b as subtitle};"
    '{"ui.gap":`{days, plural, one {every day} other {every {days} days}}`,'
    '"ui.done":`已经翻译好的文案`,'
    '"ui.a":`第一条`,'
    '"ui.b":`第二条`,'
    '"ui.c":`第三条`}'
    "export{g as gap,g as done};"
)


class LocaleChunkTests(unittest.TestCase):
    def test_parse_finds_dotted_keys(self):
        data = locale_chunk.parse(LOCALE_CHUNK)
        self.assertTrue({"ui.gap", "ui.done", "ui.a", "ui.b", "ui.c"} <= set(data))
        self.assertIn("greeting", data)  # export 形式的独立字符串也能解析
        self.assertIn("every day", data["ui.gap"])

    def test_apply_fixes_keeps_length_and_other_keys(self):
        fix = {"ui.gap": "{days, plural, one {每天} other {每 {days} 天}}"}
        original = LOCALE_CHUNK.encode("utf-8")
        patched = locale_chunk.apply_fixes(LOCALE_CHUNK, fix, pad_to=len(original))
        self.assertEqual(len(patched.encode("utf-8")), len(original))  # 字节数不变，可原地替换
        data = locale_chunk.parse(patched)
        self.assertEqual(data["ui.gap"], fix["ui.gap"])
        self.assertEqual(data["ui.done"], "已经翻译好的文案")  # 其它条目不受影响
        self.assertEqual(len(data), len(locale_chunk.parse(LOCALE_CHUNK)))

    def test_apply_fixes_rejects_unknown_key(self):
        with self.assertRaises(KeyError):
            locale_chunk.apply_fixes(LOCALE_CHUNK, {"nope": "x"})

    def test_apply_fixes_rejects_longer_patch(self):
        with self.assertRaises(ValueError):
            locale_chunk.apply_fixes(LOCALE_CHUNK, {"ui.done": "很长" * 50}, pad_to=len(LOCALE_CHUNK.encode()))

    def test_formats_adapter_roundtrip(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        source = tmp / "zh-CN-0123456789ab.js"
        source.write_text(LOCALE_CHUNK, encoding="utf-8")
        units = formats.extract_locale_chunk(source)
        self.assertTrue({"ui.gap", "ui.done", "ui.a"} <= {u.key for u in units})
        self.assertEqual(formats.detect_format(source), "locale_chunk")
        out = tmp / "patched.js"
        formats.apply_locale_chunk(source, {"ui.done": "已完成"}, out)
        self.assertEqual(locale_chunk.parse(out.read_text(encoding="utf-8"))["ui.done"], "已完成")


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.work_dir = cls.tmp / "work"
        cls.work_dir.mkdir(parents=True)
        cls.work_path = cls.work_dir / "strings.json"
        cls.tm_path = cls.tmp / "tm.sqlite"

        work = pipeline.extract(DEMO / "source", lang="en")

        memory = TranslationMemory(cls.tm_path)
        memory.put_glossary(load_csv(DEMO / "glossary.csv"), "zh-CN")
        translator = DictTranslator.from_memory(memory, "zh-CN")
        cls.stats = pipeline.translate(work, translator, "zh-CN", memory=memory)
        cls.work = work
        cls.work_path.write_text(json.dumps(work, ensure_ascii=False), encoding="utf-8")
        cls.out_dir = cls.tmp / "out"
        cls.apply_result = pipeline.apply_work(work, outdir=cls.out_dir)
        memory.close()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_extract_counts(self):
        files = {unit["file"] for unit in self.work["units"]}
        self.assertEqual(
            files,
            {
                "locales/en.json",
                "config/app.ini",
                "locale/messages.po",
                "res/values/strings.xml",
                "Properties/Resources.resx",
            },
        )
        self.assertGreater(len(self.work["units"]), 35)

    def test_two_entries_need_manual_work(self):
        self.assertEqual(self.stats["invalid"], 0)
        self.assertEqual(self.stats["review"], 2)
        pending = {u["source"] for u in self.work["units"] if u["status"] == "review"}
        self.assertEqual(
            pending, {"Parallel transfers", "Backup failed. Check the log for details."}
        )

    def test_memory_hits_on_second_pass(self):
        # 第一次跑没有记忆库命中（同一批里刚刚写入），第二次重跑应当全部命中
        memory = TranslationMemory(self.tm_path)
        try:
            repeat = pipeline.extract(DEMO / "source", lang="en")
            stats = pipeline.translate(
                repeat, DictTranslator.from_memory(memory, "zh-CN"), "zh-CN", memory=memory
            )
        finally:
            memory.close()
        self.assertEqual(stats["translated"], 0)
        self.assertEqual(stats["tm"], 41)  # 43 条里有 2 条本来就没有译文

    def test_check_has_no_errors(self):
        errors = [p for p in pipeline.check(self.work) if p["level"] == "error"]
        # 只有那两条故意留给人工的条目会报「未翻译」
        self.assertEqual(len(errors), 2, errors)
        self.assertTrue(all(p["message"] == "未翻译" for p in errors))

    def test_applied_json_keeps_placeholders(self):
        data = json.loads((self.out_dir / "locales" / "en.json").read_text(encoding="utf-8"))
        self.assertEqual(data["app"]["name"], "Nimbus 备份")
        self.assertEqual(data["status"]["running"], "正在备份第 {count} 个文件，共 {total} 个……")
        self.assertEqual(data["dialog"]["low_space"], "{drive} 上仅剩 {free} 可用空间，是否继续？")
        self.assertEqual(data["status"]["verify"], "正在校验 <b>快照</b> 完整性")
        self.assertEqual(data["settings"]["parallel"], "Parallel transfers")  # 未译条目保持原文

    def test_applied_po_and_xml(self):
        po_text = (self.out_dir / "locale" / "messages.po").read_text(encoding="utf-8")
        self.assertIn('msgstr "已校验 %s/%s 个数据块"', po_text)
        xml_text = (self.out_dir / "res" / "values" / "strings.xml").read_text(encoding="utf-8")
        self.assertIn("{user}，欢迎回来！", xml_text)
        self.assertIn("&lt;b&gt;%1$s&lt;/b&gt;，共 %2$s 已使用", xml_text)
        resx_text = (self.out_dir / "Properties" / "Resources.resx").read_text(encoding="utf-8")
        self.assertIn("已复制到 {1}，共 {0} 项", resx_text)

    def test_csv_roundtrip(self):
        csv_path = self.tmp / "review.csv"
        pipeline.export_csv(self.work, csv_path)
        self.assertTrue(csv_path.read_bytes().startswith(b"\xef\xbb\xbf"))  # Excel 需要 BOM

        import csv as csv_module

        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv_module.DictReader(handle))
        for row in rows:
            if row["状态"] == "review":
                row["译文"] = "人工补译"
        csv_path.write_text("", encoding="utf-8")
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv_module.DictWriter(handle, fieldnames=pipeline.CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

        work = json.loads(self.work_path.read_text(encoding="utf-8"))
        stats = pipeline.import_csv(work, csv_path)
        self.assertEqual(stats["filled"], 2)
        self.assertTrue(all(u["status"] in ("human", "translated") for u in work["units"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
