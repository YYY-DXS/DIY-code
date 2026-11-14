# DSH 插件

这里放的是给 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 用的宿主插件。
它们不是独立 exe，需要先安装并运行 DSH；每个目录都有 `package.json`、`cordis.patch.yml`
和 README。

| 目录 | 插件 | 作用 |
| --- | --- | --- |
| `deepseek-hub/` | `@local/deepseek-hub` | 把 DeepSeek 网页会话同步成本地 Markdown 知识库，并提供 GitHub 自动发布入口 |
| `media-studio/` | `@local/media-studio` | 让 Agent 直接驱动本机的 FilmCraft / EffectCraft / PhotoCraft / LightCraft |
| `query-bridge/` | `@local/query-bridge` | 查询 GitHub 仓库状态、DeepSeek 账户余额、工作区历史会话 |
| `codex-history-bridge/` | `@local/codex-history-bridge` | 把本机 Codex 历史导入工作区（Markdown + 索引 + 可选原始 JSONL） |

## 安装

把插件目录放到 DSH profile 的插件目录，或在 DSH 插件管理器里从本地目录安装，然后重启
DSH。各插件的 `README.md` 里有具体的配置项和工具说明。

`cordis.patch.yml` 是配置模板：里面的 `C:\path\to\...` 需要改成你自己的路径。也可以不写
进配置，用对应的环境变量覆盖（例如 DeepSeek Hub 的 `DEEPSEEK_HUB_KNOWLEDGE`、
`DEEPSEEK_HUB_PROFILE`、`DEEPSEEK_HUB_REPO`、`DEEPSEEK_HUB_PYTHON`）。

## 依赖

- Node.js 20+ / DSH 自带运行时
- Python 3（Query Bridge、Codex History Bridge、DeepSeek Hub 的发布脚本会用到）
- DeepSeek Hub 额外需要 Microsoft Edge 和一个专用浏览器 profile
- Media Studio 需要本机安装对应的剪辑 / 修图软件

## 安全

- 插件只在本机运行，不经过中转服务器。
- API Key 从环境变量或 `api.txt` 读取，源码里不含任何密钥。
- 发布到 GitHub 前建议先跑 `tools/security/privacy_check.py --check`。
