/**
 * Query Bridge — Host plugin.
 *
 * Registers three model-facing query tools that shell out to the bundled
 * Python engine (`scripts/query.py`):
 *
 *   github_repo_status       — public GitHub repository state (no login needed)
 *   deepseek_account_status  — DeepSeek balance and available models
 *   workspace_history_search — full-text search over the imported Codex
 *                              transcripts and the archived conversation folders
 *
 * The plugin owns Python discovery, workspace resolution and the concise
 * Chinese rendering; the engine owns the network and file work.
 */

import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const PLUGIN_ROOT = dirname(fileURLToPath(import.meta.url))
const SCRIPT = join(PLUGIN_ROOT, 'scripts', 'query.py')
const MAX_CAPTURE = 8 * 1024 * 1024

export const name = 'query-bridge'
export const inject = ['tools']

const DEFAULTS = {
  githubRepo: 'YYY-DXS/DIY-code',
  commits: 6,
  runs: 3,
  searchLimit: 8,
  apiKeyFile: '',
  historyDir: 'codex-history/threads',
  archiveDir: 'codex',
  pythonPath: '',
}

let cachedPython

function resolveConfig(config) {
  const merged = { ...DEFAULTS, ...(config && typeof config === 'object' ? config : {}) }
  const clamp = (value, fallback, min, max) => {
    const num = Number(value)
    if (!Number.isFinite(num)) return fallback
    return Math.min(max, Math.max(min, Math.trunc(num)))
  }
  merged.commits = clamp(merged.commits, DEFAULTS.commits, 1, 30)
  merged.runs = clamp(merged.runs, DEFAULTS.runs, 1, 10)
  merged.searchLimit = clamp(merged.searchLimit, DEFAULTS.searchLimit, 1, 50)
  merged.githubRepo = String(merged.githubRepo || '').trim()
  merged.historyDir = String(merged.historyDir || DEFAULTS.historyDir).trim()
  merged.archiveDir = String(merged.archiveDir || DEFAULTS.archiveDir).trim()
  return merged
}

function runProcess(candidate, args, timeoutMs, signal) {
  return new Promise((settle) => {
    let child
    try {
      child = spawn(candidate.command, [...candidate.args, ...args], {
        windowsHide: true,
        env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
      })
    } catch (error) {
      settle({ code: -1, stdout: '', stderr: String(error), spawnError: error.code })
      return
    }

    let stdout = ''
    let stderr = ''
    let settled = false
    let timer

    const finish = (payload) => {
      if (settled) return
      settled = true
      if (timer) clearTimeout(timer)
      if (signal && typeof signal.removeEventListener === 'function') {
        signal.removeEventListener('abort', onAbort)
      }
      settle(payload)
    }
    const onAbort = () => {
      try {
        child.kill()
      } catch {
        /* already gone */
      }
      finish({ code: -1, stdout, stderr: `${stderr}\n[已取消]`, aborted: true })
    }

    if (signal) {
      if (signal.aborted) {
        onAbort()
        return
      }
      signal.addEventListener('abort', onAbort, { once: true })
    }

    timer = setTimeout(() => {
      try {
        child.kill()
      } catch {
        /* already gone */
      }
      finish({ code: -1, stdout, stderr: `${stderr}\n[超时 ${timeoutMs} ms]`, timedOut: true })
    }, timeoutMs)
    if (typeof timer.unref === 'function') timer.unref()

    child.stdout?.on('data', (chunk) => {
      if (stdout.length < MAX_CAPTURE) stdout += chunk.toString('utf8')
    })
    child.stderr?.on('data', (chunk) => {
      if (stderr.length < MAX_CAPTURE) stderr += chunk.toString('utf8')
    })
    child.on('error', (error) => {
      settled = true
      settle({ code: -1, stdout, stderr: `${stderr}${String(error)}`, spawnError: error.code })
    })
    child.on('close', (code) => finish({ code: code ?? -1, stdout, stderr }))
  })
}

async function resolvePython(config) {
  if (cachedPython) return cachedPython
  const candidates = []
  const add = (command, args = []) => {
    if (typeof command === 'string' && command.trim()) candidates.push({ command, args })
  }
  add(config.pythonPath)
  add(process.env.DSH_PYTHON)
  add(process.env.PYTHON)
  add('python')
  add('python3')
  add('py', ['-3'])
  if (process.env.DSH_HOME) {
    add(join(process.env.DSH_HOME, 'dsh-runtimes', 'dsh-primary-runtime', 'dependencies', 'python', 'python.exe'))
  }
  if (process.platform === 'win32' && process.env.LOCALAPPDATA) {
    add(join(process.env.LOCALAPPDATA, 'Programs', 'Python', 'Python312', 'python.exe'))
  }

  const failures = []
  for (const candidate of candidates) {
    const probe = await runProcess(candidate, ['-c', 'import sys;print(sys.version_info[0])'], 8000)
    if (probe.spawnError === 'ENOENT' || probe.spawnError === 'EACCES') continue
    if (probe.code === 0 && probe.stdout.trim() === '3') {
      cachedPython = candidate
      return candidate
    }
    failures.push(`${candidate.command}: ${probe.stderr.trim().split('\n')[0] || `exit ${probe.code}`}`)
  }
  const detail = failures.length ? `（已尝试：${failures.join('；')}）` : ''
  throw new Error(`找不到可用的 Python 3。安装 Python 3，或在插件配置里设置 pythonPath。${detail}`)
}

async function workspaceDirectory(ctx, exec) {
  try {
    const service = ctx.get('workingDirectory')
    if (service && exec.agent) {
      const directory = await service.ensure(exec.agent, exec.signal)
      if (typeof directory === 'string' && directory) return directory
    }
  } catch {
    /* fall back to the Host process directory */
  }
  return process.cwd()
}

function resolveInWorkspace(requested, base) {
  const raw = String(requested || '').trim()
  if (!raw) return base
  return isAbsolute(raw) ? resolve(raw) : resolve(join(base, raw))
}

async function runEngine(ctx, config, argv, exec, timeoutMs) {
  const cfg = resolveConfig(config)
  const base = await workspaceDirectory(ctx, exec)
  const python = await resolvePython(cfg)
  const result = await runProcess(python, [SCRIPT, '--workspace', base, ...argv], timeoutMs, exec.signal)
  const stdout = (result.stdout || '').trim()
  if (stdout) {
    try {
      return JSON.parse(stdout)
    } catch {
      /* fall through to diagnostics */
    }
  }
  if (result.aborted) throw new Error('查询已取消')
  if (result.timedOut) throw new Error(`查询超时（${timeoutMs} ms）`)
  if (result.spawnError) throw new Error(`无法启动 Python：${result.stderr || result.spawnError}`)
  const reason = (result.stderr || '').trim() || `退出码 ${result.code}`
  throw new Error(`查询失败：${reason.slice(0, 1200)}`)
}

// ------------------------------------------------------------------ render

function textBlock(text) {
  return [{ type: 'text', text }]
}

function renderGithub(value) {
  if (!value || value.ok === false) {
    return `查询失败：${value?.error || '未知错误'}`
  }
  const lines = []
  lines.push(`**[${value.repo}](${value.url})** · ${value.private ? '私有' : '公开'} · ${value.license || '无协议'}`)
  lines.push(
    `默认分支 \`${value.branch}\` · 建库 ${value.created} · 最后推送 ${value.pushed}` +
      `${value.archived ? ' · 已归档' : ''}`,
  )
  lines.push(
    `star ${value.stars} · fork ${value.forks} · 未关闭 issue/PR ${value.openIssues} · ` +
      `${value.size} · ${value.language || '—'}`,
  )
  const commits = value.commits || []
  if (commits.length) {
    lines.push('')
    lines.push('最近提交：')
    for (const commit of commits) {
      lines.push(`- \`${commit.sha}\` ${commit.date} ${commit.message}`)
    }
  }
  const runs = value.runs || []
  lines.push('')
  if (runs.length) {
    lines.push('Actions：')
    for (const run of runs) {
      lines.push(`- ${run.date} \`${run.state}\` ${run.name}`)
    }
  } else {
    lines.push('Actions：没有运行记录（或未启用工作流）')
  }
  const releases = value.releases || []
  if (releases.length) {
    lines.push('发布：')
    for (const release of releases) {
      lines.push(`- ${release.tag} · ${release.date} · ${release.name || '—'}`)
    }
  } else {
    lines.push('发布：暂无 release')
  }
  return lines.join('\n')
}

function renderDeepseek(value) {
  if (!value || value.ok === false) {
    const hint = value?.hint ? `\n${value.hint}` : ''
    return `查询失败：${value?.error || '未知错误'}${hint}`
  }
  const lines = []
  lines.push(`密钥 \`${value.keyMasked}\`（来源：${value.keySource}）`)
  lines.push(`余额可用：${value.available ? '是' : '否'}`)
  for (const item of value.balances || []) {
    lines.push(
      `- ${item.currency}：总额 **${item.total}**` + `（赠送 ${item.granted} / 充值 ${item.toppedUp}）`,
    )
  }
  if ((value.models || []).length) {
    lines.push(`可用模型：${value.models.join('、')}`)
  } else if (value.modelsError) {
    lines.push(value.modelsError)
  }
  return lines.join('\n')
}

function renderSearch(value) {
  if (!value || value.ok === false) {
    return `查询失败：${value?.error || '未知错误'}`
  }
  const lines = []
  const transcripts = value.transcripts || []
  const archive = value.archive || []
  lines.push(
    `「${value.query}」命中 **${value.transcriptTotal}** 篇会话转录、**${value.archiveTotal}** 个归档对话`,
  )
  if (transcripts.length) {
    lines.push('')
    lines.push('会话转录：')
    for (const item of transcripts) {
      lines.push(`- ${item.title} — ${item.matches} 处 · \`${item.file}\``)
      for (const snippet of item.snippets || []) {
        lines.push(`  > ${snippet}`)
      }
    }
    if (value.transcriptTotal > transcripts.length) {
      lines.push(`- 其余 ${value.transcriptTotal - transcripts.length} 篇见 \`codex-history/index.md\``)
    }
  }
  if (archive.length) {
    lines.push('')
    lines.push('归档对话文件夹：')
    for (const item of archive) {
      lines.push(`- ${item.date}/${item.name} · ${item.files} 个文件 · ${item.size} · \`${item.path}\``)
    }
    if (value.archiveTotal > archive.length) {
      lines.push(`- 其余 ${value.archiveTotal - archive.length} 个见 \`codex/README.md\``)
    }
  }
  if (!transcripts.length && !archive.length) {
    lines.push('')
    lines.push('没有命中。可以换关键词，或先用 `codex_history_status` 确认导入状态。')
  }
  return lines.join('\n')
}

// ------------------------------------------------------------------ tools

const OUTPUT_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' },
    error: { type: 'string' },
  },
  additionalProperties: true,
}

function githubTool(ctx, config) {
  const cfg = resolveConfig(config)
  return {
    name: 'github_repo_status',
    description:
      'Report the live state of a GitHub repository through the public API: default branch, last push, stars/forks, ' +
      'open issue and PR count, recent commits, recent Actions runs, and latest releases. Works without any login ' +
      'for public repositories; use it whenever the user asks about a repo, its recent activity, or CI status.',
    parameters: {
      type: 'object',
      properties: {
        repo: {
          type: 'string',
          description: `Repository as OWNER/NAME or a github.com URL. Defaults to the configured repo (${cfg.githubRepo || 'none'}).`,
        },
        commits: {
          type: 'number',
          description: `How many recent commits to list (1-30). Defaults to ${cfg.commits}.`,
        },
        runs: {
          type: 'number',
          description: `How many recent Actions runs to list (1-10). Defaults to ${cfg.runs}.`,
        },
      },
      additionalProperties: false,
    },
    output: {
      schema: OUTPUT_SCHEMA,
      render: (_args, value) => textBlock(renderGithub(value)),
    },
    timeoutMs: 30000,
    async execute(args, exec) {
      const repo = String(args?.repo || '').trim() || cfg.githubRepo
      if (!repo) throw new Error('没有指定仓库：在参数里给 OWNER/NAME，或在插件配置里设置 githubRepo。')
      const commits = args?.commits ?? cfg.commits
      const runs = args?.runs ?? cfg.runs
      return runEngine(
        ctx,
        config,
        ['github', '--repo', repo, '--commits', String(commits), '--runs', String(runs)],
        exec,
        30000,
      )
    },
  }
}

function deepseekTool(ctx, config) {
  return {
    name: 'deepseek_account_status',
    description:
      'Report the DeepSeek account balance and the model ids the stored API key can use. Reads the key from the ' +
      'DEEPSEEK_API_KEY environment variable or from the configured key file (by default Desktop\\api.txt). ' +
      'Use it when the user asks about their DeepSeek balance, remaining credit, or available models.',
    parameters: { type: 'object', properties: {}, additionalProperties: false },
    output: {
      schema: OUTPUT_SCHEMA,
      render: (_args, value) => textBlock(renderDeepseek(value)),
    },
    timeoutMs: 30000,
    async execute(_args, exec) {
      const cfg = resolveConfig(config)
      const argv = ['deepseek']
      if (cfg.apiKeyFile) argv.push('--key-file', cfg.apiKeyFile)
      return runEngine(ctx, config, argv, exec, 30000)
    },
  }
}

function searchTool(ctx, config) {
  const cfg = resolveConfig(config)
  return {
    name: 'workspace_history_search',
    description:
      'Full-text search over the imported Codex conversation transcripts and the archived conversation folders in the ' +
      'workspace. Returns the matching conversations with line snippets and hit counts, so past discussions can be ' +
      'retrieved by topic, file name, date, or keyword instead of reading every transcript.',
    parameters: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'Keyword or phrase to look for (case-insensitive, literal).' },
        limit: {
          type: 'number',
          description: `Maximum number of transcripts and archived folders to return (1-50). Defaults to ${cfg.searchLimit}.`,
        },
      },
      required: ['query'],
      additionalProperties: false,
    },
    output: {
      schema: OUTPUT_SCHEMA,
      render: (_args, value) => textBlock(renderSearch(value)),
    },
    timeoutMs: 60000,
    async execute(args, exec) {
      const query = String(args?.query || '').trim()
      if (!query) throw new Error('搜索词不能为空')
      const base = await workspaceDirectory(ctx, exec)
      const argv = [
        'search',
        '--query',
        query,
        '--limit',
        String(args?.limit ?? cfg.searchLimit),
        '--history',
        resolveInWorkspace(cfg.historyDir, base),
        '--archive',
        resolveInWorkspace(cfg.archiveDir, base),
      ]
      return runEngine(ctx, config, argv, exec, 60000)
    },
  }
}

export function apply(ctx, config) {
  if (!existsSync(SCRIPT)) {
    throw new Error(`Query Bridge: 缺少查询脚本 ${SCRIPT}`)
  }
  ctx.tools.register(githubTool(ctx, config))
  ctx.tools.register(deepseekTool(ctx, config))
  ctx.tools.register(searchTool(ctx, config))
}
