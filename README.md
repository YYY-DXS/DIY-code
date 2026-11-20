# DIY-code

个人 DIY 项目、自制 Windows 工具与 DeepSeek Harness 插件仓库。

[![Release](https://img.shields.io/github/v/release/YYY-DXS/DIY-code?display_name=tag&sort=semver)](https://github.com/YYY-DXS/DIY-code/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Publish apps](https://github.com/YYY-DXS/DIY-code/actions/workflows/release.yml/badge.svg)](https://github.com/YYY-DXS/DIY-code/actions/workflows/release.yml)

## 下载

最新发行版：[v2.0.8](https://github.com/YYY-DXS/DIY-code/releases/tag/v2.0.8)

每个软件一个 zip，解压即用；`SHA256SUMS.txt` 可核对下载完整性。

## 首次运行提示

解压后运行 exe，Windows 可能弹出「Windows 已保护你的电脑」。**这不是报毒**：本项目没有购买商业代码签名证书，
SmartScreen 对「未知发布者 + 新文件」一律拦截。

确认来源后，任选一种通过：

1. 点弹窗里的 **更多信息** → **仍要运行**
2. 右键 exe → **属性** → 勾选 **解除锁定** → 确定
3. PowerShell：`Unblock-File .\程序.exe`

更稳妥的做法是先核对哈希：`Get-FileHash .\xxx.zip -Algorithm SHA256`，与 Release 里的 `SHA256SUMS.txt` 对比。
签名机制与后续方案见 [docs/首次运行与签名.md](docs/首次运行与签名.md)。

## 目录

| 目录 | 说明 |
| --- | --- |
| [`apps/`](apps/README.md) | 独立 Windows 桌面工具（科技脉冲、桌面小组件、电脑管家、Codex 环境搬运、RAW 转 JPG、DSH 插件脉冲面板、Lumen 译、汉化工具） |
| [`plugins/`](plugins/README.md) | DeepSeek Harness 宿主插件（DeepSeek Hub、Media Studio、Query Bridge、Codex History Bridge、鲸鱼提示） |
| [`extras/`](extras/README.md) | 单独发布的生成器与脚本（高中政治思维导图） |
| [`projects/`](projects/README.md) | 各个 DIY 项目的资料（齐柏林飞艇、外骨骼、台历、航模方向） |
| [`tools/`](tools/README.md) | 配套工具：DeepSeek 记录同步、Git 同步、隐私检查、Markdown 转换 |
| [`docs/`](docs/) | 首次运行提示、代码签名方案与发布检查清单 |

## 本次 v2.0.8 收录

| 包 | 类型 | 用途 |
| --- | --- | --- |
| `pc-toolkit.zip` | 桌面工具 | 系统体检 / 环境修复 / 深度垃圾与隐私清理 / 文件整理 |
| `desktop-widget.zip` | 桌面工具 | 天气 / DeepSeek 余额 / CPU 内存悬浮窗 |
| `tech-pulse.zip` | 桌面工具 | 每日科技新闻 + DIY 项目聚合（英文自动译中文） |
| `codex-portable.zip` | 桌面工具 | Codex 工作环境盘点、打包、还原与加密 |
| `raw-to-jpg.zip` | 桌面工具 | 批量 RAW / 图片转 JPG（附 C# 源码） |
| `lumen-translate.zip` | 桌面工具 | 划词 / 截图翻译（在线线路 + OpenAI 兼容 AI 引擎） |
| `hanhua-kit.zip` | 桌面工具 | 通用软件汉化流水线（提取、翻译、占位符保护、回写） |
| `deepseek-hub.zip` | DSH 插件 | DeepSeek 网页会话同步成本地知识库 + GitHub 发布 |
| `media-studio.zip` | DSH 插件 | 驱动本机 FilmCraft / EffectCraft / PhotoCraft / LightCraft |
| `query-bridge.zip` | DSH 插件 | 查询 GitHub 状态、DeepSeek 余额、历史会话 |
| `codex-history-bridge.zip` | DSH 插件 | 把 Codex 历史会话导入工作区 |
| `dsh-plugin-pulse.zip` | 桌面工具 | 可视化 DSH 插件安装 / 卸载 / 兼容性诊断 |
| `political-mindmap.zip` | 生成器 | 高中政治必修 1–2 思维导图（A4 一框一页） |
| `tools.zip` | 工具集 | 同步、发布、隐私检查、Markdown 转换等配套脚本 |
| `updater.zip` | 更新器 | 解压到各软件同一层，运行 `apps\更新所有软件.cmd`，按最新 Release 增量更新 |

## 文件格式

仓库里只保留 Markdown / 源码。**Word 和 HTML 只是在本地生成给自己看的，默认不上传**；
科技脉冲的 `public/index.html`、插件面板的 `ui.html` 属于程序源码，已在 `.gitignore` 中单独放行。

| 格式 | 用途 |
| --- | --- |
| `.md` | 文档与说明 |
| `.js` / `.mjs` / `.py` / `.ps1` / `.cs` | 软件源码 |
| `.html` | 仅程序入口/界面源码；生成的阅读版 HTML 不上传 |

改完 `.md` 之后在本地重新生成阅读版：

```bash
python tools/md2readable/md_to_readable.py
```

## 同步方式

本机已经配好 SSH 密钥，可以直接拉取和推送：

```bash
git clone git@github.com:YYY-DXS/DIY-code.git
git pull
git push
```

不想敲命令的话，双击 `tools\同步仓库.cmd`，它会自动拉取最新、提交本地改动并推送。

## 代码签名

Windows 可执行文件由 CI 从源码构建，脚本是 [`tools/build/build-binaries.ps1`](tools/build/build-binaries.ps1)，
构建记录见 Actions 的 **Build binaries**，产物是 artifact `binaries-<版本>`。

**当前状态：尚未签名。** 首次运行会出现上文所说的 SmartScreen 提示，请用 `SHA256SUMS.txt` 核对完整性。

Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org).

- Committers and reviewers: [@YYY-DXS](https://github.com/YYY-DXS)
- Approvers: [@YYY-DXS](https://github.com/YYY-DXS)
- Privacy policy: 不收集遥测，不上传任何使用数据。联网只发生在你主动使用的功能上——天气与 AQI、DeepSeek 余额查询、科技新闻抓取、在线翻译；API Key 与历史记录仅保存在本机（`config.json`、`data/`），不会进入仓库。

> SignPath Foundation 的申请状态见 [docs/code-signing.md](docs/code-signing.md)。审批通过前，上述签名政策尚未生效。

## 许可

本项目采用 [MIT 许可](LICENSE)：任何人都可以自由使用、修改、再发布，
只要保留版权声明即可。
