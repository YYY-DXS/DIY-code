# DeepSeek Hub

把 DeepSeek 网页对话同步成本地 Markdown 知识库，并把新项目发布到 GitHub。

## 工具

| 工具 | 作用 |
| --- | --- |
| `deepseek_status` | 知识库会话数/消息数/最近同步时间/浏览器配置是否就绪 |
| `deepseek_sync` | 立即同步（`limit` 限制条数、`force` 强制重抓、`visible` 显示窗口） |
| `github_publish` | 跑一次自动发布（`dryRun` 只预演） |
| `hub_doctor` | 逐项自检：知识库、浏览器 profile、Edge、Git、仓库、Python |

## 工作原理

1. 用**专用 Edge profile** 启动一个浏览器（默认离屏），通过 CDP 连接。
2. 让网页自己加载会话列表与历史，**直接读它收到的响应体**——不重放请求、不保存 token、不用 API key。
3. 服务端只回 `cache_control: MERGE`（表示用本地缓存）时，从网页自己的
   IndexedDB（`deepseek-chat` / `history-message`）取完整内容。
4. 渲染成 Markdown 写入 `knowledgeDir`，按 `updated_at` 增量跳过没变化的会话。

## 配置

`cordis.patch.yml` 里可改：

| 键 | 说明 |
| --- | --- |
| `knowledgeDir` | 知识库输出目录（含 `transcripts/`、`data/`、`index.md`） |
| `profileDir` | 专用浏览器配置目录（登录态存在这里） |
| `edgePath` | msedge.exe 路径 |
| `repoDir` | 发布用仓库目录（需含 `.git` 和 `tools/auto-publish/`） |
| `pythonPath` | 发布脚本用的 Python |
| `port` | CDP 调试端口 |
| `autoSyncMinutes` | 自动同步间隔（分钟，0 = 关闭） |
| `dailyPublishAt` | 每天自动发布的时间（`HH:MM`，空 = 关闭），取代 Windows 计划任务 |

## 状态面板

打开 `<DSH_WEB_URL>/deepseek-hub`（例如 `http://127.0.0.1:51415/deepseek-hub`），
能看到会话数、消息数、同步状态、最近同步/发布时间、自动同步与每日发布时间。
页面每 5 秒轮询 `/deepseek-hub/status`。

也可以双击 `desktop/启动面板.cmd` 打开原生 WinForms 小面板。它默认从当前目录或上三级
目录寻找仓库，也可以用环境变量指定：

```powershell
$env:DEEPSEEK_HUB_KNOWLEDGE = "D:\knowledge\deepseek-web"
$env:DEEPSEEK_HUB_REPO = "D:\code\DIY-code"
```

`desktop/Launcher.cs` 是面板启动器的源码，`DeepSeekHubPanel.exe` 是编译好的版本。

## 注意

- 专用 profile 必须独占，同步时会拉起 Edge；如果你自己的 Edge 占着同一个 profile 会失败。
- 登录态过期时同步会失败，需要在专用 profile 里重新登录一次。
- 网页上删除的会话不会自动从知识库删除（只增不减）。
