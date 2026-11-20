/**
 * Host half: tracks the run state and keeps the desktop widget alive.
 *
 * The widget is a separate PowerShell + WPF process (no DSH patching): it reads
 * a small JSON state file this plugin rewrites on every transition, and owns its
 * own dragging, voice playback and the optional shutdown countdown.
 */
import { spawn } from 'node:child_process'
import { appendFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

/** Package root; the widget and its assets live beside this file. */
const HERE = dirname(fileURLToPath(import.meta.url))
/** Where the widget picks up state and keeps its own window position. */
const STATE_DIR = join(tmpdir(), 'dsh-whale-pet')
const STATE_PATH = join(STATE_DIR, 'state.json')
/** Diagnostics for the spawn attempt; the widget keeps its own log beside this. */
const HOST_LOG = join(STATE_DIR, 'host.log')
/** How long a finished run keeps celebrating before the widget reads idle. */
const RESET_MS = 9000

export function apply(ctx) {
  if (process.platform !== 'win32') return

  /** Sessions the Host currently reports as running. */
  const running = new Set()
  let phase = 'idle'
  let resetTimer = null
  let child = null
  let stopped = false

  const hostLog = (message) => {
    try {
      mkdirSync(STATE_DIR, { recursive: true })
      appendFileSync(HOST_LOG, `[${new Date().toISOString()}] ${message}\n`, 'utf8')
    } catch (error) {
      // Diagnostics must never break activation.
    }
  }

  const writeState = () => {
    try {
      mkdirSync(STATE_DIR, { recursive: true })
      writeFileSync(STATE_PATH, JSON.stringify({ phase, at: Date.now() }), 'utf8')
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
      resetTimer = setTimeout(() => {
        resetTimer = null
        phase = 'idle'
        writeState()
      }, RESET_MS)
      if (typeof resetTimer.unref === 'function') resetTimer.unref()
    }
  }

  // Start from a readable state so a freshly started widget is not blank.
  writeState()

  const script = join(HERE, 'widget', 'widget.ps1')
  const assets = join(HERE, 'assets')
  const shell = join(process.env.SystemRoot ?? 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
  hostLog(`spawn ${shell} -File ${script}`)
  try {
    child = spawn(shell, [
      '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', script,
      '-StatePath', STATE_PATH, '-AssetsDir', assets,
    ], { windowsHide: true, stdio: 'ignore', detached: false })
    child.on('error', (error) => {
      hostLog(`spawn error: ${error && error.message ? error.message : String(error)}`)
      console.error('[whale-pet] the desktop widget failed to start', error)
    })
    child.on('exit', (code, signal) => {
      hostLog(`widget exited code=${code} signal=${signal}`)
      child = null
    })
  } catch (error) {
    console.error('[whale-pet] cannot spawn the desktop widget', error)
  }

  ctx.on('api-session/status', (sessionId, isRunning) => {
    if (isRunning) running.add(sessionId)
    else running.delete(sessionId)
    if (running.size > 0) {
      // A pending question outranks the generic running pose.
      if (phase !== 'waiting') setPhase('running')
      return
    }
    if (phase !== 'waiting') setPhase('done')
  })
  ctx.on('api-session/error', () => { setPhase('error') })
  // Observe before the answerers claim the request, then hand it on untouched.
  ctx.on('user-questions/request', (_request, next) => {
    setPhase('waiting')
    return next()
  }, { prepend: true })
  ctx.on('approval/request', (_request, next) => {
    setPhase('waiting')
    return next()
  }, { prepend: true })

  ctx.effect(() => () => {
    stopped = true
    if (resetTimer !== null) clearTimeout(resetTimer)
    // A countdown may already have queued the OS shutdown; cancel it.
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
  })
}
