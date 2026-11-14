# 科技脉冲 Tech Pulse

一个运行在本机的每日科技新闻与 DIY 项目雷达。它会在你设置的时间抓取多个来源，按影响力重新排序，并生成一份保存到本机的日报。

## 直接开始

1. 安装 Node.js 20 或更高版本。
2. 双击 `start.cmd`，浏览器会打开 <http://127.0.0.1:4173>。
3. 点击“立即生成”完成第一份日报。
4. 打开“设置”，把每日推送时间改成你希望的时间。

关闭服务可双击 `stop.cmd`。日报和设置保存在本机 `data/`。默认只显示 Windows
本地通知；只有在你主动配置 Webhook 或 Server酱后，日报内容才会推送给你指定的服务。

## 定时推送什么时候生效

定时器在本地服务运行时工作。电脑关机或服务退出后，它不会凭空运行。

如果希望登录 Windows 后自动启动服务，在 PowerShell 中运行：

```powershell
cd "本工具目录"
powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1
```

移除自动启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\remove-autostart.ps1
```

如果使用源码包（没有 `TechPulse.exe`），可以运行 `create-shortcuts.ps1` 生成桌面与
开机启动快捷方式。脚本会自动判断：有 `TechPulse.exe` 就用它，没有就改用 Node 启动
`server.mjs`，因此不再要求先编译 exe。

```powershell
powershell -ExecutionPolicy Bypass -File .\create-shortcuts.ps1
```

## 内容来源

- 科技媒体 RSS：默认包含 IT之家、少数派、Ars Technica、The Verge、TechCrunch、IEEE Spectrum，可在设置中增删。
- Hacker News：读取热门条目、点数和讨论数。
- B站：按可编辑搜索词读取近期视频，使用播放、弹幕和收藏数据。
- GitHub：轮换扫描最多四个高优先级 topics，读取近期创建项目的 stars、forks 和描述。

“影响力”不是单一阅读量。日报按以下维度加权：

- 30% 时间新鲜度
- 24% 与你关键词的匹配度
- 24% 来源内的互动热度
- 12% 来源质量
- 10% 跨来源相似主题共振

## 通知

设置中可以启用：

- Windows 系统 Toast
- 页面打开时的浏览器通知
- 通用 JSON Webhook
- Server酱 SendKey

Webhook 会收到 `title`、`text`、`markdown`、`url` 和完整 `report` 字段。

## 可选环境变量

不设置也能使用。设置后可提高稳定性或请求额度：

```powershell
$env:GITHUB_TOKEN = "github_pat_xxx"
$env:BILIBILI_COOKIE = "SESSDATA=xxx; bili_jct=xxx"
```

请在启动服务的同一个终端里设置，或通过 Windows 系统环境变量配置。不要把这些值写进 RSS 地址或 Webhook。

## 常用命令

```powershell
npm install          # 安装依赖（也支持 pnpm install）
npm start            # 以源码方式启动
npm test             # 跑单元测试
npm run dev          # 改代码时自动重启
npm run build:exe    # 打包成 TechPulse.exe（需要 Node 在 PATH 里）
```

`build:exe` 会生成 `apps/TechPulse/TechPulse.exe` 与配套文件；打包完成后可直接运行
`create-shortcuts.ps1` 创建快捷方式。

端口默认是 `4173`，可设置 `PORT` 环境变量改变端口。

## 已知边界

- GitHub 未登录搜索有频率限制，短时间内反复生成可能只返回部分来源。
- B站接口偶尔会触发风控；设置 Cookie 或稍后重试可恢复。
- 当前版本保留原标题与来源摘要，不做机器翻译，避免引入额外 API Key 成本。
- 每个来源的统计口径不同，所以排序分数是“影响力指数”，不是统一阅读量。
