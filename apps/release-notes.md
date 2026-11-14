# DIY 软件合集 v2.0.3

本次发行把仓库里所有可独立分发的软件打成 14 个 zip：8 个 Windows 桌面工具、4 个 DSH
宿主插件、1 个生成器、1 个工具集。每个包解压即用（个别需要 Node / Python / DSH 运行时，
见各包 README）。

## v2.0.3 更新

- **电脑管家**：新增「深度垃圾」与「隐私痕迹」清理（参照火绒的清理分类、PrivaZer 的隐私痕迹思路）。
  - 深度垃圾：Windows/用户临时文件、错误报告、崩溃转储、CBS/DISM/更新日志、传递优化、缩略图/图标缓存、Windows.old；可选 Prefetch 等高级项。
  - 隐私痕迹：Edge/Chrome/Brave/Firefox 历史、Cookie、缓存、站点数据；Windows 最近记录、跳转列表、运行历史、搜索记录、DNS 缓存、剪贴板、PowerShell 命令历史。
  - 可选安全擦除（删除前随机覆写文件）和 `cipher /w` 空闲空间擦除；注册表痕迹先导出备份。
  - 图形界面新增「只扫描隐私痕迹」「擦除空闲空间」按钮；命令行新增 `DeepClean`、`PrivacyScan`、`PrivacyClean`、`WipeFree`。
- **快捷方式**：10 个自制软件快捷方式全部补齐品牌图标（桌面小组件、Codex 环境搬运、汉化工具之前使用 PowerShell/cmd 默认图标）；`fix-shortcuts.ps1` 同步支持 Lumen 译、汉化工具和开机启动项修复。
- **桌面小组件**：`config.json`（含 API Key、窗口位置）改为本机私有，不再进入仓库和 Release 包。

## v2.0.2 修复

- **汉化工具**：`tools/codex-zh-cn.ps1` 补回 UTF-8 BOM。少了 BOM 时 Windows PowerShell 5.1
  会把中文当 ANSI 解析，脚本直接报语法错误。
- 同步更新 `manifest.json`。

## v2.0.1 新增

- **Lumen 译**（`lumen-translate.zip`）：划词 / 截图翻译桌面工具。选中即译、全局快捷键、
  系统托盘、在线三线路自动降级、OpenAI 兼容 AI 引擎；纯标准库 + Tkinter，无需 pip 安装。
- **汉化工具**（`hanhua-kit.zip`）：通用软件汉化流水线，支持 JSON / PO / RESX / Android
  strings.xml，带占位符保护、翻译记忆与质量检查。
- 同步更新 `manifest.json`，两个新包可通过 `apps/更新所有软件.cmd` 自动补齐。

## v2.0.0 更新

- **科技脉冲**：补回 `public/index.html`（此前被 `.gitignore` 的 `*.html` 规则排除，源码包和 Release 打开 404）；`create-shortcuts.ps1` 在没有 `TechPulse.exe` 时自动改用 Node 启动；补齐 `build-exe` 依赖并在全新检出、没有 `data/` 的情况下也能打包。
- **桌面小组件**：修复 `widget.py` 启动段缩进错误导致的启动崩溃；`启动浮窗.bat` 自动检测并安装 Pillow，缺依赖时弹窗提示而不是闪退。
- **RAW 转 JPG**：删除 `contentSplit` 的重复声明，补回 `build/app.ico`，`build.ps1` 可直接编译。
- **电脑管家 / Codex 环境搬运 / 科技脉冲 / 插件面板**：所有 PowerShell 脚本补 UTF-8 BOM，修复 Windows PowerShell 5.1 下中文脚本被按 ANSI 解析导致的语法错误。
- **新增 DSH 插件**：DeepSeek Hub、Media Studio、Query Bridge、Codex History Bridge。
- **新增工具**：DSH 插件脉冲面板、高中政治思维导图生成器、完整工具集。
- 同步更新 `manifest.json` 哈希、隐私脱敏（去掉本机用户名与绝对路径）。

## 下载内容

| 文件 | 类型 | 用法 |
| --- | --- | --- |
| `pc-toolkit.zip` | 桌面工具 | 解压后双击 `启动.bat`，系统体检 / 环境修复 / 深度垃圾与隐私清理 / 文件整理 |
| `desktop-widget.zip` | 桌面工具 | 解压后双击 `启动浮窗.bat`，天气 / DeepSeek 余额 / CPU 内存浮窗 |
| `tech-pulse.zip` | 桌面工具 | 解压后双击 `start.cmd`，每日科技新闻 + DIY 项目聚合 |
| `codex-portable.zip` | 桌面工具 | 解压后运行 `codex-portable.cmd`，打包 / 还原 Codex 工作环境 |
| `raw-to-jpg.zip` | 桌面工具 | 解压后运行 `build.ps1` 编译出 `RAW转JPG.exe`，批量把 RAW 转 JPG |
| `dsh-plugin-pulse.zip` | 桌面工具 | 解压后双击 `启动脉冲面板.cmd`，安装 / 卸载 / 诊断 DSH 插件 |
| `lumen-translate.zip` | 桌面工具 | 解压后双击 `run.cmd`，划词 / 截图翻译，在线 + AI 双引擎 |
| `hanhua-kit.zip` | 桌面工具 | 解压后 `pip install -e .`，用 `python -m hanhua` 走汉化流水线 |
| `deepseek-hub.zip` | DSH 插件 | 同步 DeepSeek 网页会话到本地 Markdown，并提供 GitHub 发布入口 |
| `media-studio.zip` | DSH 插件 | 驱动本机 FilmCraft / EffectCraft / PhotoCraft / LightCraft |
| `query-bridge.zip` | DSH 插件 | 查询 GitHub 仓库状态、DeepSeek 余额、历史会话 |
| `codex-history-bridge.zip` | DSH 插件 | 把本机 Codex 历史导入工作区 |
| `political-mindmap.zip` | 生成器 | 高中政治必修 1–2 思维导图（A4 一框一页） |
| `tools.zip` | 工具集 | 同步、发布、隐私检查、Markdown 转换等配套脚本 |
| `SHA256SUMS.txt` | 校验值 | 下载后可用 `certutil -hashfile 文件名 SHA256` 核对 |

## 自动更新

仓库里的 `apps/check-update.ps1` 会按 `apps/manifest.json` 的哈希逐文件比对，
只补不一致的文件。双击 `apps/更新所有软件.cmd` 即可。

## 说明

这批代码最初是从 Codex 会话记录里的补丁重放重建的，个别功能可能与最初版本有细微差别。
v2.0.3 已修复已知的启动阻断问题并增强清理/隐私功能；发现问题请开 Issue。
