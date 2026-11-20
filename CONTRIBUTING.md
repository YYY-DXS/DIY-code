# 参与贡献

感谢你愿意花时间。这是一个个人 DIY 工具合集仓库，欢迎三类贡献：报告问题、改进文档、提交代码。

## 先看这里

| 你想 | 去哪 |
| --- | --- |
| 怎么用、能不能做某功能 | [Discussions](https://github.com/YYY-DXS/DIY-code/discussions) |
| 安全漏洞 | [SECURITY.md](SECURITY.md)，**不要**开公开 issue |
| 想加新工具 / 新插件 | 先开 issue，说清"解决谁的什么问题" |

## 仓库约定（重要）

- **只提交 Markdown 与源码**：`.md` `.js` `.mjs` `.py` `.ps1` `.cs`，以及仅作为程序入口/界面的 `.html`
- **不要提交**：`.zip` 安装包、生成的 Word/HTML 阅读版、`node_modules`、日志、个人数据
- **一个例外**：`plugins/deepseek-hub/desktop/DeepSeekHubPanel.exe` 是随包发布的启动器，哈希记录在 `apps/manifest.json`。
  不要自行重编译替换它，否则更新器的校验会失败；需要升级时同步更新 manifest 里的哈希。
- 新增桌面工具放 `apps/<工具名>/`，新增 DSH 插件放 `plugins/<插件名>/`
- 每个工具/插件必须有 `README.md`：一句话定位、截图、依赖、运行方式、已知限制
- 改了 `.md` 之后在本地重新生成阅读版：

  ```bash
  python tools/md2readable/md_to_readable.py
  ```

  生成物只给自己看，不进仓库。

## 提交流程

1. Fork，或直接在本仓库建分支：`feat/xxx`、`fix/xxx`、`docs/xxx`
2. 提交信息用"类型: 摘要"，类型取 `新增 / 修复 / 文档 / 重构 / 发布`
   例：`修复: 桌宠越界后不回到主屏`
3. 一个 PR 只做一件事；大改动先开 issue 对齐方向，免得白做
4. PR 描述写清：改了什么、为什么、怎么验证（截图或录屏更好）

## 代码要求

- 能跑：说明 Python 版本与依赖；不引入不必要的依赖，新增依赖写进 README
- 对路径、编码、权限做基本防御——Windows 中文路径是常见坑
- 涉及删除、覆盖、关机等破坏性操作，必须有确认与回滚说明
- 不要把密钥、个人路径写进代码或截图

## 发布流程（维护者）

1. 版本号遵循 SemVer：`v2.0.x` 修 bug，`v2.1.0` 加功能
2. 更新 README 的"本次收录"表与 `apps/README.md`、`plugins/README.md`
3. 打包 zip，生成 `SHA256SUMS.txt`
4. Release notes 分「新增 / 修复 / 变更」三块，写明升级注意事项
5. 打 tag 后确认 Actions 绿灯再对外宣传

## 响应预期

个人项目，通常 7 天内回复。不保证每个需求都会实现，但会说明不做的原因。

## 行为准则

参与本项目即表示同意 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
