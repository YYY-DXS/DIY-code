# DIY-code

个人 DIY 项目、自制 Windows 工具与 DeepSeek Harness 插件仓库。

## 下载

最新发行版：[v2.0.7](https://github.com/YYY-DXS/DIY-code/releases/tag/v2.0.7)

每个软件一个 zip，解压即用；`SHA256SUMS.txt` 可核对下载完整性。

## 目录

| 目录 | 说明 |
| --- | --- |
| [`apps/`](apps/README.md) | 独立 Windows 桌面工具（科技脉冲、桌面小组件、电脑管家、Codex 环境搬运、RAW 转 JPG、DSH 插件脉冲面板、Lumen 译、汉化工具） |
| [`plugins/`](plugins/README.md) | DeepSeek Harness 宿主插件（DeepSeek Hub、Media Studio、Query Bridge、Codex History Bridge） |
| [`extras/`](extras/README.md) | 单独发布的生成器与脚本（高中政治思维导图） |
| [`projects/`](projects/README.md) | 各个 DIY 项目的资料（齐柏林飞艇、外骨骼、台历、航模方向） |
| [`tools/`](tools/README.md) | 配套工具：DeepSeek 记录同步、Git 同步、隐私检查、Markdown 转换 |

## 本次 v2.0.7 收录

| 包 | 类型 | 用途 |
| --- | --- | --- |
| `pc-toolkit.zip` | 桌面工具 | 系统体检 / 环境修复 / 深度垃圾与隐私清理 / 文件整理 |
| `desktop-widget.zip` | 桌面工具 | 天气 / DeepSeek 余额 / CPU 内存悬浮窗 |
| `tech-pulse.zip` | 桌面工具 | 每日科技新闻 + DIY 项目聚合 |
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

## 许可

本项目采用 [MIT 许可](LICENSE)：任何人都可以自由使用、修改、再发布，
只要保留版权声明即可。
