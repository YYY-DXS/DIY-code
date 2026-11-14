// DeepSeek 会话批量同步（M2）：CDP 驱动专用 Edge，读网页自己的响应体 → Markdown
//
// 用法：
//   node hub-sync.mjs --port 9381 --profile <profileDir> --out <knowledgeDir> [--limit N] [--force]
//
// 输出：
//   <out>/transcripts/YYYY-MM-DD_标题.md
//   <out>/data/chats/<conv_id>.json
//   <out>/data/manifest.json
//   <out>/index.md
import { spawn, execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync, existsSync, readFileSync, unlinkSync } from 'node:fs'
import { join } from 'node:path'
import { CDP } from './mini-ws.mjs'

// ---------------------------------------------------------------- 参数
const args = process.argv.slice(2)
const arg = (name, def) => {
  const i = args.indexOf(`--${name}`)
  return i >= 0 && args[i + 1] ? args[i + 1] : def
}
const flag = (name) => args.includes(`--${name}`)

const PORT = Number(arg('port', 9381))
const PROFILE = arg('profile', process.env.DEEPSEEK_HUB_PROFILE || 'edge-profile')
const OUT = arg('out', process.env.DEEPSEEK_HUB_OUT || 'knowledge')
const LIMIT = Number(arg('limit', 0))
const FORCE = flag('force')
const EDGE = arg('edge', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
const VISIBLE = !flag('hidden')

const BASE = `http://127.0.0.1:${PORT}`
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const t0 = Date.now()
const log = (...a) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a)

// ---------------------------------------------------------------- 工具
function fmtTs(value) {
  let ms = null
  if (typeof value === 'number') ms = value * 1000
  else if (typeof value === 'string' && value) ms = Date.parse(value)
  if (!ms || Number.isNaN(ms)) return ''
  const d = new Date(ms)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function safeName(text, limit = 45) {
  return (
    (text || '未命名')
      .replace(/[\\/:*?"<>|\r\n\t]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, limit) || '未命名'
  )
}

const KEEP = new Set(['REQUEST', 'RESPONSE', 'THINK'])
const SEARCH = new Set(['SEARCH', 'TOOL_SEARCH'])

function normalize(msg) {
  const out = { request: '', response: '', think: '', searches: [], files: [] }
  const req = []
  const res = []
  const think = []
  for (const frag of msg.fragments || []) {
    const kind = frag?.type
    if (kind === 'REQUEST') req.push(frag.content || '')
    else if (kind === 'RESPONSE') res.push(frag.content || '')
    else if (kind === 'THINK') think.push(frag.content || '')
    else if (SEARCH.has(kind)) {
      for (const item of frag.results || []) {
        if (item && item.url) out.searches.push({ title: item.title || '', url: item.url })
      }
    } else if (kind === 'FILE') {
      for (const f of frag.files || []) {
        if (f) out.files.push({ name: f.file_name || '', bytes: f.file_size || 0 })
      }
    }
  }
  out.request = req.filter((t) => t.trim()).join('\n\n')
  out.response = res.filter((t) => t.trim()).join('\n\n')
  out.think = think.filter((t) => t.trim()).join('\n\n')
  return out
}

function renderTranscript(conv, msgs) {
  const turns = msgs.filter((m) => normalize(m).request).length
  const replies = msgs.filter((m) => normalize(m).response).length
  const lines = [
    `# ${conv.title || '未命名会话'}`,
    '',
    `- 会话 ID：\`${conv.id}\``,
    `- 创建时间：${fmtTs(conv.inserted_at)}`,
    `- 最后更新：${fmtTs(conv.updated_at)}`,
    `- 用户发言 ${turns} 条 / 助手回复 ${replies} 条`,
    '- 来源：`web-cdp`',
    '',
    '> 本文由 DeepSeek Hub 自动同步（web-cdp），思考过程与联网搜索结果折叠在下面。',
    '',
    '---',
    '',
  ]
  const seen = new Set()
  let turnNo = 0
  for (const msg of msgs) {
    const p = normalize(msg)
    if (!p.request && !p.response && !p.think && !p.searches.length && !p.files.length) continue
    if (p.request) {
      turnNo += 1
      lines.push(`## ${turnNo}. 用户 · ${fmtTs(msg.inserted_at)}`, '', p.request, '')
    }
    if (p.think) {
      lines.push('<details><summary>思考过程</summary>', '', p.think, '', '</details>', '')
    }
    if (p.response) {
      lines.push(`## DeepSeek · ${fmtTs(msg.inserted_at)}`, '', p.response, '')
    }
    const fresh = p.searches.filter((s) => s.url && !seen.has(s.url))
    fresh.forEach((s) => seen.add(s.url))
    if (fresh.length) {
      lines.push(`<details><summary>联网搜索（${fresh.length} 条）</summary>`, '')
      for (const s of fresh) lines.push(`- [${s.title || s.url}](${s.url})`)
      lines.push('', '</details>', '')
    }
    for (const f of p.files) lines.push(`> 附件：${f.name}（${f.bytes} 字节）`, '')
  }
  return lines.join('\n').replace(/\n{3,}/g, '\n\n').trimEnd() + '\n'
}

function renderIndex(manifest) {
  const rows = Object.values(manifest.conversations || {})
    .sort((a, b) => (b.updated || 0) - (a.updated || 0))
    .map(
      (c) =>
        `| ${fmtTs(c.updated).slice(0, 10)} | [${(c.title || '未命名').replace(/\|/g, '\\|')}](transcripts/${encodeURI(c.file)}) | ${c.messages} | ${c.pinned ? '📌' : ''} |`
    )
  return [
    '# DeepSeek 会话索引（自动同步）',
    '',
    `- 最近同步：${fmtTs(Date.now() / 1000)}`,
    `- 会话数：${rows.length}`,
    '',
    '| 更新日期 | 会话 | 消息数 | 置顶 |',
    '| --- | --- | --- | --- |',
    ...rows,
    '',
  ].join('\n')
}

// ---------------------------------------------------------------- 浏览器
async function ensureBrowser() {
  const alive = await fetch(`${BASE}/json/version`).then((r) => r.ok).catch(() => false)
  if (alive) return null
  log('启动 Edge（专用 profile）…')
  const argv = [
    '--no-first-run',
    '--remote-debugging-port=' + PORT,
    '--remote-allow-origins=*',
    '--user-data-dir=' + PROFILE,
    '--window-size=1280,900',
    VISIBLE ? '--start-maximized' : '--window-position=-32000,-32000',
    'about:blank',
  ]
  const child = spawn(EDGE, argv, { detached: true, stdio: 'ignore' })
  child.unref()
  for (let i = 0; i < 40; i++) {
    await sleep(500)
    const ok = await fetch(`${BASE}/json/version`).then((r) => r.ok).catch(() => false)
    if (ok) return child
  }
  throw new Error('Edge 启动超时')
}

async function attach() {
  const v = await (await fetch(`${BASE}/json/version`)).json()
  const cdp = await new CDP(v.webSocketDebuggerUrl).open()
  const { targetInfos } = await cdp.send('Target.getTargets')
  let page = targetInfos.find((t) => t.type === 'page' && /deepseek/.test(t.url))
  if (!page) page = targetInfos.find((t) => t.type === 'page')
  let targetId = page?.targetId
  if (!targetId) {
    const r = await cdp.send('Target.createTarget', { url: 'about:blank' })
    targetId = r.targetId
  }
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true })
  return { cdp, sessionId }
}

async function main() {
  const launched = await ensureBrowser()
  const { cdp, sessionId } = await attach()
  const S = (m, p) => cdp.send(m, p, sessionId)
  await S('Network.enable')
  await S('Page.enable')
  log('已连接 CDP')

  // 收集响应：响应体在 loadingFinished 时立刻取，避免资源被回收
  const bodies = new Map() // url -> body
  const ridUrl = new Map()
  cdp.onEvent((msg) => {
    if (msg.method === 'Network.responseReceived') {
      const { requestId, response } = msg.params
      if (/\/api\/v\d+\/chat/.test(response.url)) ridUrl.set(requestId, response.url)
    } else if (msg.method === 'Network.loadingFinished') {
      const rid = msg.params.requestId
      const url = ridUrl.get(rid)
      if (!url) return
      ridUrl.delete(rid)
      cdp
        .send('Network.getResponseBody', { requestId: rid }, sessionId)
        .then(({ body }) => bodies.set(url, body))
        .catch(() => {})
    }
  })

  const waitBody = async (pattern, timeoutMs) => {
    const start = Date.now()
    while (Date.now() - start < timeoutMs) {
      for (const [url, body] of bodies) {
        if (pattern.test(url)) {
          bodies.delete(url)
          return body
        }
      }
      await sleep(200)
    }
    return null
  }

  // 1) 会话列表
  log('打开首页，取会话列表…')
  await S('Page.navigate', { url: 'https://chat.deepseek.com/' })
  const listBody = await waitBody(/chat_session\/fetch_page/, 20000)
  if (!listBody) throw new Error('没抓到 fetch_page')
  const sessions = JSON.parse(listBody)?.data?.biz_data?.chat_sessions || []
  log(`会话列表 ${sessions.length} 个`)

  // 2) 逐个同步
  mkdirSync(join(OUT, 'transcripts'), { recursive: true })
  mkdirSync(join(OUT, 'data', 'chats'), { recursive: true })
  const manifestPath = join(OUT, 'data', 'manifest.json')
  const manifest = existsSync(manifestPath)
    ? JSON.parse(readFileSync(manifestPath, 'utf8'))
    : { conversations: {} }
  manifest.conversations ||= {}

  // 删除同步：网页上已经不存在的会话，从本地清掉（只增不减的旧行为在这里修正）
  let pruned = 0
  if (!LIMIT) {
    const remoteIds = new Set(sessions.map((s) => s.id))
    for (const [cid, entry] of Object.entries(manifest.conversations)) {
      if (remoteIds.has(cid)) continue
      try {
        if (entry.file) {
          const f = join(OUT, 'transcripts', entry.file)
          if (existsSync(f)) unlinkSync(f)
        }
        const raw = join(OUT, 'data', 'chats', `${cid}.json`)
        if (existsSync(raw)) unlinkSync(raw)
      } catch {
        /* 删不掉就留着 */
      }
      delete manifest.conversations[cid]
      pruned++
    }
    if (pruned) log(`清理网页已删除的会话 ${pruned} 个`)
  }

  let done = 0
  let skipped = 0
  let failed = 0
  const targets = LIMIT > 0 ? sessions.slice(0, LIMIT) : sessions

  for (const sess of targets) {
    const id = sess.id
    const prev = manifest.conversations[id]
    const rawPath = join(OUT, 'data', 'chats', `${id}.json`)
    if (!FORCE && prev && existsSync(rawPath) && (prev.updated || 0) >= (sess.updated_at || 0)) {
      skipped++
      continue
    }
    const histRe = new RegExp(`history_messages.*${id}`)
    await S('Page.navigate', { url: `https://chat.deepseek.com/a/chat/s/${id}` })
    let body = await waitBody(histRe, 15000)
    if (!body) {
      // 重试一次
      await S('Page.navigate', { url: `https://chat.deepseek.com/a/chat/s/${id}` })
      body = await waitBody(histRe, 15000)
    }
    if (!body) {
      failed++
      log(`  ✗ ${sess.title}（没抓到 history）`)
      continue
    }

    // 服务端可能只回 cache_control=MERGE + 空消息（意思是"用你本地缓存合并"）。
    // 这时从网页自己的 IndexedDB（deepseek-chat / history-message）把完整内容读出来。
    let parsed = JSON.parse(body)
    let biz = parsed?.data?.biz_data
    if (!(biz?.chat_messages || []).length) {
      const idbExpr = `(async () => {
        const db = await new Promise((res, rej) => { const r = indexedDB.open('deepseek-chat'); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
        const st = db.transaction('history-message', 'readonly').objectStore('history-message');
        const val = await new Promise((res, rej) => { const r = st.get(${JSON.stringify(id)}); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
        if (!val || !val.data) return null;
        return JSON.stringify({ chat_session: val.data.chat_session, chat_messages: val.data.chat_messages || [] });
      })()`
      const r = await S('Runtime.evaluate', {
        expression: idbExpr,
        awaitPromise: true,
        returnByValue: true,
      })
      if (r.result?.value) {
        biz = JSON.parse(r.result.value)
        body = JSON.stringify({ code: 0, data: { biz_data: biz } })
        log(`  · ${sess.title} 走 IndexedDB 缓存`)
      }
    }
    try {
      const conv = biz?.chat_session || {}
      const msgs = biz?.chat_messages || []
      if (!msgs.length) {
        failed++
        log(`  ✗ ${sess.title}（服务端返回空内容）`)
        continue
      }
      writeFileSync(rawPath, body)

      const date = fmtTs(conv.inserted_at).slice(0, 10) || '未知日期'
      let file = `${date}_${safeName(conv.title || sess.title)}.md`
      for (const other of Object.values(manifest.conversations)) {
        if (other.id !== id && other.file === file) {
          file = `${date}_${safeName(conv.title || sess.title)}_${id.slice(0, 6)}.md`
          break
        }
      }
      writeFileSync(join(OUT, 'transcripts', file), renderTranscript(conv, msgs))
      manifest.conversations[id] = {
        id,
        title: conv.title || sess.title || '',
        file,
        created: conv.inserted_at || sess.inserted_at || 0,
        updated: conv.updated_at || sess.updated_at || 0,
        messages: msgs.length,
        pinned: !!sess.pinned,
        synced_at: Date.now() / 1000,
      }
      done++
      log(`  ✓ ${conv.title || sess.title}（${msgs.length} 条）`)
    } catch (e) {
      failed++
      log(`  ✗ ${sess.title}: ${e.message}`)
    }
  }

  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2))
  // 给原生面板读的状态快照（子进程写文件是确定可用的）
  try {
    writeFileSync(
      join(OUT, 'data', 'hub-state.json'),
      JSON.stringify({
        running: false,
        lastSyncAt: Date.now() / 1000,
        conversations: Object.keys(manifest.conversations).length,
        messages: Object.values(manifest.conversations).reduce((s, c) => s + (c.messages || 0), 0),
        pruned,
        updatedAt: Date.now() / 1000,
      })
    )
  } catch {
    /* 写不了不影响同步 */
  }
  writeFileSync(join(OUT, 'index.md'), renderIndex(manifest))
  log(`完成：新同步 ${done}，跳过 ${skipped}，失败 ${failed}`)
  log(`输出目录：${OUT}`)
  if (!flag('keep')) {
    await cdp.send('Browser.close').catch(() => {})
    await sleep(1200)
    // Browser.close 有时只关窗口不退出进程：按端口找到 owner PID，整棵进程树杀掉
    try {
      const still = await fetch(`${BASE}/json/version`).then((r) => r.ok).catch(() => false)
      if (still) {
        const netstat = execFileSync('netstat', ['-ano'], { encoding: 'utf8' })
        const line = netstat
          .split(/\r?\n/)
          .find((l) => l.includes(`:${PORT}`) && /LISTENING/i.test(l))
        const pid = line ? Number(line.trim().split(/\s+/).pop()) : 0
        if (pid) execFileSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' })
      }
    } catch {
      /* 已经退出就算了 */
    }
  }
  cdp.close()
  process.exit(0)
}

main().catch((e) => {
  console.error('FAIL', e.stack || e)
  process.exit(1)
})
