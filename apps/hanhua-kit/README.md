# hanhua —— 通用软件汉化流水线

把「提取 → 保护 → 翻译 → 校验 → 回写」做成一条可复用的流水线，只依赖 Python 标准库。

## 一、可行性先说清楚

| 目标类型 | 可行度 | 现实做法 |
| --- | --- | --- |
| Electron / Web 类（.json、.js 里的语言包） | 高 | 本工具直接支持，改完即生效 |
| .NET（.resx、附属程序集） | 高 | .resx 本工具直接支持；编译后的 dll 需要 ILSpy/dnSpy 反编译回资源 |
| Qt（.ts / .qm） | 高 | .ts 是 XML，加个适配器即可；.qm 需先 `lconvert` 转 .ts |
| Java / Android（.properties、strings.xml、APK） | 高 | 文本资源直接改；APK 改完需重新签名（v1+v2） |
| gettext（.po/.mo） | 高 | .po 本工具支持，`.mo` 用 `msgfmt` 编译 |
| 游戏（Unity 资源包、Unreal .pak、自研打包格式） | 中 | 先解包（UABEA/quickbms 脚本），导出文本后再用本工具 |
| 加壳 / 加密资源的 exe、dll | 低 | 字符串在二进制段里，长度受限、有校验和；先脱壳+定位资源段才谈得上汉化 |
| 在线校验完整性的程序 | 低 | 改资源会导致签名/哈希校验失败，需要同时处理校验逻辑（有法律与稳定性风险） |

结论：**不存在「一键汉化任意 exe」**，但把「文本提取 + 回写」标准化之后，绝大多数现代软件的汉化都是可批量、可回归、可复用的工程问题。

## 二、这个工具解决什么

1. **占位符安全**：`{0}` `%s` `%1$s` `%(name)s` `${env}` `<b>` `&amp;` `@string/xxx` `\n` 会被包进私用区哨兵 `U+E000…U+E001` 再交给翻译器，翻完还原。哨兵是**内容命名**的，所以中文里把 `{drive}` 提到 `{free}` 前面也不会错位。
2. **翻译记忆库(TM)**：SQLite 存句段，重跑复用、增量更新、不漂移。
3. **术语表**：`Backup/Restore/Snapshot` 之类在全文保持一致。
4. **三种翻译来源**：离线词典（无网也能跑）、OpenAI 兼容接口（OpenAI / DeepSeek / 通义 / 本地 vLLM 都行）、人工 CSV 往返。
5. **手术式回写**：JSON 只改命中的值，ini/po/xml 只改那一行/那一段，其余字节不动，xml 连注释和缩进都保留。
6. **质检闸门**：占位符缺失/多余/顺序、换行数、标签闭合、译文长度溢出、复数形式缺失、未翻译条目 —— 任何错误都能在出成品前拦下来。

## 三、目录

```
hanhua-kit/
├─ hanhua/            # 工具本体
│  ├─ placeholders.py # 占位符保护与校验
│  ├─ formats.py      # json / po / ini|properties / android xml / resx 读写
│  ├─ tm.py           # 翻译记忆库 + 术语表（SQLite）
│  ├─ translators.py  # 离线词典 / OpenAI 兼容 / 人工 CSV
│  ├─ pipeline.py     # 流水线与质检
│  └─ cli.py          # 命令行
├─ demo/source/       # 演示用「待汉化软件」资源（Nimbus Backup）
├─ demo/glossary.csv  # 演示词典（term = 术语，phrase = 整句）
├─ tools/             # 逆向/打包类辅助工具
│  ├─ asar_tool.py    # 读取 Electron app.asar（列目录 / 导出文件）
│  ├─ i18n_gap.py     # 审计自带语言包：条数、漏翻、缺 key
│  ├─ ui_patch.py     # 给 asar 里的语言包打补丁（build/apply/verify）
│  └─ binpeek.py      # 在原生二进制里找内嵌资源
└─ tests/             # 27 个自测
```

## 四、四步跑通

```powershell
$py = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

# 1. 看能抽多少条
& $py -m hanhua scan demo/source

# 2. 提取
& $py -m hanhua extract demo/source -o work/strings.json

# 3. 翻译（离线词典；换成 --translator openai 就是 AI 翻译）
& $py -m hanhua translate work/strings.json --lang zh-CN `
    --glossary demo/glossary.csv --translator dict -o work/strings.zh.json

# 4. 质检 + 回写（默认写到 out/，原文件不动）
& $py -m hanhua check  work/strings.zh.json
& $py -m hanhua apply  work/strings.zh.json -o out
```

人工/精修流程：`export` 出 UTF-8 BOM 的 CSV（Excel 双击不乱码）→ 译者填「译文」列 → `import` 合并 → `apply`。

```powershell
& $py -m hanhua export work/strings.zh.json -o review.csv
#  ……译者填 review.csv 的「译文」列……
& $py -m hanhua import review.csv work/strings.zh.json -o work/strings.human.json
& $py -m hanhua apply  work/strings.human.json -o out
```

## 五、切换到 AI 翻译

工具走的是 OpenAI 兼容协议，所以换个 `--base-url` 就能换服务商，密钥只从环境变量读、不落盘：

```powershell
$env:HANHUA_API_KEY = "sk-..."
& $py -m hanhua translate work/strings.json --translator openai `
    --model gpt-4o-mini --lang zh-CN --glossary demo/glossary.csv `
    --context "Nimbus Backup 是一款定时备份软件，界面偏专业工具风格" `
    -o work/strings.ai.json
```

DeepSeek / 通义 / 本地模型：

```powershell
$env:HANHUA_BASE_URL = "https://api.deepseek.com/v1"
$env:HANHUA_API_KEY  = "sk-..."
& $py -m hanhua translate work/strings.json --translator openai --model deepseek-chat -o work/strings.ai.json
```

模型输出仍然要过同一套占位符校验：不通过就标 `invalid`，不会被写进成品。这就是「AI 翻译 + 机器质检」的价值。

## 六、命令速查

| 命令 | 作用 |
| --- | --- |
| `scan PATH` | 扫描识别到的资源文件与条数 |
| `extract PATH -o work.json` | 提取成工作文件 |
| `translate work.json --translator dict/openai/csv` | 翻译，结果写回工作文件 |
| `check work.json` | 质检，有错误时返回码 1（可挂到 CI） |
| `export work.json -o review.csv` | 导出审校表 |
| `import review.csv work.json -o new.json` | 合并人工译文 |
| `apply work.json -o out` | 回写；`--in-place` 直接改原文件（自动 `.bak`） |
| `memory --lang zh-CN` | 查看记忆库统计 |

## 七、扩展一个新格式

在 [formats.py](hanhua/formats.py) 里加两个函数，注册到 `ADAPTERS` 即可：

```python
def extract_mine(path, include_all=False):   # -> [Unit(file, format, key, source)]
    ...
def apply_mine(path, mapping, out_path):     # mapping: {key: 译文}
    ...

ADAPTERS["mine"] = Adapter("mine", extract_mine, apply_mine, (".mine",))
```

`key` 只要能唯一定位文本就行（JSON Pointer、行号、属性名、XPath 都可以）。

## 八、汉化实战注意事项

- **编码**：源文件可能是 UTF-8 BOM、GBK 或 `\uXXXX` 转义。`.properties` 会自动跟随原有转义风格，其它格式统一写 UTF-8。
- **字体**：界面改成中文后如果显示方块，是程序没内嵌 CJK 字体，需要用字体补丁或替换默认字体。
- **布局**：中文通常比英文短，但按钮/表头是固定宽度，`check` 会提示长度异常的条目。
- **签名与校验**：Windows 程序改完 dll/exe 会破坏数字签名；部分程序启动时校验资源哈希，需要另行处理（也可能触发反作弊/防篡改机制）。
- **合规**：仅对自己拥有或已获授权修改的软件做汉化，遵守原软件的许可协议。

## 九、实战：汉化 Electron 应用自带的语言包

很多现代桌面端（Electron / Chromium 壳）自带多语言包，界面文案不在 exe 里，而在
`resources/app.asar` 内的 `webview/assets/<locale>-<hash>.js`（Vite/rolldown 打包产物）。
本工具链支持这种格式，流程是：审计 → 找漏翻 → 出补丁 → 原地写回。

```powershell
# 1. 看 asar 里有什么（只读）
& $py tools/asar_tool.py stat app.asar
& $py tools/asar_tool.py list app.asar --filter 'webview/assets/zh-CN'

# 2. 审计语言包：条数 / 漏翻 / 缺 key
& $py tools/i18n_gap.py --asar app.asar --locale zh-CN --compare zh-TW,ja-JP --csv gaps.csv

# 3. 按 CSV 出补丁（长度对齐 + node --check 语法校验）
& $py tools/ui_patch.py build --asar app.asar --locale zh-CN --fixes fixes.csv --outdir out/ui-patch

# 4. 写回（需先退出应用；WindowsApps 目录还需要管理员/夺权）
& $py tools/ui_patch.py verify --patch out/ui-patch/patch.json
& $py tools/ui_patch.py apply  --patch out/ui-patch/patch.json
```

补丁是**等字节长替换**，所以 asar 的目录表和偏移都不用动；回滚就是把备份写回同一偏移。

### 本次对 Codex 桌面端的审计结果

拿这套工具审了我自己跑着的这个界面（`OpenAI.Codex` MSIX 包，Chromium 壳 + `app.asar` 471MB）：

| 项目 | 结果 |
| --- | --- |
| 界面资源位置 | `app.asar → webview/`（18449 个文件 / 437MB，本地打包，不走远端） |
| 语言包数量 | 135 个语区，`zh-CN` 已内置 |
| zh-CN 条目数 | 25074 条，与 zh-TW / ja-JP 的 key 覆盖率一致（缺 0 条） |
| 原生菜单 | `native-menu-locales/zh-CN.json` 209 条，无英文残留 |
| 生效开关 | `~/.codex/config.toml` 的 `[desktop] localeOverride = "zh-CN"` |
| 发现的漏翻 | **4 条**：`sidebarElectron.usageAlert.cadence.{day,hour,minute,week}` 仍是英文 ICU 复数消息（`month`/`year` 却是中文，zh-TW/ja-JP/de-DE 也都翻译了 → 官方遗漏） |
| 补丁状态 | 已生成：25074 条 → 25074 条、仅 4 条变化、2093436 字节等长、`node --check` 通过 |

结论：**这个界面本来就汉化完了**，不需要从零汉化；剩下的只是官方语言包里的 4 条漏翻。
真正写回 `app.asar` 要夺取 WindowsApps 目录所有权（破坏 MSIX 完整性、更新即失效），
所以补丁只做出来、没有安装 —— 为 4 条文案动系统目录不划算，更合理的是向官方反馈。

### 更正：语言包齐 ≠ 界面是中文

后来查明，上面这条结论只对了一半。`webview/assets/app-initial-*.js` 里有这么一段：

```js
s = Ohe(`72216192`)                    // 远端 feature gate（statsig dynamic config）
c = s?.get(`enable_i18n`, !1)          // 默认 false —— 主界面 i18n 的总开关
l = c                                  // 只有 l 为真，才会去动态 import 语言包
useEffect(() => { if (l) { Hxr(y).then(...) } }, [y, l, S, a])
```

也就是说：**语言包齐全，但 `enable_i18n` 这个远端开关默认关着**，所以主界面走英文兜底，
只有原生菜单（`native-menu-locales/`）会跟着 `localeOverride` 变中文。这正是社区汉化工具
在改的那一处。本项目改的是同一个地方，另外多补了 4 条官方漏翻：

```powershell
# 一键：自动定位版本 -> 构建两个补丁 -> 夺权 -> 等长写入 -> 还原权限 -> 重启
powershell -ExecutionPolicy Bypass -File tools\汉化-Codex.ps1
powershell -ExecutionPolicy Bypass -File tools\汉化-Codex.ps1 -DryRun   # 只构建校验，不写入
powershell -ExecutionPolicy Bypass -File tools\汉化-Codex.ps1 -Revert   # 还原英文
```

两个补丁都是**等字节长替换**（`!0` 后面补空格对齐），所以 asar 目录表不动、可精确回滚；
升级覆盖后重跑脚本即可，脚本每次都按当前版本重新构建补丁。
