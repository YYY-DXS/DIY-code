# 应用合集

这里放的是从 Codex 会话记录里重建出来的五个自制软件。每个都是独立目录，
可以单独使用，也可以整包更新。

| 目录 | 软件 | 说明 | 运行方式 |
| --- | --- | --- | --- |
| `pc-toolkit/` | 电脑管家 | 系统体检、环境修复、垃圾清理、文件整理 | 双击 `启动.bat` |
| `desktop-widget/` | 桌面小组件 | 天气 / DeepSeek 余额 / CPU 内存悬浮窗 | 双击 `启动浮窗.bat` |
| `tech-pulse/` | 科技脉冲 | 每日科技新闻 + DIY 项目聚合推送 | 双击 `start.cmd` |
| `codex-portable/` | Codex 环境搬运 | 把 Codex 工作环境打包搬到新电脑 | `codex-portable.cmd` |
| `raw-to-jpg/` | RAW 转 JPG | 批量把 ARW 等 RAW 转成 JPG 的桌面工具 | `build.ps1` 编译后运行 |

## 自动更新

双击 `更新所有软件.cmd`，它会读取本目录的 `manifest.json`，把本地与线上
不一致的文件逐个补齐。只覆盖清单里列出的文件，不会动你自己的数据
（比如 `desktop-widget/config.json` 里填的 API Key 需要你自己保留）。

更新器两种通道自动切换：

1. `raw.githubusercontent.com` 直连
2. 失败时改用 GitHub API（`api.github.com`）取 base64 内容

## 说明

- 这些目录是从 Codex 会话日志里的补丁**重放重建**的，不是原始文件夹的拷贝。
- 两个较大的项目有个别补丁没能精确还原：桌面小组件的 6 处、RAW 转 JPG 的 1 处。
  代码能通过语法检查，功能可能和原版有细微差别。
- `desktop-widget/config.json` 里 API Key 是空的，用之前自己填。
