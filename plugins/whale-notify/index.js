/**
 * Host half: run state, mood model, and the whale girl's generated lines.
 *
 * The desktop widget is a separate PowerShell/WPF process. It reads
 * `state.json` (rewritten here) and writes `request.json` when the user clicks,
 * feeds her, or asks about her mood. Generated lines come from the configured
 * DSH model through `ctx.llm`, and are spoken through Edge TTS when a Python
 * environment with `edge-tts` is available.
 */
import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { appendFileSync, existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const STATE_DIR = join(tmpdir(), 'dsh-whale-pet')
const STATE_PATH = join(STATE_DIR, 'state.json')
const MOOD_PATH = join(STATE_DIR, 'mood.json')
const REQUEST_PATH = join(STATE_DIR, 'request.json')
const HOST_LOG = join(STATE_DIR, 'host.log')
const VOICE_CACHE = join(STATE_DIR, 'voice-cache')
const TTS_SCRIPT = join(HERE, 'tools', 'tts.py')
const RESET_MS = 9000
/** Do not ask the model more often than this. */
const MIN_LINE_GAP_MS = 20000

/** The voice the persona uses for generated lines. */
const TTS_VOICE = 'zh-CN-XiaoyiNeural'

/** System prompt: persona plus the strict reply contract. */
const PERSONA = [
  '你是 DeepSeek 鲸鱼娘（也叫蓝色大肥鱼），一只住在用户 Windows 电脑上的桌宠。',
  '性格：聪明但懒、嘴甜又傲娇、爱吃白米饭和小鱼干，管用户叫“主人”。',
  '说话要像真人聊天：短、口语、有情绪、偶尔撒娇或吐槽，不要书面语，不要解释自己。',
  '只输出一个 JSON 对象：{"line":"不超过 24 个汉字的一句台词","expression":"cheer|tired|worried|denied|thinking|idle"}。',
  'expression 选最贴合这句台词的：开心欢呼 cheer、累了 tired、担心 worried、拒绝/生气 denied、思考 thinking、平常 idle。',
  '不要输出 JSON 以外的任何字符。',
].join('\n')

/** Mutable counters that make her feel alive. */
const DEFAULT_MOOD = { mood: 62, affinity: 20, satiety: 45, fed: 0, patted: 0, lastLineAt: 0 }

/**
 * Clamp a number into a range.
 * @param {number} value - candidate.
 * @param {number} low - minimum.
 * @param {number} high - maximum.
 * @returns {number} clamped value.
 */
function clamp(value, low, high) {
  return Math.max(low, Math.min(high, value))
}

export function apply(ctx) {
  if (process.platform !== 'win32') return

  const running = new Set()
  let phase = 'idle'
  let resetTimer = null
  let child = null
  let stopped = false
  let sequence = 0
  /** Last generated bubble: line, expression, spoken file, and its sequence. */
  let script = { line: '', expression: '', voice: '', summary: '' }
  let mood = { ...DEFAULT_MOOD }
  let busy = false
  let lastRequestAt = 0
  /** When the last inner monologue was requested. */
  let lastThoughtAt = 0

  const hostLog = (message) => {
    try {
      mkdirSync(STATE_DIR, { recursive: true })
      appendFileSync(HOST_LOG, `[${new Date().toISOString()}] ${message}\n`, 'utf8')
    } catch (error) {
      // Diagnostics must never break activation.
    }
  }

  try {
    mkdirSync(VOICE_CACHE, { recursive: true })
    mood = { ...DEFAULT_MOOD, ...JSON.parse(readFileSync(MOOD_PATH, 'utf8')) }
  } catch (error) {
    // First run, or a corrupt file: defaults are fine.
  }

  const saveMood = () => {
    try {
      mkdirSync(STATE_DIR, { recursive: true })
      writeFileSync(MOOD_PATH, JSON.stringify(mood), 'utf8')
    } catch (error) {
      // Mood is a cache; the widget keeps working without it.
    }
  }

  const writeState = () => {
    try {
      mkdirSync(STATE_DIR, { recursive: true })
      writeFileSync(STATE_PATH, JSON.stringify({
        phase,
        at: Date.now(),
        mood: mood.mood,
        affinity: mood.affinity,
        satiety: mood.satiety,
        fed: mood.fed,
        patted: mood.patted,
        line: script.line,
        expression: script.expression,
        voice: script.voice,
        summary: script.summary,
        seq: sequence,
      }), 'utf8')
    } catch (error) {
      console.error('[whale-pet] cannot write the widget state', error)
    }
  }

  const setPhase = (next) => {
    if (stopped || phase === next) return
    phase = next
    if (resetTimer !== null) {
      clearTimeout(resetTimer)
      resetTimer = null
    }
    writeState()
    if (next === 'done' || next === 'error') {
      void generate(next === 'error' ? 'error' : 'done')
      resetTimer = setTimeout(() => {
        resetTimer = null
        phase = 'idle'
        writeState()
      }, RESET_MS)
      if (typeof resetTimer.unref === 'function') resetTimer.unref()
    }
  }

  /** Resolve the model the profile currently prefers. */
  const pickModel = () => {
    try {
      const selection = ctx.get('agentDefaultModel')
      if (selection !== undefined && typeof selection.currentSelection === 'function') {
        const current = selection.currentSelection()
        if (current !== null && current !== undefined && typeof current.provider === 'string') return current
      }
    } catch (error) {
      // Fall through to the plain route below.
    }
    return { provider: 'deepseek', model: 'deepseek-flash' }
  }

  /**
   * Ask the configured model for one persona line.
   * @param {string} kind - `done`, `error`, `talk`, `mood`, `pat`, or `feed`.
   * @returns {Promise<{ line: string, expression: string } | null>} parsed reply, or null.
   */
  const askModel = async (kind) => {
    const llm = ctx.get('llm')
    if (llm === undefined || typeof llm.stream !== 'function') {
      hostLog('no llm service')
      return null
    }
    const { provider, model } = pickModel()
    const when = new Date()
    const angles = {
      done: '任务刚刚完成，主人可能正等着看结果。',
      error: '刚才有一步出错了，主人可能有点急。',
      talk: '主人点了一下你，想听你说句话。',
      thought: '你正在陪着主人干活，可以小声嘀咕一句你此刻的小心思。',
      mood: '主人想知道你现在的心情。',
      pat: '主人刚摸了你的头。',
      feed: '主人刚喂了你一条小鱼干。',
    }
    const prompt = [
      `当前状态：${angles[kind] ?? angles.talk}`,
      `心情 ${mood.mood}/100，对主人好感 ${mood.affinity}/100，饱食 ${mood.satiety}/100。`,
      `已经是 ${when.getHours()} 点${when.getHours() < 6 ? '，你有点困' : when.getHours() >= 22 ? '，夜挺深了' : ''}。`,
      '说一句符合人设的短台词。',
    ].join('\n')
    let text = ''
    try {
      const stream = llm.stream({
        provider,
        model,
        system: PERSONA,
        messages: [{ role: 'user', content: [{ type: 'text', text: prompt }] }],
        temperature: 0.9,
        maxTokens: 240,
      })
      for await (const chunk of stream) {
        if (chunk.type === 'text-delta') text += chunk.text
        if (chunk.type === 'finish' && chunk.reason.kind === 'error') {
          hostLog(`llm finish error: ${chunk.reason.failure?.message ?? 'unknown'}`)
          return null
        }
      }
    } catch (error) {
      hostLog(`llm failed: ${error && error.message ? error.message : String(error)}`)
      return null
    }
    // The reply may be truncated mid-JSON; read the two fields directly.
    const lineMatch = /"line"\s*:\s*"((?:[^"\\]|\\.)*)"/.exec(text)
    if (lineMatch === null) {
      hostLog(`llm reply had no line: ${text.slice(0, 120)}`)
      return null
    }
    let line = lineMatch[1]
    try {
      line = JSON.parse(`"${lineMatch[1]}"`)
    } catch (error) {
      // Keep the raw text when the escapes are unusual.
    }
    line = line.trim().slice(0, 60)
    if (line === '') return null
    const expressionMatch = /"expression"\s*:\s*"([a-zA-Z-]+)"/.exec(text)
    return { line, expression: expressionMatch === null ? 'idle' : expressionMatch[1] }
  }

  /** Locate a Python that has edge-tts installed. */
  const ttsPython = () => {
    const candidates = [
      process.env.WHALE_TTS_PYTHON,
      join(HERE, '..', '..', '_tools', 'tts-venv', 'Scripts', 'python.exe'),
    ]
    for (const candidate of candidates) {
      if (typeof candidate === 'string' && candidate !== '' && existsSync(candidate)) return candidate
    }
    return undefined
  }

  /**
   * Synthesise a line into the cache, or reuse it.
   * @param {string} line - text to speak.
   * @returns {Promise<string | undefined>} absolute mp3 path.
   */
  const speakable = async (line) => {
    const python = ttsPython()
    if (python === undefined || !existsSync(TTS_SCRIPT)) return undefined
    const digest = createHash('sha1').update(`${TTS_VOICE}:${line}`).digest('hex').slice(0, 16)
    const out = join(VOICE_CACHE, `${digest}.mp3`)
    if (existsSync(out)) return out
    const run = async () => {
      try {
        const service = ctx.get('subprocess')
        if (service === undefined) return undefined
        const handle = service.spawn({
          argv: [python, TTS_SCRIPT, '--text', line, '--out', out, '--voice', TTS_VOICE],
          cwd: HERE,
          stdio: { stdin: 'ignore', stdout: { maxBytes: 4096 }, stderr: { maxBytes: 4096 } },
          graceMs: 2000,
        })
        await handle.done
        return existsSync(out) ? out : undefined
      } catch (error) {
        hostLog(`tts failed: ${error && error.message ? error.message : String(error)}`)
        return undefined
      }
    }
    const synth = run()
    // A stuck synthesizer must never block the next line.
    return await Promise.race([
      synth,
      new Promise((resolve) => setTimeout(() => resolve(undefined), 12000)),
    ])
  }

  /**
   * Generate a line, speak it, and publish it to the widget.
   * @param {string} kind - request kind.
   */
  const generate = async (kind) => {
    if (stopped || busy) return
    const now = Date.now()
    if (kind !== 'mood' && kind !== 'talk' && kind !== 'thought' && now - mood.lastLineAt < MIN_LINE_GAP_MS) return
    busy = true
    try {
      const reply = await askModel(kind)
      if (reply === null) return
      mood.lastLineAt = Date.now()
      saveMood()
      sequence += 1
      // Synthesise first (bounded), then publish line and voice together.
      const voice = await speakable(reply.line)
      script = {
        line: reply.line,
        expression: reply.expression,
        voice: voice ?? '',
        summary: `心情 ${mood.mood} · 好感 ${mood.affinity} · 饱食 ${mood.satiety}`,
      }
      writeState()
      hostLog(`line(${kind}) ${reply.line} [${reply.expression}]${voice ? ' +voice' : ' (no voice)'}`)
    } finally {
      busy = false
    }
  }

  /** Apply one widget request. */
  const handleRequest = (request) => {
    const kind = request && typeof request.kind === 'string' ? request.kind : ''
    lastRequestAt = Date.now()
    if (kind === 'pat') {
      mood.patted += 1
      mood.affinity = clamp(mood.affinity + 2, 0, 100)
      mood.mood = clamp(mood.mood + 1, 0, 100)
      saveMood()
      writeState()
      return
    }
    if (kind === 'feed') {
      mood.fed += 1
      mood.satiety = clamp(mood.satiety + 10, 0, 100)
      mood.mood = clamp(mood.mood + 3, 0, 100)
      saveMood()
      writeState()
      return
    }
    if (kind === 'talk' || kind === 'mood' || kind === 'thought') {
      lastRequestAt = Date.now()
      void generate(kind)
    }
  }

  // Start from a readable state so a freshly started widget is not blank.
  const agents = ctx.get('agents')
  try {
    if (agents !== undefined) {
      for (const agent of agents.list()) {
        if (agent.status === 'running') running.add(agent.session.id)
      }
    }
  } catch (error) {
    hostLog(`cannot seed running sessions: ${error && error.message ? error.message : String(error)}`)
  }
  if (running.size > 0) phase = 'running'
  writeState()

  // One-shot network probe: can this Host process reach the internet at all?
  const probeNetwork = async () => {
    const result = { at: new Date().toISOString(), targets: {} }
    for (const url of ['https://pypi.org/', 'https://speech.platform.bing.com/']) {
      try {
        const controller = new AbortController()
        const timer = setTimeout(() => controller.abort(), 8000)
        const response = await fetch(url, { method: 'HEAD', signal: controller.signal })
        clearTimeout(timer)
        result.targets[url] = `http ${response.status}`
      } catch (error) {
        result.targets[url] = `fail: ${error && error.message ? error.message : String(error)}`
      }
    }
    try {
      writeFileSync(join(STATE_DIR, 'host-probe.json'), JSON.stringify(result, null, 2), 'utf8')
    } catch (error) {
      // Probe output is best effort.
    }
    hostLog(`network probe: ${JSON.stringify(result.targets)}`)
  }
  void probeNetwork()

  const scriptPath = join(HERE, 'widget', 'widget.ps1')
  const assets = join(HERE, 'assets')
  const shell = join(process.env.SystemRoot ?? 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
  hostLog(`spawn ${shell} -File ${scriptPath}`)
  try {
    child = spawn(shell, [
      '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', scriptPath,
      '-StatePath', STATE_PATH, '-AssetsDir', assets,
      '-TtsPython', ttsPython() ?? '', '-TtsScript', TTS_SCRIPT,
    ], { windowsHide: true, stdio: 'ignore', detached: false })
    child.on('error', (error) => {
      hostLog(`spawn error: ${error && error.message ? error.message : String(error)}`)
    })
    child.on('exit', (code, signal) => {
      hostLog(`widget exited code=${code} signal=${signal}`)
      child = null
    })
  } catch (error) {
    console.error('[whale-pet] cannot spawn the desktop widget', error)
  }

  let waitingUntil = 0
  const settle = () => {
    if (running.size > 0) setPhase('running')
    else setPhase('done')
  }
  ctx.on('api-session/status', (sessionId, isRunning) => {
    if (isRunning) running.add(sessionId)
    else running.delete(sessionId)
    waitingUntil = 0
    settle()
  })
  ctx.on('api-session/error', () => {
    waitingUntil = 0
    setPhase('error')
  })
  ctx.on('user-questions/request', (_request, next) => {
    waitingUntil = Date.now() + 90000
    setPhase('waiting')
    return next()
  }, { prepend: true })
  ctx.on('approval/request', (_request, next) => {
    waitingUntil = Date.now() + 90000
    setPhase('waiting')
    return next()
  }, { prepend: true })

  const beat = setInterval(() => {
    if (stopped) return
    if (waitingUntil !== 0 && Date.now() > waitingUntil) {
      waitingUntil = 0
      settle()
    }
    // Slow decay keeps the mood from freezing while nothing happens.
    if (mood.satiety > 0) mood.satiety = clamp(mood.satiety - 1, 0, 100)
    if (phase === 'running') {
      mood.mood = clamp(mood.mood + 1, 0, 100)
      if (Date.now() - lastThoughtAt > 90000) {
        lastThoughtAt = Date.now()
        void generate('thought')
      }
    }
    writeState()
  }, 15000)
  if (typeof beat.unref === 'function') beat.unref()

  const inbox = setInterval(() => {
    if (stopped || !existsSync(REQUEST_PATH)) return
    let request
    try {
      request = JSON.parse(readFileSync(REQUEST_PATH, 'utf8').replace(/^\uFEFF/, ''))
    } catch (error) {
      // A malformed request must not wedge the inbox.
      try {
        unlinkSync(REQUEST_PATH)
      } catch (unlinkError) {
        // Already gone.
      }
      return
    }
    try {
      unlinkSync(REQUEST_PATH)
    } catch (error) {
      // Already gone.
    }
    handleRequest(request)
  }, 400)
  if (typeof inbox.unref === 'function') inbox.unref()

  ctx.effect(() => () => {
    stopped = true
    clearInterval(beat)
    clearInterval(inbox)
    if (resetTimer !== null) clearTimeout(resetTimer)
    try {
      writeFileSync(STATE_PATH, JSON.stringify({ phase: 'offline', at: Date.now() }), 'utf8')
    } catch (error) {
      // The widget falls back to its heartbeat timeout.
    }
    try {
      spawn('shutdown.exe', ['/a'], { windowsHide: true, stdio: 'ignore' })
    } catch (error) {
      // Nothing was scheduled.
    }
    if (child !== null) {
      try {
        child.kill()
      } catch (error) {
        // Already gone.
      }
    }
    void lastRequestAt
  })
}
