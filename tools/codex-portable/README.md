# codex-portable

把 Codex 的整套工作环境（项目代码、聊天知识库、配置、开机自启）安全地搬到另一台
Windows 电脑上。

零依赖：只用 Windows 自带的 PowerShell 和 robocopy，不用装 Python、Node 或任何库。

```powershell
.\codex-portable.ps1 scan                          # 先看这台机器上有什么
.\codex-portable.ps1 export -Dest "E:\迁移包"      # 打包
.\codex-portable.ps1 restore -Package "D:\迁移包"  # 新电脑上还原
```

## 为什么不是"整个文件夹拷过去"

Codex 相关的东西混着三类完全不同的数据：能公开的代码、绝不能外传的聊天记录、以及
一旦泄露就要换 key 的凭据。一股脑打包，要么把隐私传到网上，要么把密钥带进仓库。

这个工具先把数据分成四类，再按类处理：

| 类 | 内容 | 去向 |
| --- | --- | --- |
| **A 代码** | 项目源码、脚本、生成物 | 私有仓库 / 直接拷贝 |
| **B 隐私** | 聊天记录、Codex 会话与记忆 | 加密后上传，或移动硬盘 |
| **C 密钥** | API Key、登录凭据、本机令牌 | 永不入库，单独带 |
| **D 缓存** | node_modules、venv、构建产物、日志 | 不搬，新机器重装 |

## 命令

### `scan` 盘点

```powershell
.\codex-portable.ps1 scan            # 表格
.\codex-portable.ps1 scan -Json      # 机器可读
```

按 A/B/C/D 汇总体积和文件数，额外列出超过 50 MB 的文件（GitHub 单文件上限是
100 MB）和构建缓存目录。

### `export` 打包

```powershell
.\codex-portable.ps1 export -Dest "E:\Codex迁移包"
.\codex-portable.ps1 export -Dest "E:\Codex迁移包" -Repo     # 适合传 GitHub
.\codex-portable.ps1 export -Dest "E:\Codex迁移包" -Zip      # 额外打 tar.gz
```

| 参数 | 作用 |
| --- | --- |
| `-SkipPrivate` | 不导出聊天记录与 Codex 会话 |
| `-IncludeCaches` | 连 node_modules / venv / JDK 一起导出 |
| `-IncludeSecrets` | 连明文密钥一起导出（危险，默认关闭） |
| `-Lean` | 跳过 `.recon` 反编译素材（约省 100 MB） |
| `-MaxFileMB <n>` | 剔除超过 n MB 的文件，并在清单里记账 |
| `-Repo` | 等价于 `-SkipPrivate -Lean -MaxFileMB 50` |
| `-DryRun` | 只打印动作，不落盘 |

导出目录**不能**位于 `Desktop\codex`、`New project`、`.codex` 之内——否则会自己
复制自己。工具会检查并拒绝。

产物结构：

```text
Codex迁移包\
├─ 00-清单\                 环境快照、SHA256 清单、隐私提醒
├─ 01-项目源码\New project\  代码、脚本、配套工具
├─ 02-DeepSeek知识库\        聊天记录（隐私）
├─ 03-Codex工作区\           生成物（应用、工具、成品）
├─ 04-Codex应用数据\.codex\  全局约定、规则、会话、记忆库
├─ 05-启动项与快捷方式\      自启脚本与桌面快捷方式
└─ 06-密钥\                  仅 -IncludeSecrets 时出现
```

### `restore` 还原

```powershell
.\codex-portable.ps1 restore -Package "D:\Codex迁移包"
.\codex-portable.ps1 restore -Package "D:\Codex迁移包" -NewUser zhangsan
.\codex-portable.ps1 restore -Package "D:\Codex迁移包" -DryRun
```

自动完成：复制项目与产物、还原 Codex 配置和会话、重建桌面快捷方式、重装自启项。
如果新电脑用户名和旧电脑不同，会把脚本、`.vbs`、配置里写死的 `C:\Users\旧名`
一并改写（这是这类迁移最容易静默失败的地方）。已存在的配置先备份成 `.bak-时间戳`。

### `verify` 校验

```powershell
.\codex-portable.ps1 verify -Package "D:\Codex迁移包"
.\codex-portable.ps1 verify -Package "D:\Codex迁移包" -Deep   # 逐个核对 SHA256
```

### `protect` / `unprotect` 加密隐私包

```powershell
.\codex-portable.ps1 protect   -Path "隐私.tar.gz" -OutFile "隐私.tar.gz.enc"
.\codex-portable.ps1 unprotect -Path "隐私.tar.gz.enc" -OutFile "隐私.tar.gz"
```

AES-256-CBC + HMAC-SHA256，PBKDF2-SHA256（12 万次迭代）派生密钥，每次随机 salt
和 IV。密码丢了就解不回来。

### `selftest` 自检

```powershell
.\codex-portable.ps1 selftest
```

在临时目录里造一套假环境，完整跑 `scan → export → restore → protect/unprotect`，
用于改完代码后的回归验证。

## 迁移流程建议

1. **旧机**：`scan` 看清家底 → `export` 打包
2. **新机**：先装 Codex 桌面版并启动一次（桌面上那些 Python 小工具依赖它自带的运行时）
3. `restore` 还原
4. 浏览器装一次 Tampermonkey，打开本机服务地址点"安装同步脚本"
5. 重启电脑，确认自启项生效

## 发布 / 更新到 GitHub

首次发布：

1. 双击 `推到GitHub.cmd`，粘贴仓库地址（如 `https://github.com/you/codex-portable.git`）
2. 有 Git Credential Manager 就浏览器登录；没有就粘贴一次 Personal Access Token
   （只用于本次推送，不会写入 `.git/config`）
3. 没有 GCM 时，脚本会用这个 token 自动创建一个同名**私有**仓库；如果仓库已存在就跳过

省略第 3 步也可以：先在 GitHub 建一个空仓库（不要勾选 README 初始化），再运行脚本。

以后更新只要在仓库目录里：

```powershell
git add -A
git commit -m "说明改了什么"
.\push-to-github.ps1 -Repo https://github.com/you/codex-portable.git
```

> 这台机器自带的 git 用 schannel 会报 `SEC_E_NO_CREDENTIALS`，脚本已自动加
> `-c http.sslBackend=openssl`。

## 已知限制

- 只支持 Windows（依赖 robocopy 和 WScript.Shell）。
- 开机自启靠"启动文件夹"，部分安全软件会拦截写启动项，需加信任或手动拖入。
- 浏览器扩展（如 Tampermonkey 里的用户脚本）无法跨机器复制，必须在浏览器里重装。
- 加密是"文件级"的，不会加密文件名；上传前建议先打包成单个 tar.gz。
- 提交/推送需要你自己的 GitHub 凭据，工具不会存储任何令牌。

## 目录

```text
codex-portable.ps1   主程序（scan / export / restore / verify / protect / selftest）
codex-portable.cmd   双击启动器
push-to-github.ps1   把本仓库推到 GitHub（浏览器登录，不经过第三方）
docs/方案.md          数据分类与迁移方案的设计说明
```

## 许可

MIT
