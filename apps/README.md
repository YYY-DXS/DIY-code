# 应用合集

这里放的是独立 Windows 工具（多数来自 Codex 会话重建，桌面小组件的依赖已补全）。
每个目录都能单独使用，也可以整包更新。

| 目录 | 软件 | 说明 | 运行方式 |
| --- | --- | --- | --- |
| `pc-toolkit/` | 电脑管家 | 系统体检、环境修复、垃圾清理、文件整理 | 双击 `启动.bat` |
| `desktop-widget/` | 桌面小组件 | 天气 / DeepSeek 余额 / CPU 内存悬浮窗 | 双击 `启动浮窗.bat` |
| `tech-pulse/` | 科技脉冲 | 每日科技新闻 + DIY 项目聚合推送 | 双击 `start.cmd` |
| `codex-portable/` | Codex 环境搬运 | 把 Codex 工作环境打包搬到新电脑 | `codex-portable.cmd` |
| `raw-to-jpg/` | RAW 转 JPG | 批量把 ARW 等 RAW 转成 JPG 的桌面工具 | `build.ps1` 编译后运行 |
| `dsh-plugin-pulse/` | DSH 插件脉冲面板 | 可视化安装 / 卸载 DSH 插件并做兼容性诊断 | 双击 `启动脉冲面板.cmd` |

## 依赖说明

- `desktop-widget`：启动器会自动检测并安装 Pillow，不需要手动 `pip install`。
- `tech-pulse`：源码运行需要 Node.js 20+；打包 exe 需要先 `npm install`，再 `npm run build:exe`。
- `raw-to-jpg`：使用 Windows 自带 .NET Framework 4.x 编译器，无需第三方运行库。
- `dsh-plugin-pulse`：源码运行需要 Python 3 + Tkinter；也可以先 `build.ps1` 打包。

## 自动更新

双击 `更新所有软件.cmd`，它会读取本目录的 `manifest.json`，把本地与线上
不一致的文件逐个补齐。只覆盖清单里列出的文件，不会动你自己的数据
（比如 `desktop-widget/config.json` 里填的 API Key 需要你自己保留）。

更新器两种通道自动切换：

1. `raw.githubusercontent.com` 直连
2. 失败时改用 GitHub API（`api.github.com`）取 base64 内容

## 说明

- 这些目录最初是从 Codex 会话日志里的补丁**重放重建**的，个别功能可能和原版有细微差别。
- v2.0.0 已修复会阻止启动的问题：科技脉冲缺入口页、桌面小组件启动缩进、RAW 转 JPG 重复字段。
- `desktop-widget/config.json` 里 API Key 是空的，用之前自己填。
