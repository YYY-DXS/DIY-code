# Codex History Bridge

把本机 Codex（CLI / Desktop）的全部会话历史导入 DSH 工作区：每个会话一份 Markdown 逐字记录，外加总览索引，并可保留原始 rollout JSONL。

## 它提供什么

| 工具 | 作用 |
| --- | --- |
| `codex_history_import` | 扫描 Codex 数据目录，生成/增量更新工作区副本 |
| `codex_history_status` | 只读报告：本机有多少会话、上次导入了什么、有无新记录 |

导入结果默认写到会话工作区的 `codex-history/`：

```text
codex-history/
├── README.md            说明与统计
├── index.md             会话总览（日期 / 标题 / 轮次 / 工具数）
├── index.json           机器可读索引
├── threads/*.md         每个会话一份逐字记录
├── raw/                 Codex 原始 JSONL 副本（--no-raw 可关闭）
└── .codex-import.json   增量状态（源文件大小/修改时间）
```

Markdown 记录包含用户消息、助手回复、推理（折叠）、工具调用与输出（折叠、默认超过 8000 字符截断）。

## 插件配置

在 profile 的 `cordis.patch.yml` 中该行的 `config` 里可改：

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `codexHome` | `''` | Codex 数据目录；留空用 `$CODEX_HOME` 或 `~/.codex` |
| `outputDir` | `codex-history` | 输出目录，相对工作区或绝对路径 |
| `pythonPath` | `''` | 指定 Python 3；留空自动探测 |
| `includeArchived` | `true` | 是否包含 `archived_sessions/` |
| `includeRaw` | `true` | 是否复制原始 JSONL |
| `fullToolOutputs` | `false` | 工具输出不截断 |
| `toolOutputLimit` | `8000` | 工具输出截断上限（字符） |

## 导入引擎（Python）

Cordis 插件入口必须是 JS 模块，实际扫描/解析/渲染由 `scripts/import_codex_history.py` 完成（仅标准库，可独立运行）：

```text
python scripts/import_codex_history.py --out ./codex-history             # 导入/增量更新
python scripts/import_codex_history.py --out ./codex-history --status    # 只看状态
python scripts/import_codex_history.py --out ./codex-history --dry-run   # 预演
python scripts/import_codex_history.py --out ./codex-history --force     # 全部重生成
python scripts/import_codex_history.py --out ./codex-history --thread 01a0db94   # 只导一个会话
```

## 注意

- 只读取 Codex 数据目录，写入仅发生在输出目录内；不会修改 Codex 自身的数据。
- `raw/` 是会话原文的字节级副本，可能包含会话里出现过的密钥、令牌或隐私内容，分享工作区前请先检查。
- 开发者/系统注入上下文（developer 消息、`<environment_context>`）不进入正文，仍在 `raw/` 中。
- 同一会话的多次续接 rollout 会按时间合并为一份记录，重复注入的开场请求会去重。
