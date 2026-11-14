/**
 * Codex History Bridge — Host plugin.
 *
 * Registers two model-facing tools that shell out to the bundled Python importer
 * (`scripts/import_codex_history.py`), which does the scanning, parsing and
 * Markdown rendering. The plugin owns discovery of the Python interpreter, the
 * workspace-relative output directory, and the concise tool-result summary.
 */

import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const PLUGIN_ROOT = dirname(fileURLToPath(import.meta.url))
const SCRIPT = join(PLUGIN_ROOT, 'scripts', 'import_codex_history.py')
const MAX_CAPTURE = 8 * 1024 * 1024
const IMPORT_TIMEOUT_MS = 180000

export const name = 'codex-history-bridge'
export const inject = ['tools']

const DEFAULTS = {
  codexHome: '',
  outputDir: 'codex-history',
  pythonPath: '',
  includeArchived: true,
  includeRaw: true,
  fullToolOutputs: false,
  toolOutputLimit: 8000,
}

let cachedPython

function resolveConfig(config) {
  const merged = { ...DEFAULTS, ...(config && typeof config === 'object' ? config : {}) }
  const limit = Number(merged.toolOutputLimit)
  merged.toolOutputLimit = Number.isFinite(limit) && limit >= 0 ? Math.trunc(limit) : DEFAULTS.toolOutputLimit
  merged.includeArchived = merged.includeArchived !== false
  merged.includeRaw = merged.includeRaw !== false
  merged.fullToolOutputs = merged.fullToolOutputs === true
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
      settle({ code: -1, stdout, stderr: `${stderr}${String(error)}`, spawnError: error.code })
      settled = true
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
  add(process.env.CODEX_PYTHON)
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
  throw new Error(
    `找不到可用的 Python 3。安装 Python 3，或在插件配置里设置 pythonPath。${detail}`,
  )
}

function parsePayload(result, action) {
  const stdout = (result.stdout || '').trim()
  if (stdout) {
    try {
      return JSON.parse(stdout)
    } catch {
      /* fall through to diagnostics */
    }
  }
  const stderr = (result.stderr || '').trim()
  if (result.aborted) throw new Error(`${action}已取消`)
  if (result.timedOut) throw new Error(`${action}超时（${IMPORT_TIMEOUT_MS} ms）`)
  if (result.spawnError) throw new Error(`${action}无法启动 Python：${stderr || result.spawnError}`)
  const reason = stderr || `退出码 ${result.code}`
  throw new Error(`${action}失败：${reason.slice(0, 1500)}`)
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

function resolveOutputDir(requested, config, base) {
  const raw = (requested || config.outputDir || DEFAULTS.outputDir).trim()
  return isAbsolute(raw) ? resolve(raw) : resolve(join(base, raw))
}

async function invokeImporter(ctx, config, args, exec) {
  const cfg = resolveConfig(config)
  const base = await workspaceDirectory(ctx, exec)
  const outputDir = resolveOutputDir(args.outputDir, cfg, base)
  const python = await resolvePython(cfg)
  const argv = [SCRIPT, '--json', '--out', outputDir]
  if (cfg.codexHome) argv.push('--codex-home', cfg.codexHome)
  if (!cfg.includeArchived) argv.push('--no-archived')
  if (!cfg.includeRaw) argv.push('--no-raw')
  if (cfg.fullToolOutputs) argv.push('--full-tool-output')
  else argv.push('--tool-output-limit', String(cfg.toolOutputLimit))
  if (args.threadId) argv.push('--thread', String(args.threadId))
  if (args.dryRun) argv.push('--dry-run')
  if (args.force) argv.push('--force')
  const result = await runProcess(python, argv, IMPORT_TIMEOUT_MS, exec.signal)
  const payload = parsePayload(result, '导入')
  payload.outputDir = payload.outputDir || outputDir
  return payload
}

async function invokeStatus(ctx, config, exec) {
  const cfg = resolveConfig(config)
  const base = await workspaceDirectory(ctx, exec)
  const outputDir = resolveOutputDir(undefined, cfg, base)
  const python = await resolvePython(cfg)
  const argv = [SCRIPT, '--json', '--status', '--out', outputDir]
  if (cfg.codexHome) argv.push('--codex-home', cfg.codexHome)
  if (!cfg.includeArchived) argv.push('--no-archived')
  const result = await runProcess(python, argv, 30000, exec.signal)
  const payload = parsePayload(result, '读取状态')
  payload.outputDir = payload.outputDir || outputDir
  return payload
}

const numberFormat = new Intl.NumberFormat('zh-CN')

function textBlock(text) {
  return [{ type: 'text', text }]
}

function formatMegabytes(bytes) {
  return `${(Number(bytes || 0) / 1048576).toFixed(1)} MB`
}

function renderImport(value) {
  if (!value || value.ok === false) {
    return `导入失败：${value?.error || '未知错误'}`
  }
  const totals = value.totals || {}
  const dryRun = value.mode === 'dry-run'
  const lines = []
  lines.push(
    `${dryRun ? '预演' : '已导入'} **${numberFormat.format(totals.threads || 0)}** 个 Codex 会话` +
      `（${numberFormat.format(totals.rollouts || 0)} 个 rollout 文件，${formatMegabytes(totals.bytes)}）` +
      `到 \`${value.outputDir}\`。`,
  )
  lines.push('')
  lines.push(
    `- 轮次 ${numberFormat.format(totals.turns || 0)} · 消息 ` +
      `${numberFormat.format((totals.user || 0) + (totals.assistant || 0))} · 工具调用 ` +
      `${numberFormat.format(totals.toolCalls || 0)}`,
  )
  const written = Array.isArray(value.written) ? value.written.length : 0
  const skipped = Array.isArray(value.skipped) ? value.skipped.length : 0
  lines.push(`- ${dryRun ? '将写入' : '本次写入'} ${written} 个文件${skipped ? `，跳过 ${skipped} 个未变化会话` : ''}`)
  if (!dryRun) {
    lines.push(`- 索引：\`${join(value.outputDir, 'index.md')}\``)
  }
  const imported = Array.isArray(value.imported) ? value.imported.slice(0, 5) : []
  if (imported.length) {
    lines.push('')
    lines.push(dryRun ? '将要写入：' : '本次写入：')
    for (const thread of imported) {
      lines.push(
        `- ${thread.title} — ${numberFormat.format(thread.turns || 0)} 轮 / ` +
          `${numberFormat.format(thread.toolCalls || 0)} 次工具`,
      )
    }
    if ((value.imported || []).length > imported.length) {
      lines.push(`- 其余 ${numberFormat.format(value.imported.length - imported.length)} 个见索引`)
    }
  }
  if (Array.isArray(value.warnings) && value.warnings.length) {
    lines.push('')
    lines.push(`注意：${value.warnings.slice(0, 3).join('；')}`)
  }
  return lines.join('\n')
}

function renderStatus(value) {
  if (!value || value.ok === false) {
    return `读取失败：${value?.error || '未知错误'}`
  }
  const source = value.source || {}
  const lines = []
  lines.push(
    `Codex 本机数据：**${numberFormat.format(source.threads || 0)}** 个会话 / ` +
      `${numberFormat.format(source.files || 0)} 个 rollout / ${formatMegabytes(source.bytes)}`,
  )
  const imported = value.imported
  if (imported) {
    lines.push(
      `工作区副本：已导入 ${numberFormat.format(imported.threads || 0)} 个会话` +
        `（${imported.importedAt}）到 \`${value.outputDir}\``,
    )
  } else {
    lines.push(`工作区副本：\`${value.outputDir}\` 中还没有导入记录`)
  }
  lines.push(`待更新会话：${numberFormat.format(value.pendingThreads || 0)}`)
  return lines.join('\n')
}

const OUTPUT_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' },
    mode: { type: 'string' },
    outputDir: { type: 'string' },
    error: { type: 'string' },
  },
  additionalProperties: true,
}

function importTool(ctx, config) {
  return {
    name: 'codex_history_import',
    description:
      'Import every Codex conversation found in the local Codex home into the workspace as Markdown transcripts with an index, ' +
      'and optionally copy the original rollout JSONL. Reads the Codex home directory; it writes only inside the chosen output directory.',
    parameters: {
      type: 'object',
      properties: {
        threadId: {
          type: 'string',
          description: 'Import a single Codex thread by id (a unique prefix is enough) instead of every thread.',
        },
        dryRun: {
          type: 'boolean',
          description: 'Report the sessions and files that would be written without changing anything.',
        },
        force: {
          type: 'boolean',
          description: 'Rewrite every transcript even when its source rollout files are unchanged.',
        },
        outputDir: {
          type: 'string',
          description:
            'Directory for the generated files, relative to the session workspace or absolute. Defaults to the plugin setting (codex-history).',
        },
      },
      additionalProperties: false,
    },
    output: {
      schema: OUTPUT_SCHEMA,
      render: (_args, value) => textBlock(renderImport(value)),
    },
    timeoutMs: IMPORT_TIMEOUT_MS,
    async execute(args, exec) {
      return invokeImporter(ctx, config, args || {}, exec)
    },
  }
}

function statusTool(ctx, config) {
  return {
    name: 'codex_history_status',
    description:
      'Report the Codex conversations available in the local Codex home and what the last import wrote into the workspace, ' +
      'without changing any file. Use it to check coverage or whether Codex recorded anything new.',
    parameters: { type: 'object', properties: {}, additionalProperties: false },
    output: {
      schema: OUTPUT_SCHEMA,
      render: (_args, value) => textBlock(renderStatus(value)),
    },
    timeoutMs: 30000,
    async execute(_args, exec) {
      return invokeStatus(ctx, config, exec)
    },
  }
}

export function apply(ctx, config) {
  if (!existsSync(SCRIPT)) {
    throw new Error(`Codex History Bridge: 缺少导入脚本 ${SCRIPT}`)
  }
  ctx.tools.register(importTool(ctx, config))
  ctx.tools.register(statusTool(ctx, config))
}
