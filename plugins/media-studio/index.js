import { spawn } from 'node:child_process'
import { access, mkdir, mkdtemp, readdir, rm, stat, writeFile } from 'node:fs/promises'
import { constants as fsConstants } from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const TICKS_PER_SECOND = 254016000000
const PF = process.env.ProgramFiles || 'C:\\Program Files'
const PF86 = process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)'
const LOCAL = process.env.LOCALAPPDATA || ''
const HOME = process.env.USERPROFILE || ''

const CRAFT = {
  filmcraft: {
    name: 'FilmCraft',
    kind: 'video',
    cli: [path.join(PF, 'FilmCraft', 'filmcraft-cli.exe')],
    app: [path.join(PF, 'FilmCraft', 'filmcraft.exe')],
    capabilities: ['timeline editing', 'transitions', 'effects', 'titles', 'Lumetri colour', 'audio', 'colour management', 'interchange', 'export'],
  },
  effectcraft: {
    name: 'EffectCraft',
    kind: 'vfx',
    cli: [path.join(PF, 'EffectCraft', 'effectcraft-cli.exe')],
    app: [path.join(PF, 'EffectCraft', 'effectcraft.exe')],
    capabilities: ['compositing', 'motion graphics', 'keying', '3D', 'particles', 'expressions', 'scripts', 'alpha render'],
  },
  photocraft: {
    name: 'PhotoCraft',
    kind: 'photo',
    cli: [path.join(PF, 'PhotoCraft', 'photocraft-cli.exe')],
    app: [path.join(PF, 'PhotoCraft', 'photocraft.exe')],
    capabilities: ['layers', 'adjustments', 'filters', 'masks', 'PSD', 'batch', 'droplets'],
  },
  lightcraft: {
    name: 'LightCraft',
    kind: 'raw',
    cli: [path.join(PF, 'LightCraft', 'lightcraft-cli.exe')],
    app: [path.join(PF, 'LightCraft', 'lightcraft.exe')],
    capabilities: ['RAW develop', 'colour grading', 'presets', 'HDR merge', 'panorama merge', 'batch export'],
  },
}

const ADOBE_NAMES = [
  ['premiere', 'Adobe Premiere Pro', 'video', /^Adobe Premiere Pro/i, /^Adobe Premiere Pro\.exe$/i, ['editing', 'interchange']],
  ['aftereffects', 'Adobe After Effects', 'vfx', /^Adobe After Effects/i, /^AfterFX\.exe$/i, ['motion graphics', 'compositing', 'scripts']],
  ['photoshop', 'Adobe Photoshop', 'photo', /^Adobe Photoshop/i, /^Photoshop\.exe$/i, ['photo retouch', 'layers', 'scripts']],
  ['mediaencoder', 'Adobe Media Encoder', 'encode', /^Adobe Media Encoder/i, /^Adobe Media Encoder\.exe$/i, ['encoding', 'watch folders']],
]

const scanCache = { at: 0, value: null }

function isWin() {
  return process.platform === 'win32'
}

async function exists(file) {
  if (!file) return false
  try {
    await access(file, fsConstants.F_OK)
    return true
  } catch {
    return false
  }
}

async function isFile(file) {
  try {
    return (await stat(file)).isFile()
  } catch {
    return false
  }
}

async function firstExisting(list) {
  for (const candidate of list) {
    if (await isFile(candidate)) return candidate
  }
  return undefined
}

async function readDirSafe(dir) {
  try {
    return await readdir(dir, { withFileTypes: true })
  } catch {
    return []
  }
}

async function findFile(root, predicate, depth = 3) {
  if (!root || depth < 0 || !(await exists(root))) return undefined
  const entries = await readDirSafe(root)
  for (const entry of entries) {
    const full = path.join(root, entry.name)
    if (entry.isFile() && predicate(entry.name, full)) return full
  }
  for (const entry of entries) {
    if (!entry.isDirectory()) continue
    const found = await findFile(path.join(root, entry.name), predicate, depth - 1)
    if (found) return found
  }
  return undefined
}

function runProcess(exe, args = [], options = {}) {
  const timeoutMs = options.timeoutMs ?? 120000
  return new Promise((resolve, reject) => {
    let child
    try {
      child = spawn(exe, args, {
        cwd: options.cwd,
        env: process.env,
        windowsHide: options.windowsHide ?? true,
        stdio: ['pipe', 'pipe', 'pipe'],
      })
    } catch (error) {
      reject(error)
      return
    }
    let stdout = ''
    let stderr = ''
    let settled = false
    const finish = (error, result) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      if (error) reject(error)
      else resolve(result)
    }
    const timer = setTimeout(() => {
      try {
        child.kill()
      } catch {
        // ignore
      }
      finish(new Error(`Timed out after ${Math.round(timeoutMs / 1000)}s: ${path.basename(exe)} ${args.slice(0, 3).join(' ')}`))
    }, timeoutMs)
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdout.on('data', (chunk) => {
      if (stdout.length < 8_000_000) stdout += chunk
    })
    child.stderr.on('data', (chunk) => {
      if (stderr.length < 2_000_000) stderr += chunk
    })
    child.on('error', (error) => finish(error))
    child.on('close', (code) => finish(null, { code, stdout, stderr }))
    if (options.input !== undefined) child.stdin.end(options.input)
    else child.stdin.end()
  })
}

function parseJson(text) {
  const value = String(text || '').trim()
  if (!value) return null
  try {
    return JSON.parse(value)
  } catch {
    // fall through to line scan
  }
  const lines = value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.startsWith('{') || line.startsWith('['))
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    try {
      return JSON.parse(lines[index])
    } catch {
      // keep looking
    }
  }
  throw new Error(`Expected JSON output, got: ${value.slice(0, 600)}`)
}

function parseJsonLines(text) {
  const out = []
  for (const line of String(text || '').split(/\r?\n/)) {
    const trimmed = line.trim()
    if (!trimmed.startsWith('{')) continue
    try {
      out.push(JSON.parse(trimmed))
    } catch {
      // ignore non-JSON progress lines
    }
  }
  return out
}

async function tempScript(lines) {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'dsh-media-studio-'))
  const file = path.join(dir, 'steps.jsonl')
  await writeFile(file, `${lines.join('\n')}\n`, 'utf8')
  return { dir, file }
}

function secondsToTicks(seconds) {
  return Math.max(0, Math.round(Number(seconds) * TICKS_PER_SECOND))
}

function pick(editors, ...ids) {
  for (const id of ids) {
    const found = editors.find((editor) => editor.id === id && editor.available)
    if (found) return found
  }
  return null
}

async function craftEditor(id) {
  const spec = CRAFT[id]
  if (!spec) return null
  const cli = await firstExisting(spec.cli)
  const app = await firstExisting(spec.app)
  if (!cli && !app) return null
  let version
  if (cli) {
    try {
      const result = await runProcess(cli, ['--version'], { timeoutMs: 15000 })
      version = (result.stdout || '').trim().split(/\r?\n/)[0] || undefined
    } catch {
      // version is optional
    }
  }
  return {
    id,
    name: spec.name,
    kind: spec.kind,
    cli,
    app,
    version,
    available: true,
    automation: cli ? 'cli' : 'launch',
    capabilities: spec.capabilities,
  }
}

async function findAdobe() {
  const found = []
  for (const root of [path.join(PF, 'Adobe'), path.join(PF86, 'Adobe')]) {
    for (const [id, name, kind, productRe, exeRe, capabilities] of ADOBE_NAMES) {
      const productDir = (await readDirSafe(root)).find((entry) => entry.isDirectory() && productRe.test(entry.name))
      if (!productDir) continue
      const productPath = path.join(root, productDir.name)
      const exe = await findFile(productPath, (file) => exeRe.test(file), 3)
      if (exe) {
        found.push({
          id,
          name,
          kind,
          exe,
          app: exe,
          available: true,
          automation: id === 'premiere' ? 'interchange' : 'script',
          capabilities,
        })
      }
    }
  }
  return found
}

async function findCapCut() {
  const candidates = []
  const base = path.join(LOCAL, 'JianyingPro', 'Apps')
  if (await exists(base)) {
    const direct = path.join(base, 'JianyingPro.exe')
    if (await isFile(direct)) candidates.push(direct)
    const versions = (await readDirSafe(base)).filter((entry) => entry.isDirectory()).map((entry) => entry.name)
    versions.sort((a, b) => b.localeCompare(a, undefined, { numeric: true }))
    for (const version of versions) {
      const exe = path.join(base, version, 'JianyingPro.exe')
      if (await isFile(exe)) {
        candidates.push(exe)
        break
      }
    }
  }
  const intl = path.join(LOCAL, 'CapCut', 'Apps', 'CapCut.exe')
  if (await isFile(intl)) candidates.push(intl)
  const exe = candidates[0]
  if (!exe) return null
  const version = path.basename(path.dirname(exe)) === 'Apps' ? undefined : path.basename(path.dirname(exe))
  return {
    id: exe.toLowerCase().includes('capcut') ? 'capcut' : 'jianying',
    name: exe.toLowerCase().includes('capcut') ? 'CapCut' : '剪映专业版',
    kind: 'video',
    exe,
    app: exe,
    version,
    available: true,
    automation: 'launch',
    capabilities: ['consumer editing', 'templates', 'auto captions', 'effects'],
    note: 'CapCut stores its drafts in an encrypted format in this version, so automated handoff is launch/open only.',
  }
}

async function findResolve() {
  const exe = await firstExisting([
    path.join(PF, 'Blackmagic Design', 'DaVinci Resolve', 'Resolve.exe'),
    path.join(PF86, 'Blackmagic Design', 'DaVinci Resolve', 'Resolve.exe'),
  ])
  if (!exe) return null
  return {
    id: 'resolve',
    name: 'DaVinci Resolve',
    kind: 'video',
    exe,
    app: exe,
    available: true,
    automation: 'launch',
    capabilities: ['editing', 'colour grading', 'Fusion', 'Fairlight', 'scripting API'],
  }
}

async function findBlender() {
  const root = path.join(PF, 'Blender Foundation')
  const exe = await findFile(root, (file) => /^blender\.exe$/i.test(file), 3)
  if (!exe) return null
  return {
    id: 'blender',
    name: 'Blender',
    kind: '3d',
    exe,
    app: exe,
    available: true,
    automation: 'python',
    capabilities: ['3D', 'animation', 'compositing', 'VFX', 'Python'],
  }
}

async function findFFmpeg() {
  let exe
  try {
    const result = await runProcess('where.exe', ['ffmpeg.exe'], { timeoutMs: 10000 })
    exe = (result.stdout || '').split(/\r?\n/).map((line) => line.trim()).find(Boolean)
  } catch {
    exe = undefined
  }
  if (!exe || !(await isFile(exe))) {
    exe = await firstExisting([
      'C:\\ffmpeg\\bin\\ffmpeg.exe',
      path.join(PF, 'ffmpeg', 'bin', 'ffmpeg.exe'),
      path.join(LOCAL, 'Microsoft', 'WinGet', 'Links', 'ffmpeg.exe'),
    ])
  }
  if (!exe) return null
  return {
    id: 'ffmpeg',
    name: 'FFmpeg',
    kind: 'encode',
    exe,
    app: exe,
    available: true,
    automation: 'cli',
    capabilities: ['transcode', 'filters', 'frame extraction', 'audio', 'streaming'],
  }
}

async function findOtherEditors() {
  const out = []
  const specs = [
    {
      id: 'obs',
      name: 'OBS Studio',
      kind: 'capture',
      paths: [path.join(PF, 'obs-studio', 'bin', '64bit', 'obs64.exe')],
      capabilities: ['screen capture', 'recording', 'streaming'],
    },
    {
      id: 'gimp',
      name: 'GIMP',
      kind: 'photo',
      paths: [path.join(PF, 'GIMP 3', 'bin', 'gimp-3.exe'), path.join(PF, 'GIMP 2', 'bin', 'gimp-2.10.exe')],
      capabilities: ['photo retouch', 'layers', 'Script-Fu'],
    },
    {
      id: 'shotcut',
      name: 'Shotcut',
      kind: 'video',
      paths: [path.join(PF, 'Shotcut', 'shotcut.exe')],
      capabilities: ['editing', 'filters', 'export'],
    },
    {
      id: 'kdenlive',
      name: 'Kdenlive',
      kind: 'video',
      paths: [path.join(PF, 'kdenlive', 'bin', 'kdenlive.exe')],
      capabilities: ['editing', 'effects', 'export'],
    },
    {
      id: 'vegas',
      name: 'VEGAS Pro',
      kind: 'video',
      paths: [path.join(PF, 'VEGAS', 'VEGAS Pro 22', 'vegas220.exe'), path.join(PF, 'VEGAS', 'VEGAS Pro 21', 'vegas210.exe')],
      capabilities: ['editing', 'effects', 'audio'],
    },
    {
      id: 'filmora',
      name: 'Wondershare Filmora',
      kind: 'video',
      paths: [path.join(PF, 'Wondershare', 'Filmora', 'Filmora.exe')],
      capabilities: ['editing', 'effects', 'templates'],
    },
  ]
  for (const spec of specs) {
    const exe = await firstExisting(spec.paths)
    if (exe) {
      out.push({
        id: spec.id,
        name: spec.name,
        kind: spec.kind,
        exe,
        app: exe,
        available: true,
        automation: 'launch',
        capabilities: spec.capabilities,
      })
    }
  }
  return out
}

async function scanEditors(force = false) {
  if (!force && scanCache.value && Date.now() - scanCache.at < 60000) return scanCache.value
  const editors = []
  for (const id of Object.keys(CRAFT)) {
    const editor = await craftEditor(id)
    if (editor) editors.push(editor)
  }
  const [capcut, resolve, blender, ffmpeg, adobe, other] = await Promise.all([
    findCapCut(),
    findResolve(),
    findBlender(),
    findFFmpeg(),
    findAdobe(),
    findOtherEditors(),
  ])
  for (const editor of [capcut, resolve, blender, ffmpeg, ...adobe, ...other]) {
    if (editor) editors.push(editor)
  }
  editors.sort((a, b) => {
    const order = ['filmcraft', 'effectcraft', 'photocraft', 'lightcraft', 'jianying', 'capcut', 'resolve', 'premiere', 'aftereffects', 'photoshop']
    const ai = order.indexOf(a.id)
    const bi = order.indexOf(b.id)
    return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi) || a.name.localeCompare(b.name)
  })
  const routes = {
    editing: pick(editors, 'filmcraft', 'premiere', 'resolve', 'jianying', 'capcut', 'vegas', 'shotcut', 'kdenlive', 'ffmpeg'),
    effects: pick(editors, 'effectcraft', 'aftereffects', 'blender', 'resolve', 'filmcraft'),
    motionGraphics: pick(editors, 'effectcraft', 'aftereffects', 'blender'),
    colour: pick(editors, 'lightcraft', 'resolve', 'filmcraft', 'premiere'),
    photo: pick(editors, 'photocraft', 'lightcraft', 'photoshop', 'gimp'),
    raw: pick(editors, 'lightcraft', 'photocraft'),
  }
  const value = {
    platform: process.platform,
    scannedAt: new Date().toISOString(),
    editors,
    routes: Object.fromEntries(
      Object.entries(routes).map(([key, editor]) => [key, editor ? { id: editor.id, name: editor.name, automation: editor.automation } : null]),
    ),
    summary: {
      installed: editors.length,
      cliDriven: editors.filter((editor) => editor.automation === 'cli').length,
      videoEditors: editors.filter((editor) => editor.kind === 'video').length,
      vfxEditors: editors.filter((editor) => editor.kind === 'vfx').length,
      photoEditors: editors.filter((editor) => ['photo', 'raw'].includes(editor.kind)).length,
    },
  }
  scanCache.at = Date.now()
  scanCache.value = value
  return value
}

async function filmCli() {
  const editor = await craftEditor('filmcraft')
  if (!editor?.cli) throw new Error('FilmCraft CLI was not found on this PC.')
  return editor.cli
}

async function filmRunScript({ project, saveAs, steps, save = true, timeoutMs = 180000, demo = false }) {
  const { dir, file } = await tempScript(steps.map((step) => JSON.stringify(step)))
  try {
    const args = []
    if (demo) args.push('--demo')
    else if (saveAs) args.push('--save-as', saveAs)
    else if (project) args.push('--project', project)
    if (save && project && !saveAs && !demo) args.push('--save')
    args.push('--compact', 'run', file)
    const result = await runProcess(await filmCli(), args, { timeoutMs })
    const parsed = parseJsonLines(result.stdout)
    if (result.code !== 0) {
      const failed = parsed.find((line) => line && line.ok === false)
      const detail = failed
        ? `${failed.id} (line ${failed.line}): ${failed.error}`
        : (result.stderr || result.stdout || '').trim().slice(0, 1500)
      throw new Error(`FilmCraft command failed: ${detail}`)
    }
    return parsed
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => {})
  }
}

async function filmExec(project, id, params = {}) {
  const [line] = await filmRunScript({ project, steps: [{ id, params }], save: true })
  return line?.result
}

async function filmProbe(media) {
  const result = await runProcess(await filmCli(), ['--compact', 'probe', media], { timeoutMs: 60000 })
  if (result.code !== 0) throw new Error(`FilmCraft could not probe ${media}: ${(result.stderr || result.stdout).trim()}`)
  return parseJson(result.stdout)
}

async function filmCatalog(kind = 'Video', query = '') {
  const [line] = await filmRunScript({
    steps: [{ id: 'effects.list', params: { kind, detail: true } }],
    save: false,
    timeoutMs: 60000,
  })
  let effects = Array.isArray(line?.result) ? line.result : []
  const needle = String(query || '').toLowerCase()
  if (needle) {
    effects = effects.filter((effect) =>
      `${effect.id} ${effect.name} ${effect.folder || ''} ${effect.path || ''}`.toLowerCase().includes(needle),
    )
  }
  return effects.slice(0, 120).map((effect) => ({
    id: effect.id,
    name: effect.name,
    kind: effect.kind,
    folder: effect.folder || effect.path || '',
    params: effect.params || [],
  }))
}

async function filmInspect(project, kind = 'sequence') {
  const result = await runProcess(await filmCli(), ['--project', project, '--compact', 'inspect', kind], { timeoutMs: 60000 })
  if (result.code !== 0) throw new Error(`FilmCraft could not inspect the project: ${(result.stderr || result.stdout).trim()}`)
  return parseJson(result.stdout)
}

function flattenProject(node, out = []) {
  if (!node) return out
  if (node.item) out.push({ item: node.item, name: node.name, type: node.type, duration: node.duration })
  for (const child of node.children || []) flattenProject(child, out)
  return out
}

function summarizeSequence(sequence) {
  if (!sequence) return null
  const tracks = []
  for (const track of sequence.video || []) {
    tracks.push({
      kind: 'video',
      id: track.id,
      name: track.name,
      enabled: track.enabled,
      items: (track.items || []).map((item) => ({
        clip: item.clip,
        name: item.name,
        start: Number(item.start || 0) / TICKS_PER_SECOND,
        duration: Number(item.duration || 0) / TICKS_PER_SECOND,
        effects: (item.effects || []).map((effect) => effect.effect),
      })),
      transitions: (track.transitions || []).map((transition) => ({
        effect: transition.effect,
        from: transition.from,
        to: transition.to,
        seconds: Number(transition.duration || 0) / TICKS_PER_SECOND,
      })),
    })
  }
  for (const track of sequence.audio || []) {
    tracks.push({
      kind: 'audio',
      id: track.id,
      name: track.name,
      enabled: track.enabled,
      items: (track.items || []).map((item) => ({
        clip: item.clip,
        name: item.name,
        start: Number(item.start || 0) / TICKS_PER_SECOND,
        duration: Number(item.duration || 0) / TICKS_PER_SECOND,
      })),
    })
  }
  return {
    id: sequence.id,
    name: sequence.name,
    duration: Number(sequence.duration || 0) / TICKS_PER_SECOND,
    settings: sequence.settings,
    tracks,
  }
}

function normalizeEffectList(clip, width, height) {
  const effects = []
  if (Array.isArray(clip.effects)) {
    for (const effect of clip.effects) {
      if (typeof effect === 'string') effects.push({ name: effect, params: {} })
      else if (effect && typeof effect === 'object' && effect.name) effects.push({ name: effect.name, params: effect.params || {} })
    }
  }
  for (const effect of effects) {
    if (effect.name !== 'simple_text') continue
    const supplied = Object.fromEntries(Object.entries(effect.params || {}).filter(([, value]) => value !== undefined))
    effect.params = {
      size: Math.round(height * 0.08),
      color: '#ffffff',
      alignment: 'center',
      bg_opacity: 0,
      position: [Math.round(width / 2), Math.round(height * 0.82)],
      ...supplied,
    }
  }
  return effects
}

async function filmCompose(spec) {
  if (!Array.isArray(spec.clips) || spec.clips.length === 0) throw new Error('compose needs at least one clip.')
  const width = Number(spec.width || 1920)
  const height = Number(spec.height || 1080)
  const fps = Number(spec.fps || 30)
  const project = spec.project
    ? path.resolve(spec.project)
    : path.resolve(process.cwd(), 'output', `media-studio-${Date.now()}.fcproj`)
  await mkdir(path.dirname(project), { recursive: true })
  if (await exists(project)) {
    if (!spec.overwrite) throw new Error(`Project already exists: ${project}. Pass overwrite: true to replace it.`)
    await rm(project, { force: true })
  }
  const name = spec.name || path.basename(project, path.extname(project))
  const create = await filmRunScript({
    saveAs: project,
    save: true,
    steps: [
      { id: 'file.newProject', params: { name } },
      {
        id: 'file.newSequence',
        params: {
          name: 'Main',
          width,
          height,
          fps,
          video: 3,
          audio: 2,
        },
      },
    ],
  })
  const sequenceId = create.find((line) => line.id === 'file.newSequence')?.result?.sequence
  if (!sequenceId) throw new Error('FilmCraft did not create a sequence.')

  const clipSpecs = spec.clips.map((clip) => ({ ...clip, path: path.resolve(String(clip.path)) }))
  const importSteps = clipSpecs.map((clip) => ({ id: 'file.import', params: { paths: [clip.path] } }))
  const imported = await filmRunScript({ project, steps: importSteps, save: true })
  const itemIds = imported.map((line, index) => {
    const item = line?.result?.items?.[0]
    if (!item) throw new Error(`Could not import clip ${index + 1}: ${clipSpecs[index].path}`)
    if (Array.isArray(line?.result?.errors) && line.result.errors.length) {
      throw new Error(`Could not import ${clipSpecs[index].path}: ${line.result.errors.join('; ')}`)
    }
    return item
  })

  const clipInfo = []
  for (let index = 0; index < clipSpecs.length; index += 1) {
    const clip = clipSpecs[index]
    if (!(await isFile(clip.path))) throw new Error(`Clip does not exist: ${clip.path}`)
    let probe = null
    try {
      probe = await filmProbe(clip.path)
    } catch {
      // images and synthetic media may not probe, keep going
    }
    const probedSeconds = Number(probe?.duration || 0) / TICKS_PER_SECOND
    const still = /\.(png|jpe?g|tiff?|bmp|webp|gif|exr|dpx|tga)$/i.test(clip.path)
    const fullSeconds = probedSeconds > 0 ? probedSeconds : still ? 5 : 5
    const inSeconds = Math.max(0, Number(clip.in ?? clip.sourceIn ?? 0))
    const outSeconds = clip.out != null ? Number(clip.out) : null
    const duration = Math.max(
      0.05,
      Number(clip.duration ?? (outSeconds != null ? outSeconds - inSeconds : fullSeconds - inSeconds)),
    )
    clipInfo.push({
      index,
      path: clip.path,
      item: itemIds[index],
      inSeconds,
      duration,
      start: 0,
      probe,
      transition: clip.transition,
      effects: normalizeEffectList(clip, width, height),
      text: clip.text,
    })
  }

  let cursor = 0
  const placeSteps = clipInfo.map((clip) => {
    const start = cursor
    clip.start = start
    cursor += clip.duration
    return {
      id: 'timeline.place',
      params: {
        item: clip.item,
        track: 'V1',
        seconds: start,
        sourceIn: secondsToTicks(clip.inSeconds),
        duration: secondsToTicks(clip.duration),
      },
    }
  })
  const placed = await filmRunScript({ project, steps: placeSteps, save: true })
  for (let index = 0; index < clipInfo.length; index += 1) {
    const clipId = placed[index]?.result?.clips?.[0]
    if (!clipId) throw new Error(`FilmCraft did not place clip ${index + 1}.`)
    clipInfo[index].clip = clipId
  }

  const buildSteps = []
  for (let index = 0; index < clipInfo.length; index += 1) {
    const clip = clipInfo[index]
    const next = clipInfo[index + 1]
    if (clip.transition && next) {
      const transition = typeof clip.transition === 'string' ? { effect: clip.transition } : clip.transition
      if (transition.effect && transition.effect !== 'none') {
        buildSteps.push({
          id: 'sequence.applyVideoTransition',
          params: {
            clip: clip.clip,
            effect: transition.effect,
            frames: transition.frames ?? Math.max(1, Math.round(fps * 0.5)),
            edge: transition.edge ?? 'out',
            ...(transition.params ? { params: transition.params } : {}),
          },
        })
      }
    }
    for (const effect of clip.effects) {
      if (!effect.name || effect.name === 'none') continue
      buildSteps.push({ id: 'effects.apply', params: { clips: [clip.clip], effect: effect.name } })
      for (const [param, value] of Object.entries(effect.params || {})) {
        if (value === undefined) continue
        buildSteps.push({
          id: 'effects.setParam',
          params: { clip: clip.clip, effect: effect.name, param, value },
        })
      }
    }
  }

  const textLayers = []
  const textSteps = []
  for (const clip of clipInfo) {
    if (!clip.text) continue
    const text = typeof clip.text === 'string' ? { text: clip.text } : clip.text
    if (!text.text) continue
    const position = Array.isArray(text.position) ? text.position : [Math.round(width / 2), Math.round(height * 0.82)]
    textSteps.push({
      id: 'graphics.newText',
      params: {
        text: text.text,
        size: text.size ?? Math.round(height * 0.08),
        track: 1,
        time: secondsToTicks(clip.start),
        newClip: true,
        seconds: Math.min(clip.duration, Number(text.seconds ?? clip.duration)),
        position,
      },
    })
    textLayers.push({ clipIndex: clip.index, text, position })
  }
  if (textSteps.length) {
    const textCreated = await filmRunScript({ project, steps: textSteps, save: true })
    const styleSteps = []
    for (let index = 0; index < textLayers.length; index += 1) {
      const layer = textLayers[index]
      const created = textCreated[index]?.result
      layer.clip = created?.clip
      layer.layer = created?.layer ?? 0
      if (!layer.clip) continue
      styleSteps.push({
        id: 'graphics.set',
        params: {
          clip: layer.clip,
          layer: layer.layer,
          props: {
            align: layer.text.alignment ?? 'center',
            fill_color: layer.text.color ?? '#ffffff',
            ...(layer.text.font ? { font: layer.text.font } : {}),
          },
        },
      })
    }
    if (styleSteps.length) await filmRunScript({ project, steps: styleSteps, save: true })
    for (const layer of textLayers) {
      const target = clipInfo.find((clip) => clip.index === layer.clipIndex)
      if (target) target.textClip = layer.clip
    }
  }

  const music = Array.isArray(spec.music) ? spec.music : spec.music ? [spec.music] : []
  const musicInfo = []
  if (music.length) {
    const musicPaths = music.map((track) => path.resolve(String(track.path || track)))
    const musicImport = await filmRunScript({
      project,
      save: true,
      steps: musicPaths.map((musicPath) => ({ id: 'file.import', params: { paths: [musicPath] } })),
    })
    for (let index = 0; index < music.length; index += 1) {
      const track = music[index]
      const item = musicImport[index]?.result?.items?.[0]
      if (!item) throw new Error(`Could not import music: ${musicPaths[index]}`)
      let probe = null
      try {
        probe = await filmProbe(musicPaths[index])
      } catch {
        // optional
      }
      const sourceSeconds = Number(probe?.duration || 0) / TICKS_PER_SECOND
      const start = Math.max(0, Number(track.start ?? 0))
      const remaining = Math.max(0.1, cursor - start)
      const duration = Math.max(0.1, Math.min(sourceSeconds > 0 ? sourceSeconds : remaining, remaining))
      buildSteps.push({
        id: 'timeline.place',
        params: {
          item,
          track: 'A1',
          seconds: start,
          duration: secondsToTicks(duration),
          video: false,
          audio: true,
        },
      })
      musicInfo.push({ index, path: musicPaths[index], item, start, duration, gainDb: Number(track.gainDb ?? 0) })
    }
  }

  if (buildSteps.length) {
    const built = await filmRunScript({ project, steps: buildSteps, save: true })
    let musicCursor = 0
    for (const line of built) {
      if (line.id === 'timeline.place' && line.ok && line.result?.clips?.[0]) {
        if (musicCursor < musicInfo.length) musicInfo[musicCursor].clip = line.result.clips[0]
        musicCursor += 1
      }
    }
    const gainSteps = musicInfo
      .filter((track) => track.clip && track.gainDb)
      .map((track) => ({ id: 'clip.audioGain', params: { clips: [track.clip], mode: 'set', db: track.gainDb } }))
    if (gainSteps.length) await filmRunScript({ project, steps: gainSteps, save: true })
  }

  let exportResult = null
  if (spec.export) {
    const out = path.resolve(String(spec.export.path || path.join(path.dirname(project), `${name}.mp4`)))
    await mkdir(path.dirname(out), { recursive: true })
    const format = spec.export.format || path.extname(out).replace('.', '') || 'h264'
    const args = ['--project', project, 'export', out, '--format', format]
    if (spec.export.preset) args.push('--preset', String(spec.export.preset))
    if (spec.export.quality != null) args.push('--quality', String(spec.export.quality))
    if (spec.export.scale != null) args.push('--scale', String(spec.export.scale))
    if (spec.export.noAudio) args.push('--no-audio')
    if (spec.export.range) args.push('--range', String(spec.export.range))
    if (spec.export.startSeconds != null) args.push('--start', String(spec.export.startSeconds))
    if (spec.export.endSeconds != null) args.push('--end', String(spec.export.endSeconds))
    const settings = { ...(spec.export.settings || {}) }
    if (spec.export.width) settings.width = spec.export.width
    if (spec.export.height) settings.height = spec.export.height
    if (spec.export.fps) settings.fps = spec.export.fps
    if (Object.keys(settings).length) args.push('--settings', JSON.stringify(settings))
    const result = await runProcess(await filmCli(), args, { timeoutMs: 1800000 })
    if (result.code !== 0) {
      throw new Error(`FilmCraft export failed: ${(result.stderr || result.stdout).trim().slice(0, 2000)}`)
    }
    exportResult = parseJson(result.stdout)
  }

  return {
    ok: true,
    project,
    sequence: sequenceId,
    durationSeconds: cursor,
    settings: { width, height, fps },
    clips: clipInfo.map((clip) => ({
      path: clip.path,
      item: clip.item,
      clip: clip.clip,
      inSeconds: clip.inSeconds,
      duration: clip.duration,
      transition: clip.transition || null,
      effects: clip.effects.map((effect) => effect.name),
      text: clip.text || null,
      textClip: clip.textClip || null,
    })),
    music: musicInfo.map((track) => ({
      path: track.path,
      item: track.item,
      clip: track.clip,
      start: track.start,
      duration: track.duration,
      gainDb: track.gainDb,
    })),
    export: exportResult,
  }
}

async function effectCli() {
  const editor = await craftEditor('effectcraft')
  if (!editor?.cli) throw new Error('EffectCraft CLI was not found on this PC.')
  return editor.cli
}

async function effectInfo() {
  const result = await runProcess(await effectCli(), ['--demo', '--json', 'info'], { timeoutMs: 60000 })
  if (result.code !== 0) throw new Error(`EffectCraft info failed: ${(result.stderr || result.stdout).trim()}`)
  const info = parseJson(result.stdout)
  return {
    version: info.version,
    commands: info.commands,
    effects: info.effects,
    mode: info.mode,
    activeComp: info.activeComp
      ? {
          name: info.activeComp.name,
          width: info.activeComp.width,
          height: info.activeComp.height,
          duration: info.activeComp.duration,
          frameRate: info.activeComp.frameRate,
          layers: (info.activeComp.layers || []).length,
        }
      : null,
    renderer: info.project?.renderer,
  }
}

async function effectCommands(query = '') {
  const result = await runProcess(await effectCli(), ['commands', '--json'], { timeoutMs: 60000 })
  if (result.code !== 0) throw new Error(`EffectCraft commands failed: ${(result.stderr || result.stdout).trim()}`)
  let commands = parseJson(result.stdout)
  if (!Array.isArray(commands)) commands = []
  const needle = String(query || '').toLowerCase()
  if (needle) commands = commands.filter((command) => `${command.id} ${command.label}`.toLowerCase().includes(needle))
  return commands.slice(0, 100).map((command) => ({ id: command.id, label: command.label, params: command.params }))
}

async function effectExec({ project, commands, save = true, demo = false }) {
  const cli = await effectCli()
  const results = []
  for (const command of commands) {
    const args = []
    if (demo) args.push('--demo')
    else if (project) args.push('--project', project)
    if (save && project && !demo) args.push('--save')
    args.push('--json', 'exec', command.id, '--params', JSON.stringify(command.params || {}))
    const result = await runProcess(cli, args, { timeoutMs: 300000 })
    if (result.code !== 0) {
      throw new Error(`EffectCraft ${command.id} failed: ${(result.stderr || result.stdout).trim().slice(0, 1500)}`)
    }
    results.push({ id: command.id, result: parseJson(result.stdout) })
  }
  return results
}

async function effectScript({ project, code, save = true }) {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'dsh-effectcraft-'))
  const file = path.join(dir, 'script.jsx')
  try {
    await writeFile(file, code, 'utf8')
    const args = []
    if (project) args.push('--project', project)
    if (save && project) args.push('--save')
    args.push('script', file)
    const result = await runProcess(await effectCli(), args, { timeoutMs: 600000 })
    if (result.code !== 0) throw new Error(`EffectCraft script failed: ${(result.stderr || result.stdout).trim().slice(0, 3000)}`)
    return { ok: true, output: result.stdout.trim(), stderr: result.stderr.trim() || undefined }
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => {})
  }
}

async function effectRender({ project, comp, out, format = 'h264', start, end, scale, fps, transparent, quality }) {
  await mkdir(path.dirname(path.resolve(out)), { recursive: true })
  const args = []
  if (project) args.push('--project', project)
  else args.push('--demo')
  args.push('render', '--out', path.resolve(out), '--format', format)
  if (comp) args.push('--comp', String(comp))
  if (start != null) args.push('--start', String(start))
  if (end != null) args.push('--end', String(end))
  if (scale != null) args.push('--scale', String(scale))
  if (fps != null) args.push('--fps', String(fps))
  if (transparent) args.push('--channels', 'rgba')
  if (quality) args.push('--quality', String(quality))
  const result = await runProcess(await effectCli(), args, { timeoutMs: 1800000 })
  if (result.code !== 0) throw new Error(`EffectCraft render failed: ${(result.stderr || result.stdout).trim().slice(0, 2500)}`)
  return { out: path.resolve(out), output: result.stdout.trim(), stderr: result.stderr.trim() || undefined }
}

async function photoCli() {
  const editor = await craftEditor('photocraft')
  if (!editor?.cli) throw new Error('PhotoCraft CLI was not found on this PC.')
  return editor.cli
}

async function lightCli() {
  const editor = await craftEditor('lightcraft')
  if (!editor?.cli) throw new Error('LightCraft CLI was not found on this PC.')
  return editor.cli
}

async function photoCommands(query = '') {
  const result = await runProcess(await photoCli(), ['commands', '--json'], { timeoutMs: 60000 })
  if (result.code !== 0) throw new Error(`PhotoCraft commands failed: ${(result.stderr || result.stdout).trim()}`)
  let commands = parseJson(result.stdout)
  if (!Array.isArray(commands)) commands = []
  const needle = String(query || '').toLowerCase()
  if (needle) commands = commands.filter((command) => `${command.id} ${command.label}`.toLowerCase().includes(needle))
  return commands.slice(0, 100).map((command) => ({ id: command.id, label: command.label, params: command.params }))
}

async function photoRetouch({ input, output, commands = [], quality, format }) {
  await mkdir(path.dirname(path.resolve(output)), { recursive: true })
  const args = ['run', path.resolve(input), '--out', path.resolve(output)]
  for (const command of commands) {
    if (typeof command === 'string') args.push('--cmd', command)
    else if (command && command.id) {
      args.push('--cmd', String(command.id))
      if (command.params) args.push('--params', JSON.stringify(command.params))
    }
  }
  if (format) args.push('--format', String(format))
  if (quality != null) args.push('--quality', String(quality))
  const result = await runProcess(await photoCli(), args, { timeoutMs: 600000 })
  if (result.code !== 0) throw new Error(`PhotoCraft retouch failed: ${(result.stderr || result.stdout).trim().slice(0, 2500)}`)
  return { output: path.resolve(output), result: result.stdout.trim() }
}

async function photoConvert({ input, output, quality, format }) {
  await mkdir(path.dirname(path.resolve(output)), { recursive: true })
  const args = ['convert', path.resolve(input), path.resolve(output)]
  if (format) args.push('--format', String(format))
  if (quality != null) args.push('--quality', String(quality))
  const result = await runProcess(await photoCli(), args, { timeoutMs: 300000 })
  if (result.code !== 0) throw new Error(`PhotoCraft convert failed: ${(result.stderr || result.stdout).trim()}`)
  return { output: path.resolve(output), result: result.stdout.trim() }
}

async function photoBatch({ inputDir, outputDir, commands = [], format, quality }) {
  await mkdir(path.resolve(outputDir), { recursive: true })
  const dir = await mkdtemp(path.join(os.tmpdir(), 'dsh-photocraft-'))
  const actions = path.join(dir, 'actions.json')
  try {
    await writeFile(actions, JSON.stringify({ actions: commands }, null, 2), 'utf8')
    const args = ['batch', '--actions', actions, '--in', path.resolve(inputDir), '--out', path.resolve(outputDir)]
    if (format) args.push('--format', String(format))
    if (quality != null) args.push('--quality', String(quality))
    const result = await runProcess(await photoCli(), args, { timeoutMs: 1800000 })
    if (result.code !== 0) throw new Error(`PhotoCraft batch failed: ${(result.stderr || result.stdout).trim().slice(0, 2000)}`)
    return { outputDir: path.resolve(outputDir), result: result.stdout.trim() }
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => {})
  }
}

async function lightDevelop({ input, output, controls = {}, preset, size, quality, format }) {
  await mkdir(path.dirname(path.resolve(output)), { recursive: true })
  const args = ['render', path.resolve(input), '-o', path.resolve(output)]
  for (const [control, value] of Object.entries(controls || {})) {
    args.push('--set', `${control}=${typeof value === 'object' ? JSON.stringify(value) : value}`)
  }
  if (preset) args.push('--preset', String(preset))
  if (size != null) args.push('--size', String(size))
  if (quality != null) args.push('--quality', String(quality))
  const result = await runProcess(await lightCli(), args, { timeoutMs: 600000 })
  if (result.code !== 0) throw new Error(`LightCraft develop failed: ${(result.stderr || result.stdout).trim().slice(0, 2500)}`)
  return { output: path.resolve(output), result: result.stdout.trim() }
}

async function openInEditor({ editor, target }) {
  const scan = await scanEditors()
  let chosen = editor && editor !== 'auto' ? scan.editors.find((entry) => entry.id === editor) : undefined
  if (editor && editor !== 'auto' && !chosen) throw new Error(`Editor "${editor}" is not installed or was not detected.`)
  if (!chosen) {
    const ext = target ? path.extname(target).toLowerCase() : ''
    const byExt = {
      '.fcproj': 'filmcraft',
      '.ecproj': 'effectcraft',
      '.pcraft': 'photocraft',
      '.psd': 'photoshop',
      '.prproj': 'premiere',
      '.aep': 'aftereffects',
      '.blend': 'blender',
      '.dng': 'lightcraft',
      '.cr2': 'lightcraft',
      '.nef': 'lightcraft',
      '.arw': 'lightcraft',
      '.raf': 'lightcraft',
      '.mp4': 'filmcraft',
      '.mov': 'filmcraft',
      '.mkv': 'filmcraft',
      '.avi': 'filmcraft',
      '.wav': 'filmcraft',
      '.mp3': 'filmcraft',
      '.png': 'photocraft',
      '.jpg': 'photocraft',
      '.jpeg': 'photocraft',
      '.tif': 'photocraft',
      '.tiff': 'photocraft',
    }
    const wanted = byExt[ext]
    if (wanted) chosen = scan.editors.find((entry) => entry.id === wanted)
    if (!chosen) chosen = scan.editors.find((entry) => ['filmcraft', 'capcut', 'jianying', 'resolve', 'premiere'].includes(entry.id))
    if (!chosen) chosen = scan.editors[0]
  }
  if (!chosen) throw new Error('No supported editor was detected on this PC.')
  const exe = chosen.app || chosen.exe || chosen.cli
  if (!exe) throw new Error(`${chosen.name} has no launchable executable.`)
  const args = target ? [path.resolve(target)] : []
  const child = spawn(exe, args, {
    detached: true,
    stdio: 'ignore',
    windowsHide: false,
    cwd: target ? path.dirname(path.resolve(target)) : undefined,
  })
  child.unref()
  return {
    launched: true,
    editor: { id: chosen.id, name: chosen.name, automation: chosen.automation },
    executable: exe,
    args,
    pid: child.pid,
  }
}

function clean(value) {
  if (Array.isArray(value)) return value.map(clean)
  if (value && typeof value === 'object') {
    const out = {}
    for (const [key, item] of Object.entries(value)) {
      if (item !== undefined) out[key] = clean(item)
    }
    return out
  }
  return value
}

function textOutput(value) {
  return [
    {
      type: 'text',
      text: typeof value === 'string' ? value : JSON.stringify(clean(value), null, 2),
    },
  ]
}

const objectSchema = { type: 'object', additionalProperties: true }

export const name = 'media-studio'
export const inject = ['tools']

export function apply(ctx) {
  const register = (definition) =>
    ctx.effect(() =>
      ctx.tools.register({
        ...definition,
        async execute(args, exec) {
          const value = await definition.execute(args, exec)
          return clean(Array.isArray(value) ? { items: value } : value)
        },
      }),
    )

  register({
    name: 'media_studio_scan',
    description:
      'Scan this Windows PC for installed video, VFX, photo, RAW and audio editors (FilmCraft, EffectCraft, PhotoCraft, LightCraft, CapCut/Jianying, DaVinci Resolve, Adobe Premiere/After Effects/Photoshop, Blender, FFmpeg, OBS, GIMP, Shotcut, Kdenlive, VEGAS, Filmora). Returns exact executables, versions, automation level and the recommended app for each task. Call this first when the request mentions editing software or an unspecified editor.',
    parameters: {
      type: 'object',
      properties: {
        refresh: { type: 'boolean', description: 'Ignore the 60-second cache and rescan.' },
      },
      additionalProperties: false,
    },
    output: { schema: objectSchema, render: (_args, value) => textOutput(value) },
    timeoutMs: 120000,
    async execute(args) {
      return scanEditors(Boolean(args?.refresh))
    },
  })

  register({
    name: 'media_studio_video',
    description:
      'Edit video on a real FilmCraft timeline and create effects. compose builds a project from ordered clips with trims, transitions (cross dissolve, zoom blur, whip, glitch, wipe...), colour/Lumetri, 100s of video effects, burned-in titles, music and export. exec runs any of FilmCraft\'s 690 commands for precise or advanced work. catalog discovers effect and transition ids. probe reads media metadata. inspect summarises a project.',
    parameters: {
      type: 'object',
      properties: {
        action: {
          type: 'string',
          enum: ['compose', 'exec', 'catalog', 'probe', 'inspect', 'export'],
          description: 'compose = full edit; exec = raw FilmCraft commands; catalog = list effects/transitions; probe = media info; inspect = project summary; export = render an existing project.',
        },
        project: { type: 'string', description: 'Absolute or workspace-relative .fcproj path.' },
        name: { type: 'string', description: 'Project name for compose.' },
        width: { type: 'integer', description: 'Frame width, default 1920.' },
        height: { type: 'integer', description: 'Frame height, default 1080.' },
        fps: { type: 'number', description: 'Timeline frame rate, default 30.' },
        overwrite: { type: 'boolean', description: 'Replace an existing project path.' },
        clips: {
          type: 'array',
          description: 'Ordered clips for compose. Each clip is trimmed, placed on V1 and can carry a transition, effects and a burned-in title.',
          items: {
            type: 'object',
            properties: {
              path: { type: 'string' },
              in: { type: 'number', description: 'Source in-point in seconds.' },
              out: { type: 'number', description: 'Source out-point in seconds.' },
              duration: { type: 'number', description: 'Explicit duration in seconds; overrides out - in.' },
              transition: {
                description: 'Transition after this clip: a FilmCraft effect id (e.g. cross_dissolve, zoom_blur, whip, rgb_split) or {effect, frames, params}.',
                oneOf: [
                  { type: 'string' },
                  { type: 'object', additionalProperties: true },
                ],
              },
              effects: {
                type: 'array',
                description: 'Effects applied to this clip, e.g. [{name:"lumetri",params:{exposure:0.3,contrast:18}},{name:"camera_shake",params:{amount:12}}].',
                items: {
                  oneOf: [
                    { type: 'string' },
                    { type: 'object', additionalProperties: true },
                  ],
                },
              },
              text: {
                description: 'Burned-in title: a string or {text,size,color,font,alignment,bgOpacity,position:[x,y]}.',
                oneOf: [
                  { type: 'string' },
                  { type: 'object', additionalProperties: true },
                ],
              },
            },
            required: ['path'],
            additionalProperties: true,
          },
        },
        music: {
          type: 'array',
          description: 'Music beds: [{path, start?, gainDb?}]. Trimmed to the picture length.',
          items: { type: 'object', additionalProperties: true },
        },
        export: {
          type: 'object',
          description: 'Export settings: {path, format:"h264", quality:80, width?, height?, fps?, preset?, scale?, range?, startSeconds?, endSeconds?, noAudio?}.',
          additionalProperties: true,
        },
        commands: {
          type: 'array',
          description: 'For exec: [{id:"effects.apply", params:{...}}] in FilmCraft command order.',
          items: { type: 'object', additionalProperties: true },
        },
        kind: { type: 'string', description: 'For catalog: Video, Audio, VideoTransition or AudioTransition.' },
        query: { type: 'string', description: 'For catalog: filter effect names/ids.' },
        path: { type: 'string', description: 'For probe: media file path.' },
        save: { type: 'boolean', description: 'For exec: save the project after running, default true.' },
        demo: { type: 'boolean', description: 'For exec/inspect: operate on FilmCraft\'s demo project.' },
      },
      required: ['action'],
      additionalProperties: false,
    },
    output: { schema: objectSchema, render: (_args, value) => textOutput(value) },
    timeoutMs: 1800000,
    async execute(args) {
      const action = args?.action
      if (action === 'scan') return scanEditors(false)
      if (action === 'compose') return filmCompose(args)
      if (action === 'probe') {
        if (!args.path) throw new Error('probe needs path.')
        return filmProbe(path.resolve(args.path))
      }
      if (action === 'catalog') return filmCatalog(args.kind || 'Video', args.query || '')
      if (action === 'inspect') {
        if (!args.project) throw new Error('inspect needs project.')
        const project = path.resolve(args.project)
        const projectInfo = await filmInspect(project, 'project')
        const sequenceInfo = await filmInspect(project, 'sequence')
        return {
          project: {
            name: projectInfo?.name,
            path: projectInfo?.path,
            activeSequence: projectInfo?.activeSequence,
            items: flattenProject(projectInfo?.root).slice(0, 100),
          },
          sequence: summarizeSequence(sequenceInfo),
        }
      }
      if (action === 'export') {
        if (!args.project || !args.export?.path) throw new Error('export needs project and export.path.')
        await mkdir(path.dirname(path.resolve(args.export.path)), { recursive: true })
        const format = args.export.format || 'h264'
        const cliArgs = ['--project', path.resolve(args.project), 'export', path.resolve(args.export.path), '--format', format]
        for (const [key, flag] of [
          ['preset', '--preset'],
          ['quality', '--quality'],
          ['scale', '--scale'],
          ['range', '--range'],
          ['startSeconds', '--start'],
          ['endSeconds', '--end'],
        ]) {
          if (args.export[key] != null) cliArgs.push(flag, String(args.export[key]))
        }
        if (args.export.noAudio) cliArgs.push('--no-audio')
        const settings = args.export.settings || {}
        if (Object.keys(settings).length) cliArgs.push('--settings', JSON.stringify(settings))
        const result = await runProcess(await filmCli(), cliArgs, { timeoutMs: 1800000 })
        if (result.code !== 0) throw new Error(`FilmCraft export failed: ${(result.stderr || result.stdout).trim().slice(0, 2000)}`)
        return parseJson(result.stdout)
      }
      if (action === 'exec') {
        if (!Array.isArray(args.commands) || args.commands.length === 0) throw new Error('exec needs commands.')
        const lines = await filmRunScript({
          project: args.project ? path.resolve(args.project) : undefined,
          demo: Boolean(args.demo),
          steps: args.commands.map((command) => ({ id: command.id, params: command.params || {} })),
          save: args.save !== false,
        })
        return lines
      }
      throw new Error(`Unknown video action: ${action}`)
    },
  })

  register({
    name: 'media_studio_vfx',
    description:
      'Create motion graphics, compositing and VFX in EffectCraft (After Effects-style). info summarises the engine and demo comp; commands lists 660+ commands; exec runs EffectCraft commands; script runs JavaScript with app.project/CompItem/Layer/properties; render outputs a comp to H.264/ProRes/PNG sequence/WebM with optional alpha. Use this for keying, 3D, particles, expressions, lower thirds and animated titles.',
    parameters: {
      type: 'object',
      properties: {
        action: {
          type: 'string',
          enum: ['info', 'commands', 'exec', 'script', 'render'],
          description: 'Operation to perform.',
        },
        project: { type: 'string', description: 'EffectCraft .ecproj path. Omit to use the demo project for exec/render.' },
        comp: { type: 'string', description: 'Composition id, name or "-" for active comp.' },
        code: { type: 'string', description: 'JavaScript for action=script.' },
        commands: {
          type: 'array',
          description: 'For exec: [{id, params}] EffectCraft commands, run in order.',
          items: { type: 'object', additionalProperties: true },
        },
        out: { type: 'string', description: 'Output path for render.' },
        format: { type: 'string', description: 'Render format: h264, hevc, prores, webm, png, jpeg, exr, gif, wav (default h264).' },
        start: { type: 'number', description: 'Render start in seconds.' },
        end: { type: 'number', description: 'Render end in seconds.' },
        scale: { type: 'number', description: 'Render scale (0.5 = half).' },
        fps: { type: 'number', description: 'Render frame rate.' },
        transparent: { type: 'boolean', description: 'Render RGBA with alpha when the format supports it.' },
        quality: { type: 'string', description: 'best or draft.' },
        query: { type: 'string', description: 'For commands: filter.' },
        save: { type: 'boolean', description: 'Save the project after exec/script, default true.' },
        demo: { type: 'boolean', description: 'Run exec on the demo project.' },
      },
      required: ['action'],
      additionalProperties: false,
    },
    output: { schema: objectSchema, render: (_args, value) => textOutput(value) },
    timeoutMs: 1800000,
    async execute(args) {
      const action = args?.action
      if (action === 'info') return effectInfo()
      if (action === 'commands') return effectCommands(args.query || '')
      if (action === 'exec') {
        if (!Array.isArray(args.commands) || !args.commands.length) throw new Error('exec needs commands.')
        return effectExec({
          project: args.project ? path.resolve(args.project) : undefined,
          commands: args.commands,
          save: args.save !== false,
          demo: Boolean(args.demo),
        })
      }
      if (action === 'script') {
        if (!args.code) throw new Error('script needs code.')
        return effectScript({
          project: args.project ? path.resolve(args.project) : undefined,
          code: args.code,
          save: args.save !== false,
        })
      }
      if (action === 'render') {
        if (!args.out) throw new Error('render needs out.')
        return effectRender({
          project: args.project ? path.resolve(args.project) : undefined,
          comp: args.comp,
          out: args.out,
          format: args.format || 'h264',
          start: args.start,
          end: args.end,
          scale: args.scale,
          fps: args.fps,
          transparent: Boolean(args.transparent),
          quality: args.quality,
        })
      }
      throw new Error(`Unknown VFX action: ${action}`)
    },
  })

  register({
    name: 'media_studio_photo',
    description:
      'Retouch photos with PhotoCraft (Photoshop-style layers, adjustments, filters, masks, PSD, batch/droplets) and develop RAW/JPEG with LightCraft (exposure, colour, presets, HDR/panorama merge). retouch runs PhotoCraft commands on an image; develop renders a LightCraft develop; convert changes format; batch applies commands to a folder; commands lists the PhotoCraft command registry.',
    parameters: {
      type: 'object',
      properties: {
        action: {
          type: 'string',
          enum: ['info', 'retouch', 'develop', 'convert', 'batch', 'commands'],
          description: 'Operation to perform.',
        },
        app: { type: 'string', enum: ['photocraft', 'lightcraft'], description: 'For info/commands: which app.' },
        input: { type: 'string', description: 'Input image/RAW path.' },
        output: { type: 'string', description: 'Output image path.' },
        inputDir: { type: 'string', description: 'For batch: input folder.' },
        outputDir: { type: 'string', description: 'For batch: output folder.' },
        commands: {
          type: 'array',
          description: 'PhotoCraft commands: ["image.adjustments.levels", {id:"filter.sharpen.unsharpMask", params:{...}}].',
          items: {
            oneOf: [
              { type: 'string' },
              { type: 'object', additionalProperties: true },
            ],
          },
        },
        controls: {
          type: 'object',
          description: 'LightCraft develop controls, e.g. {"light.exposure":0.6,"light.contrast":15,"color.saturation":10}.',
          additionalProperties: true,
        },
        preset: { type: 'string', description: 'LightCraft preset id.' },
        size: { type: 'integer', description: 'Long edge for develop output.' },
        quality: { type: 'integer', description: 'JPEG/WebP/AVIF quality 1-100.' },
        format: { type: 'string', description: 'Output format/extension for retouch/convert/batch.' },
        query: { type: 'string', description: 'For commands: filter.' },
      },
      required: ['action'],
      additionalProperties: false,
    },
    output: { schema: objectSchema, render: (_args, value) => textOutput(value) },
    timeoutMs: 1800000,
    async execute(args) {
      const action = args?.action
      if (action === 'info') {
        const scan = await scanEditors()
        return {
          editors: scan.editors.filter((editor) => ['photocraft', 'lightcraft', 'photoshop', 'gimp'].includes(editor.id)),
          routes: { photo: scan.routes.photo, raw: scan.routes.raw },
        }
      }
      if (action === 'commands') return photoCommands(args.query || '')
      if (action === 'retouch') {
        if (!args.input || !args.output) throw new Error('retouch needs input and output.')
        return photoRetouch({
          input: args.input,
          output: args.output,
          commands: args.commands || [],
          quality: args.quality,
          format: args.format,
        })
      }
      if (action === 'convert') {
        if (!args.input || !args.output) throw new Error('convert needs input and output.')
        return photoConvert({ input: args.input, output: args.output, quality: args.quality, format: args.format })
      }
      if (action === 'batch') {
        if (!args.inputDir || !args.outputDir) throw new Error('batch needs inputDir and outputDir.')
        return photoBatch({
          inputDir: args.inputDir,
          outputDir: args.outputDir,
          commands: args.commands || [],
          format: args.format,
          quality: args.quality,
        })
      }
      if (action === 'develop') {
        if (!args.input || !args.output) throw new Error('develop needs input and output.')
        return lightDevelop({
          input: args.input,
          output: args.output,
          controls: args.controls || {},
          preset: args.preset,
          size: args.size,
          quality: args.quality,
          format: args.format,
        })
      }
      throw new Error(`Unknown photo action: ${action}`)
    },
  })

  register({
    name: 'media_studio_open',
    description:
      'Open a project or media file in the best installed editor, or launch a specific editor. Use this for manual finishing in FilmCraft, EffectCraft, PhotoCraft, LightCraft, CapCut/Jianying, DaVinci Resolve, Adobe Premiere/After Effects/Photoshop, Blender, OBS, GIMP, Shotcut or Kdenlive. editor="auto" picks by file extension.',
    parameters: {
      type: 'object',
      properties: {
        editor: { type: 'string', description: 'Editor id from media_studio_scan, or auto.' },
        path: { type: 'string', description: 'Project or media file to open.' },
      },
      additionalProperties: false,
    },
    output: { schema: objectSchema, render: (_args, value) => textOutput(value) },
    timeoutMs: 30000,
    async execute(args) {
      return openInEditor({ editor: args?.editor || 'auto', target: args?.path })
    },
  })
}
