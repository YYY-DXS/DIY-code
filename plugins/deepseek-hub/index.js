/**
 * DeepSeek Hub — Host plugin.
 *
 * 把 DeepSeek 网页对话同步成本地 Markdown 知识库，并提供 GitHub 发布入口。
 *
 * 工具：
 *   deepseek_status   — 知识库/浏览器配置/最近同步时间
 *   deepseek_sync     — 立即同步（可限制条数、强制重抓）
 *   github_publish    — 跑一次自动发布（可 dryRun）
 *   hub_doctor        — 自检：浏览器、知识库、git、仓库、Python
 *
 * 同步引擎是 `scripts/hub-sync.mjs`：它用 CDP 驱动一个专用 Edge profile，
 * 读网页自己收到的响应体（不重放请求、不保存 token），再渲染成 Markdown。
 */

import { spawn } from 'node:child_process'
import { existsSync, readFileSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = dirname(fileURLToPath(import.meta.url))
const SYNC_SCRIPT = join(ROOT, 'scripts', 'hub-sync.mjs')

export const name = 'deepseek-hub'
export const inject = ['tools', 'timer']

const GIT_DIR = 'C:\\Program Files\\Git\\cmd'
const USER_HOME = process.env.USERPROFILE || process.env.HOME || ''

const DEFAULTS = {
  knowledgeDir:
    process.env.DEEPSEEK_HUB_KNOWLEDGE ||
    join(USER_HOME || '.', 'Documents', 'deepseek-hub', 'knowledge'),
  profileDir:
    process.env.DEEPSEEK_HUB_PROFILE ||
    join(USER_HOME || '.', '.deepseek-hub', 'edge-profile'),
  edgePath:
    process.env.DEEPSEEK_HUB_EDGE ||
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  repoDir: process.env.DEEPSEEK_HUB_REPO || process.cwd(),
  pythonPath: process.env.DEEPSEEK_HUB_PYTHON || '',
  port: 9390,
  autoSyncMinutes: 60,
  dailyPublishAt: '20:00',
  syncTimeoutMs: 900000,
  publishTimeoutMs: 300000,
}

function resolveConfig(config) {
  const merged = { ...DEFAULTS, ...(config && typeof config === 'object' ? config : {}) }
  merged.port = Number(merged.port) || DEFAULTS.port
  merged.autoSyncMinutes = Number(merged.autoSyncMinutes ?? DEFAULTS.autoSyncMinutes)
  merged.syncTimeoutMs = Number(merged.syncTimeoutMs) || DEFAULTS.syncTimeoutMs
  return merged
}

// ---------------------------------------------------------------- 进程执行

function run(file, args, options = {}) {
  const { timeoutMs = 120000, env, cwd, signal } = options
  return new Promise((settle) => {
    let child
    try {
      child = spawn(file, args, {
        windowsHide: true,
        cwd: cwd || undefined,
        env: env || process.env,
      })
    } catch (error) {
      settle({ code: -1, stdout: '', stderr: String(error) })
      return
    }
    let stdout = ''
    let stderr = ''
    let done = false
    const finish = (payload) => {
      if (done) return
      done = true
      clearTimeout(timer)
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
      finish({ code: -1, stdout, stderr: `${stderr}\n[已取消]` })
    }
    const timer = setTimeout(() => {
      try {
        child.kill()
      } catch {
        /* already gone */
      }
      finish({ code: -1, stdout, stderr: `${stderr}\n[超时 ${Math.round(timeoutMs / 1000)}s]` })
    }, timeoutMs)
    if (signal && typeof signal.addEventListener === 'function') {
      signal.addEventListener('abort', onAbort)
    }
    child.stdout?.on('data', (d) => {
      stdout += d
    })
    child.stderr?.on('data', (d) => {
      stderr += d
    })
    child.on('error', (error) => finish({ code: -1, stdout, stderr: stderr + String(error) }))
    child.on('close', (code) => finish({ code, stdout, stderr }))
  })
}

// Electron 主进程用 ELECTRON_RUN_AS_NODE 跑 .mjs，子进程会正常等待
function runNodeScript(script, args, options = {}) {
  return run(process.execPath, [script, ...args], {
    ...options,
    env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' },
  })
}

// ---------------------------------------------------------------- 状态

function readManifest(cfg) {
  const path = join(cfg.knowledgeDir, 'data', 'manifest.json')
  if (!existsSync(path)) return null
  try {
    return JSON.parse(readFileSync(path, 'utf8'))
  } catch {
    return null
  }
}

function summarize(cfg) {
  const manifest = readManifest(cfg)
  const conversations = Object.values(manifest?.conversations || {})
  const messages = conversations.reduce((sum, c) => sum + (c.messages || 0), 0)
  const lastSync = conversations.reduce((max, c) => Math.max(max, c.synced_at || 0), 0)
  return {
    knowledgeDir: cfg.knowledgeDir,
    conversations: conversations.length,
    messages,
    lastSync,
    profileOk: existsSync(join(cfg.profileDir, 'Default')),
    edgeOk: existsSync(cfg.edgePath),
  }
}

function fmtTime(seconds) {
  if (!seconds) return '从未'
  const d = new Date(seconds * 1000)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function parseSyncResult(stdout) {
  const line = String(stdout)
    .split(/\r?\n/)
    .reverse()
    .find((l) => /完成：新同步/.test(l))
  if (!line) return { summary: '同步结束（未识别到统计行）', raw: String(stdout).slice(-2000) }
  const m = /新同步 (\d+)，跳过 (\d+)，失败 (\d+)/.exec(line)
  return {
    synced: m ? Number(m[1]) : 0,
    skipped: m ? Number(m[2]) : 0,
    failed: m ? Number(m[3]) : 0,
    summary: line.trim(),
  }
}

// ---------------------------------------------------------------- 渲染

let persistState = () => {}

function textBlock(text) {
  return [{ type: 'text', text }]
}

const OUTPUT_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' },
    error: { type: 'string' },
  },
  additionalProperties: true,
}

function renderSync(value) {
  if (!value || value.ok === false) return `同步失败：${value?.error || '未知错误'}`
  const lines = [`**同步完成** · ${value.summary}`]
  lines.push(`- 知识库：${value.conversations} 个会话 / ${value.messages} 条消息`)
  lines.push(`- 输出目录：\`${value.knowledgeDir}\``)
  if (value.logTail) lines.push('', '```', value.logTail.trim(), '```')
  return lines.join('\n')
}

function renderStatus(value) {
  if (!value || value.ok === false) return `读取状态失败：${value?.error || '未知错误'}`
  return [
    '**DeepSeek Hub 状态**',
    `- 会话/消息：${value.conversations} / ${value.messages}`,
    `- 最近同步：${fmtTime(value.lastSync)}`,
    `- 专用浏览器配置：${value.profileOk ? '就绪' : '缺失（需要重新登录一次）'}`,
    `- Edge：${value.edgeOk ? '已找到' : '未找到'}`,
    `- 自动同步：${value.autoSyncMinutes > 0 ? `每 ${value.autoSyncMinutes} 分钟` : '关闭'}`,
    `- 知识库：\`${value.knowledgeDir}\``,
  ].join('\n')
}

function renderDoctor(value) {
  if (!value) return '自检失败'
  const lines = ['**Hub 自检**', '']
  for (const item of value.checks) {
    lines.push(`- ${item.ok ? '✅' : '❌'} ${item.name}：${item.detail}`)
  }
  lines.push('', value.ok ? '全部通过。' : '有项目未通过，按上面提示修。')
  return lines.join('\n')
}

function renderPublish(value) {
  if (!value) return '发布失败'
  const head = value.dryRun ? '**发布预演（不写文件、不推送）**' : '**发布结果**'
  return [head, '', '```', (value.output || '').trim().split(/\r?\n/).slice(-40).join('\n'), '```'].join('\n')
}

// ---------------------------------------------------------------- 工具

function statusTool(cfg) {
  return {
    name: 'deepseek_status',
    description:
      'Report the DeepSeek Hub state: how many web conversations and messages are in the local knowledge base, ' +
      'when it was last synced, whether the dedicated browser profile still exists, and whether automatic sync is on.',
    parameters: { type: 'object', properties: {}, additionalProperties: false },
    output: { schema: OUTPUT_SCHEMA, render: (_a, v) => textBlock(renderStatus(v)) },
    timeoutMs: 15000,
    async execute() {
      const s = summarize(cfg)
      return { ok: true, ...s, autoSyncMinutes: cfg.autoSyncMinutes }
    },
  }
}

function syncTool(cfg, state) {
  return {
    name: 'deepseek_sync',
    description:
      'Sync DeepSeek web conversations into the local Markdown knowledge base right now. It launches the dedicated ' +
      'Edge profile, lets the web app fetch its own data, reads the responses it received, and renders Markdown. ' +
      'Only conversations whose remote updated_at is newer are re-fetched unless force is set.',
    parameters: {
      type: 'object',
      properties: {
        limit: { type: 'number', description: 'Only sync the first N conversations (for a quick test). Default: all.' },
        force: { type: 'boolean', description: 'Re-fetch every conversation even if it looks unchanged.' },
        visible: { type: 'boolean', description: 'Show the browser window while syncing. Default false.' },
      },
      additionalProperties: false,
    },
    output: { schema: OUTPUT_SCHEMA, render: (_a, v) => textBlock(renderSync(v)) },
    timeoutMs: cfg.syncTimeoutMs + 30000,
    async execute(args, exec) {
      if (state.running) throw new Error('已有同步任务在跑，等它结束。')
      const argv = [
        '--port', String(cfg.port),
        '--profile', cfg.profileDir,
        '--out', cfg.knowledgeDir,
        '--edge', cfg.edgePath,
      ]
      if (Number(args?.limit) > 0) argv.push('--limit', String(Number(args.limit)))
      if (args?.force) argv.push('--force')
      if (!args?.visible) argv.push('--hidden')

      state.running = true
      try {
        const r = await runNodeScript(SYNC_SCRIPT, argv, {
          timeoutMs: cfg.syncTimeoutMs,
          signal: exec?.signal,
        })
        const parsed = parseSyncResult(r.stdout)
        const s = summarize(cfg)
        const ok = r.code === 0
        state.lastSyncAt = Date.now() / 1000
        if (!ok) state.lastError = String(r.stderr || r.stdout).slice(-500)
        if (!ok) {
          return {
            ok: false,
            error: (r.stderr || r.stdout || `退出码 ${r.code}`).slice(-1500),
            ...s,
          }
        }
        return {
          ok: true,
          ...parsed,
          ...s,
          knowledgeDir: cfg.knowledgeDir,
          logTail: String(r.stdout).trim().split(/\r?\n/).slice(-6).join('\n'),
        }
      } finally {
        state.running = false
        persistState()
      }
    },
  }
}

async function runPublish(cfg, { dryRun = false, minScore = 6, signal } = {}) {
  const script = join(cfg.repoDir, 'tools', 'auto-publish', 'auto_publish.py')
  if (!existsSync(script)) return { ok: false, output: `找不到发布脚本：${script}` }
  // 先把手上的 chats/*.json 汇总成 auto_publish 需要的 messages.jsonl
  const jsonl = await runNodeScript(join(ROOT, 'scripts', 'build-jsonl.mjs'), [cfg.knowledgeDir], {
    timeoutMs: 60000,
    signal,
  })
  if (jsonl.code !== 0) {
    return { ok: false, output: `汇总 messages.jsonl 失败：${jsonl.stderr || jsonl.stdout}` }
  }
  const argv = [
    script,
    '--repo', cfg.repoDir,
    '--kb', cfg.knowledgeDir,
    '--min-score', String(minScore),
    '--allow-public',
  ]
  if (dryRun) argv.push('--dry-run')
  const env = {
    ...process.env,
    PYTHONIOENCODING: 'utf-8',
    PYTHONUTF8: '1',
    PATH: `${GIT_DIR};${process.env.PATH || ''}`,
  }
  const r = await run(cfg.pythonPath || 'python', argv, {
    timeoutMs: cfg.publishTimeoutMs,
    env,
    cwd: cfg.repoDir,
    signal,
  })
  return { ok: r.code === 0, dryRun, output: `${r.stdout}\n${r.stderr}` }
}

function publishTool(cfg, state) {
  return {
    name: 'github_publish',
    description:
      'Run the DIY auto-publish pipeline: score new DeepSeek conversations, generate project drafts, redact private ' +
      'content, commit and push to the GitHub repository. Use dryRun to preview without writing or pushing.',
    parameters: {
      type: 'object',
      properties: {
        dryRun: { type: 'boolean', description: 'Only preview which conversations would be published.' },
        minScore: { type: 'number', description: 'Score threshold, default 6.' },
      },
      additionalProperties: false,
    },
    output: { schema: OUTPUT_SCHEMA, render: (_a, v) => textBlock(renderPublish(v)) },
    timeoutMs: cfg.publishTimeoutMs + 30000,
    async execute(args, exec) {
      const result = await runPublish(cfg, {
        dryRun: !!args?.dryRun,
        minScore: Number(args?.minScore) || 6,
        signal: exec?.signal,
      })
      state.lastPublish = { at: Date.now() / 1000, ok: result.ok, dryRun: !!args?.dryRun }
      if (!result.ok) state.lastError = String(result.output || '').slice(-500)
      persistState()
      return result
    },
  }
}

function doctorTool(cfg) {  return {
    name: 'hub_doctor',
    description:
      'Check DeepSeek Hub prerequisites one by one: knowledge base, dedicated browser profile, Edge, Git, the publish ' +
      'repository, and Python. Reports exactly which piece is missing.',
    parameters: { type: 'object', properties: {}, additionalProperties: false },
    output: { schema: OUTPUT_SCHEMA, render: (_a, v) => textBlock(renderDoctor(v)) },
    timeoutMs: 30000,
    async execute() {
      const checks = []
      const add = (name, ok, detail) => checks.push({ name, ok, detail })
      const s = summarize(cfg)
      add('知识库', existsSync(join(cfg.knowledgeDir, 'data', 'manifest.json')), `${s.conversations} 会话 / ${s.messages} 消息`)
      add('浏览器 profile', s.profileOk, cfg.profileDir)
      add('Edge', s.edgeOk, cfg.edgePath)
      add('Git', existsSync(join(GIT_DIR, 'git.exe')), join(GIT_DIR, 'git.exe'))
      const gitDir = join(cfg.repoDir, '.git')
      add('发布仓库', existsSync(gitDir), cfg.repoDir)
      const py = cfg.pythonPath || 'python'
      add('Python', existsSync(py), py)
      const script = join(cfg.repoDir, 'tools', 'auto-publish', 'auto_publish.py')
      add('发布脚本', existsSync(script), script)
      return { ok: checks.every((c) => c.ok), checks }
    },
  }
}

function panelTool(cfg) {
  return {
    name: 'hub_panel',
    description:
      'Open the native (non-web) DeepSeek Hub status window on this desktop: conversation/message counts, sync state, ' +
      'last sync and last publish, refreshed every few seconds from local files.',
    parameters: { type: 'object', properties: {}, additionalProperties: false },
    output: { schema: OUTPUT_SCHEMA, render: (_a, v) => textBlock(v.message || '') },
    timeoutMs: 15000,
    async execute() {
      const script = join(ROOT, 'desktop', 'HubPanel.ps1')
      if (!existsSync(script)) return { ok: false, message: `找不到面板脚本：${script}` }
      const child = spawn(
        'powershell.exe',
        ['-NoProfile', '-WindowStyle', 'Hidden', '-ExecutionPolicy', 'Bypass', '-File', script, '-Knowledge', cfg.knowledgeDir, '-Repo', cfg.repoDir],
        { detached: true, stdio: 'ignore', windowsHide: true },
      )
      child.unref()
      return { ok: true, message: `已打开原生状态面板（数据来自 ${cfg.knowledgeDir}）` }
    },
  }
}

// ---------------------------------------------------------------- 状态面板

const PANEL_HTML = `<!doctype html>
<html lang="zh-CN"><meta charset="utf-8">
<title>DeepSeek Hub</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root { color-scheme: dark }
  body { margin:0; font:15px/1.7 system-ui,"Segoe UI",sans-serif; background:#0f1115; color:#e6e8ee }
  main { max-width:760px; margin:0 auto; padding:40px 24px }
  h1 { font-size:22px; margin:0 0 4px }
  .sub { color:#8b93a7; font-size:13px; margin-bottom:24px }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px }
  .card { background:#171a21; border:1px solid #232833; border-radius:12px; padding:14px 16px }
  .k { color:#8b93a7; font-size:12px; letter-spacing:.4px; text-transform:uppercase }
  .v { font-size:24px; font-weight:600; margin-top:2px }
  .row { display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #1e222b }
  .row:last-child { border-bottom:0 }
  .dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; background:#3ddc84 }
  .dot.bad { background:#ff5f57 }
  .dot.run { background:#ffbd2e }
  .err { color:#ff8a80; font-size:13px; white-space:pre-wrap; word-break:break-all }
  footer { color:#6b7387; font-size:12px; margin-top:28px }
  a { color:#7aa2ff }
</style>
<main>
  <h1>DeepSeek Hub</h1>
  <div class="sub">网页对话 → 本地知识库 → GitHub，全程自动</div>
  <div class="grid">
    <div class="card"><div class="k">会话</div><div class="v" id="convs">–</div></div>
    <div class="card"><div class="k">消息</div><div class="v" id="msgs">–</div></div>
    <div class="card"><div class="k">同步状态</div><div class="v" id="state" style="font-size:16px">–</div></div>
  </div>
  <div style="margin-top:22px" class="card">
    <div class="row"><span>最近同步</span><span id="lastSync">–</span></div>
    <div class="row"><span>最近发布</span><span id="lastPub">–</span></div>
    <div class="row"><span>自动同步</span><span id="auto">–</span></div>
    <div class="row"><span>每日发布</span><span id="daily">–</span></div>
    <div class="row"><span>浏览器配置</span><span id="profile">–</span></div>
  </div>
  <div id="err" class="err" style="margin-top:14px"></div>
  <footer>每 5 秒自动刷新 · <a href="/deepseek-hub/status">原始 JSON</a></footer>
</main>
<script>
const pad = (n) => String(n).padStart(2, '0');
const fmt = (s) => s ? new Date(s * 1000).toLocaleString('zh-CN', { hour12: false }) : '从未';
const $ = (id) => document.getElementById(id);
async function tick() {
  try {
    const r = await fetch('/deepseek-hub/status', { cache: 'no-store' });
    const d = await r.json();
    $('convs').textContent = d.conversations ?? 0;
    $('msgs').textContent = d.messages ?? 0;
    $('state').innerHTML = d.running
      ? '<span class="dot run"></span>同步中'
      : '<span class="dot"></span>空闲';
    $('lastSync').textContent = fmt(d.lastSyncAt || d.lastSync);
    $('lastPub').textContent = d.lastPublish
      ? fmt(d.lastPublish.at) + (d.lastPublish.ok ? ' · 成功' : ' · 失败')
      : '从未';
    $('auto').textContent = d.autoSyncMinutes > 0 ? '每 ' + d.autoSyncMinutes + ' 分钟' : '关闭';
    $('daily').textContent = d.dailyPublishAt || '关闭';
    $('profile').innerHTML = d.profileOk
      ? '<span class="dot"></span>就绪'
      : '<span class="dot bad"></span>缺失';
    $('err').textContent = d.lastError || '';
  } catch (e) {
    $('state').innerHTML = '<span class="dot bad"></span>面板连不上';
  }
}
tick();
setInterval(tick, 5000);
</script>
</html>`

// ---------------------------------------------------------------- 入口

export function apply(ctx, config) {
  const cfg = resolveConfig(config)
  const state = { running: false, lastSyncAt: 0, lastPublish: null, lastError: '' }
  const STATE_FILE = join(cfg.knowledgeDir, 'data', 'hub-state.json')
  const persist = () => {
    try {
      writeFileSync(
        STATE_FILE,
        JSON.stringify({
          ...state,
          autoSyncMinutes: cfg.autoSyncMinutes,
          dailyPublishAt: cfg.dailyPublishAt,
          updatedAt: Date.now() / 1000,
        }),
        'utf8',
      )
    } catch {
      /* 写不了就算了，面板会退回到 manifest */
    }
  }
  persistState = persist
  persist()
  if (!existsSync(SYNC_SCRIPT)) {
    ctx.logger?.warn?.(`deepseek-hub: 缺少同步脚本 ${SYNC_SCRIPT}`)
  }

  const statusPayload = () => {
    const s = summarize(cfg)
    return {
      ok: true,
      ...s,
      running: state.running,
      lastSyncAt: state.lastSyncAt || s.lastSync,
      lastPublish: state.lastPublish,
      lastError: state.lastError,
      autoSyncMinutes: cfg.autoSyncMinutes,
      dailyPublishAt: cfg.dailyPublishAt,
      updatedAt: Date.now() / 1000,
    }
  }

  const doSync = async (signal, hidden = true) => {
    if (state.running) return null
    state.running = true
    try {
      const r = await runNodeScript(
        SYNC_SCRIPT,
        [
          '--port', String(cfg.port),
          '--profile', cfg.profileDir,
          '--out', cfg.knowledgeDir,
          '--edge', cfg.edgePath,
          ...(hidden ? ['--hidden'] : []),
        ],
        { timeoutMs: cfg.syncTimeoutMs, signal },
      )
      state.lastSyncAt = Date.now() / 1000
      if (r.code !== 0) state.lastError = String(r.stderr || r.stdout).slice(-500)
      return r
    } finally {
      state.running = false
    }
  }

  ctx.tools.register(statusTool(cfg))
  ctx.tools.register(syncTool(cfg, state))
  ctx.tools.register(publishTool(cfg, state))
  ctx.tools.register(doctorTool(cfg))
  ctx.tools.register(panelTool(cfg))

  // 1) 自动增量同步
  if (cfg.autoSyncMinutes > 0 && ctx.timer && typeof ctx.timer.interval === 'function') {
    ctx.effect(() =>
      ctx.timer.interval(async () => {
        try {
          const r = await doSync(undefined, true)
          if (r) ctx.logger?.info?.(`deepseek-hub 自动同步：${parseSyncResult(r.stdout).summary}`)
        } catch (error) {
          state.lastError = String(error)
          ctx.logger?.warn?.(`deepseek-hub 自动同步失败：${error}`)
        }
      }, cfg.autoSyncMinutes * 60000),
    )
  }

  // 2) 每天定点发布（默认 20:00），取代 Windows 计划任务
  const [hh, mm] = String(cfg.dailyPublishAt || '').split(':').map(Number)
  if (Number.isFinite(hh) && Number.isFinite(mm) && ctx.timer && typeof ctx.timer.interval === 'function') {
    let lastDay = ''
    ctx.effect(() =>
      ctx.timer.interval(async () => {
        const now = new Date()
        if (now.getHours() !== hh || now.getMinutes() !== mm) return
        const day = now.toDateString()
        if (lastDay === day) return
        lastDay = day
        try {
          const result = await runPublish(cfg, {})
          state.lastPublish = { at: Date.now() / 1000, ok: result.ok, dryRun: false }
          if (!result.ok) state.lastError = String(result.output || '').slice(-500)
          persist()
          ctx.logger?.info?.(`deepseek-hub 每日发布：${result.ok ? '完成' : '失败'}`)
        } catch (error) {
          state.lastError = String(error)
        }
      }, 30000),
    )
  }

  // 3) 状态面板：浏览器打开 <dsh origin>/deepseek-hub
  const web = ctx.get('webServer')
  if (web && typeof web.register === 'function') {
    ctx.effect(() =>
      web.register({
        kind: 'exact',
        path: '/deepseek-hub',
        resource: async () =>
          new Response(PANEL_HTML, {
            headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' },
          }),
      }),
    )
    ctx.effect(() =>
      web.register({
        kind: 'exact',
        path: '/deepseek-hub/status',
        resource: async () =>
          new Response(JSON.stringify(statusPayload()), {
            headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
          }),
      }),
    )
  }
}
