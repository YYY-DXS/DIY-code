# 代码签名（Code signing）

## 现状

| 项 | 状态 |
| --- | --- |
| 从源码可验证构建 | ✅ `.github/workflows/build-binaries.yml` → `tools/build/build-binaries.ps1` |
| 产物带产品名/版本元数据 | ✅ 构建脚本会校验，缺元数据直接失败 |
| 公共 CA 证书签名 | ❌ 未签名，因此有 SmartScreen 提示 |
| SignPath Foundation 申请 | ⏳ 未提交（需要仓库有一定曝光量后再申请，见下） |

构建出来的三个产物：

| 文件 | 来源 |
| --- | --- |
| `DeepSeekHubPanel.exe` | `plugins/deepseek-hub/desktop/Launcher.cs`（csc） |
| `RAW转JPG.exe` | `apps/raw-to-jpg/src/*.cs`（csc，WPF） |
| `DSH-Plugin-Pulse.exe` | `apps/dsh-plugin-pulse/pulse_panel.py`（PyInstaller） |

## 本地的等价命令

```powershell
# 需要：.NET Framework 4 的 csc、带 PyInstaller 的 Python
pip install pyinstaller
./tools/build/build-binaries.ps1 -PythonExe python
# 产物在 dist-bin/，SHA256SUMS.txt 一并生成
```

## 申请 SignPath Foundation

入口：<https://signpath.org/apply>（先读一遍 <https://signpath.org/terms>）

**硬性门槛**（条款原文归纳）：

- OSI 许可、无专有组件、持续维护、已发布、有文档 —— 全部满足
- 首页要有 **Code signing policy** 段落 —— 已写在 README
- 产物必须由 CI 从源码构建 —— 已满足
- 每个可执行文件带产品名/版本元数据 —— 已满足
- 团队角色（Author / Reviewer / Approver）与 MFA —— 单人项目，全部指向 @YYY-DXS，账号需开 2FA
- **项目要有可验证的知名度**（"we require a certain verifiable reputation"）—— 目前最弱的一项，建议先攒到 20–30 star、有真实下载量再提交

申请表里可以直接用这段（按需补联系方式）：

```
Project: DIY-code
Repository: https://github.com/YYY-DXS/DIY-code
License: MIT (OSI-approved)
Website / download page: https://github.com/YYY-DXS/DIY-code/releases

Description:
A collection of small Windows desktop utilities and DeepSeek Harness plugins,
distributed as portable ZIP packages. All sources are in the repository; the
release binaries are built in CI by .github/workflows/build-binaries.yml.

Artifacts to be signed (all built from source in CI):
- DeepSeekHubPanel.exe  (C#, plugins/deepseek-hub/desktop/Launcher.cs)
- RAW转JPG.exe         (C#, apps/raw-to-jpg/src)
- DSH-Plugin-Pulse.exe  (Python/PyInstaller, apps/dsh-plugin-pulse)

Build: GitHub Actions, workflow "Build binaries", script tools/build/build-binaries.ps1
Roles: author / reviewer / approver: @YYY-DXS
MFA: enabled on the GitHub account
Contact: <你的邮箱>
```

## 审批通过之后

1. 接受 SignPath.io 组织邀请，建 project / signing policy / artifact configuration
2. 在 `build-binaries.yml` 里加一步，把 `dist-bin/` 上传成 signing request
   （`signpath/github-action-submit-signing-request`，用 OIDC 或 API token）
3. 每次 release 手动审批一次签名请求（条款要求，不能全自动）
4. 签名产物回填：
   - 替换仓库里的 `plugins/deepseek-hub/desktop/DeepSeekHubPanel.exe` 时，
     必须同步更新 `apps/manifest.json` 里它的 SHA256，否则更新器校验失败
   - `Release` 里的 zip 要在签名**之后**打包，再生成 `SHA256SUMS.txt`
5. 把 README 里"尚未签名"的说明改成已签名

## 备选方案

| 方案 | 成本 | 说明 |
| --- | --- | --- |
| Certum Open Source Code Signing | 约 €100–200/年 | 不看知名度，OV 级，信誉需累积数周 |
| EV 证书 | $300–700/年 | 立即获得 SmartScreen 信任，需硬件令牌/HSM |
| Azure Trusted Signing | $9.99/月 | 个人需 3 年可验证历史，暂不满足 |
