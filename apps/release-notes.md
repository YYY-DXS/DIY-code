# DIY 软件合集

本次发行包含五个自制 Windows 小工具，全部绿色免安装（除 RAW 转 JPG 需先编译）。

## v1.0.1 修复

- 科技脉冲：补回 `public/index.html`（此前被 `.gitignore` 的 `*.html` 规则排除，源码包和 Release zip 打开 404）；`create-shortcuts.ps1` 在没有 `TechPulse.exe` 时自动改用 Node 启动。
- 桌面小组件：修复 `widget.py` 启动段缩进错误导致的启动崩溃；`启动浮窗.bat` 会自动检测并安装 Pillow，缺少依赖时弹窗提示而不是闪退。
- RAW 转 JPG：删除 `contentSplit` 的重复声明，补回 `build/app.ico`，`build.ps1` 可直接编译。

| 文件 | 软件 | 用法 |
| --- | --- | --- |
| `pc-toolkit.zip` | 电脑管家 | 解压后双击 `启动.bat`，系统体检 / 环境修复 / 垃圾清理 / 文件整理 |
| `desktop-widget.zip` | 桌面小组件 | 解压后双击 `启动浮窗.bat`，天气 / DeepSeek 余额 / CPU 内存浮窗 |
| `tech-pulse.zip` | 科技脉冲 | 解压后双击 `start.cmd`，每日科技新闻 + DIY 项目聚合 |
| `codex-portable.zip` | Codex 环境搬运 | 解压后运行 `codex-portable.cmd`，打包/还原 Codex 工作环境 |
| `raw-to-jpg.zip` | RAW 转 JPG | 解压后运行 `build.ps1` 编译出 `RAW转JPG.exe`，批量把 RAW 转 JPG |
| `SHA256SUMS.txt` | 校验值 | 下载后可用 `certutil -hashfile 文件名 SHA256` 核对 |

## 自动更新

仓库里的 `apps/check-update.ps1` 会按 `apps/manifest.json` 的哈希逐文件比对，
只补不一致的文件。双击 `apps/更新所有软件.cmd` 即可。

## 说明

这批代码是从 Codex 会话记录里的补丁重放重建的，个别功能可能与最初版本有细微差别。
本次已修复会阻止启动的三个问题。发现问题请开 Issue。
