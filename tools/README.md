# 工具集

这些是为了支撑 DIY 项目而做的一整套小工具，全部本地运行、不上传任何数据。

## DeepSeek 记录同步

把 DeepSeek 网页版的对话记录同步到本地知识库，方便以后查资料、接续讨论。

| 文件 | 作用 |
| --- | --- |
| `deepseek_sync.py` | 把官方导出包增量导入本地知识库 |
| `deepseek_pinned.py` | 重建「置顶会话」目录（自动同步置顶变更） |
| `deepseek_purge_live.py` | 清理实时同步产生的临时记录 |
| `deepseek_bridge/` | 浏览器脚本 + 本机接收服务，实现实时同步 |

`deepseek_bridge/` 里包含：

- `userscript_template.js`：Tampermonkey 用户脚本模板，挂在 DeepSeek 页面上抓取新消息
- `server.py`：本机接收端（只监听 127.0.0.1）
- `start.cmd` / `stop.cmd` / `restart.cmd`：启停服务
- `autostart.vbs`：开机自启
- `test_parse.mjs`：离线回归测试，用真实报文验证解析逻辑

## Git 相关

| 文件 | 作用 |
| --- | --- |
| `github/sync-repo.ps1` | 从 GitHub 拉取仓库（国内直连被拦时自动走代理） |
| `gitee/upload-to-gitee.ps1` | 一键提交并推送到码云 |
| `同步仓库.ps1` | 一键同步当前仓库（拉取 → 提交 → 推送） |

## 其他

| 文件 | 作用 |
| --- | --- |
| `global-context/install-global-context.ps1` | 把知识库指引写入 Codex 全局 AGENTS.md，让新对话自动读取 |

## 环境说明

这台机器上的 git 需要显式设置 `GIT_EXEC_PATH` 才能做 clone/fetch/push，
相关脚本里已经处理。

> 注意：不同机器上的路径不同，脚本里涉及绝对路径的地方需要按实际情况调整。
