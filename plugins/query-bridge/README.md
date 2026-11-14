# 查询桥（Query Bridge）

在对话里一句话查三件事，不用离开聊天窗口。

| 工具 | 作用 | 数据来源 |
| --- | --- | --- |
| `github_repo_status` | 仓库分支、最后推送、star/fork、未关闭 issue/PR、最近提交、Actions 运行、release | GitHub 公开 API（无需登录，公开仓库 60 次/小时） |
| `deepseek_account_status` | 余额（总额/赠送/充值）、账户是否可用、可用模型 | `api.deepseek.com`，需要 DeepSeek API key |
| `workspace_history_search` | 在已导入的 Codex 会话转录和归档对话目录里全文检索，返回命中的会话与片段 | 工作区里的 `codex-history/threads/*.md` 与 `codex/index.json` |

## 密钥

DeepSeek 的 key 按以下顺序查找，命中即用：

1. 环境变量 `DEEPSEEK_API_KEY`
2. 插件配置里的 `apiKeyFile`（默认 `%USERPROFILE%\Desktop\api.txt`）
3. `%USERPROFILE%\Desktop\api.txt`
4. 工作区里的 `codex/api.txt`（旧位置，仅兼容）

把 key 写成一行 `sk-...` 即可，后面带中文备注也能识别。**不要把这个文件放进任何仓库。**

## 配置

`cordis.patch.yml` 里可以改：

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `githubRepo` | `YYY-DXS/DIY-code` | 默认查询的仓库，`OWNER/NAME` |
| `commits` | `6` | 默认列出的最近提交数 |
| `runs` | `3` | 默认列出的 Actions 运行数 |
| `searchLimit` | `8` | 检索默认返回条数 |
| `apiKeyFile` | 桌面 `api.txt` | DeepSeek key 文件 |
| `historyDir` | `codex-history/threads` | 会话转录目录（相对工作区） |
| `archiveDir` | `codex` | 归档对话目录（相对工作区） |
| `pythonPath` | 空 | 指定 Python 解释器；留空自动探测 |

## 实现

- `index.js`：Host 插件，注册三个工具，负责 Python 探测、工作区路径解析和中文摘要渲染。
- `scripts/query.py`：查询引擎，只输出 JSON；`github` / `deepseek` / `search` 三个子命令可直接单独运行调试：

```powershell
python scripts\query.py github --repo YYY-DXS/DIY-code --commits 5
python scripts\query.py deepseek
python scripts\query.py search --query 萝卜刀 --limit 5 --history C:\path\to\threads
```
