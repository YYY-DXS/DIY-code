/**
 * MiniMax speech-2.8-hd through Alibaba Cloud Model Studio (Bailian / DashScope).
 *
 * Credentials, in order: `DASHSCOPE_API_KEY` environment variable, then
 * `%TEMP%/dsh-whale-pet/dashscope.json` (`{"key": "sk-...", "voice_id": "..."}`).
 * The file stays outside the repository so the key is never committed.
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { request as httpsRequest } from 'node:https'

const CONFIG_PATH = join(tmpdir(), 'dsh-whale-pet', 'dashscope.json')
const ENDPOINT = 'https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation'
const MODEL = 'MiniMax/speech-2.8-hd'
/** MiniMax's default Chinese female voice; override in the config file. */
const DEFAULT_VOICE = 'female-shaonv'

/**
 * Read the DashScope credentials, if any.
 * @returns {{ key: string, voiceId: string } | undefined} usable credentials.
 */
export function minimaxCredentials() {
  const key = process.env.DASHSCOPE_API_KEY ?? ''
  const voiceId = process.env.MINIMAX_VOICE_ID ?? ''
  if (key !== '') return { key, voiceId: voiceId === '' ? DEFAULT_VOICE : voiceId }
  try {
    if (!existsSync(CONFIG_PATH)) return undefined
    const parsed = JSON.parse(readFileSync(CONFIG_PATH, 'utf8'))
    if (typeof parsed.key === 'string' && parsed.key !== '') {
      return { key: parsed.key, voiceId: typeof parsed.voice_id === 'string' && parsed.voice_id !== '' ? parsed.voice_id : DEFAULT_VOICE }
    }
  } catch (error) {
    // A missing or broken config simply disables MiniMax.
  }
  return undefined
}

/** @returns {boolean} whether MiniMax synthesis is configured. */
export const hasMinimax = () => minimaxCredentials() !== undefined

/** Map a neutral emotion to the MiniMax value. */
const minimaxEmotion = (emotion) => {
  if (emotion === 'affectionate' || emotion === 'gentle') return 'calm'
  if (emotion === 'happy' || emotion === 'sad' || emotion === 'angry') return emotion
  return 'calm'
}

/**
 * Synthesise one line through MiniMax.
 * @param {object} options - synthesis options.
 * @param {string} options.text - line to speak.
 * @param {string} options.out - destination mp3 path.
 * @param {string} [options.emotion] - neutral emotion name.
 * @param {number} [options.speed] - 0.5 to 2.0.
 * @param {number} [options.pitch] - -12 to 12.
 * @param {number} [options.timeoutMs] - request budget.
 * @returns {Promise<boolean>} whether the file was written.
 */
export function synthesizeMinimax({ text, out, emotion = 'calm', speed = 1, pitch = 0, timeoutMs = 20000 }) {
  const credentials = minimaxCredentials()
  if (credentials === undefined) return Promise.resolve(false)
  const body = Buffer.from(JSON.stringify({
    model: MODEL,
    input: {
      text,
      voice_setting: {
        voice_id: credentials.voiceId,
        speed,
        vol: 1,
        pitch,
        emotion: minimaxEmotion(emotion),
      },
      audio_setting: { sample_rate: 32000, bitrate: 128000, format: 'mp3', channel: 1 },
      language_boost: 'Chinese',
    },
    output_format: 'hex',
  }), 'utf8')
  return new Promise((resolve) => {
    let settled = false
    const finish = (ok, payload) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      if (!ok || payload === undefined) {
        resolve(false)
        return
      }
      try {
        writeFileSync(out, Buffer.from(payload, 'hex'))
        resolve(true)
      } catch (error) {
        resolve(false)
      }
    }
    const timer = setTimeout(() => finish(false), timeoutMs)
    const req = httpsRequest({
      host: 'dashscope.aliyuncs.com',
      path: '/api/v1/services/aigc/multimodal-generation/generation',
      method: 'POST',
      headers: {
        Authorization: `Bearer ${credentials.key}`,
        'Content-Type': 'application/json',
        'Content-Length': body.length,
      },
      timeout: timeoutMs,
    }, (response) => {
      const chunks = []
      response.on('data', (chunk) => chunks.push(chunk))
      response.on('end', () => {
        let parsed
        try {
          parsed = JSON.parse(Buffer.concat(chunks).toString('utf8'))
        } catch (error) {
          finish(false)
          return
        }
        const status = parsed?.output?.base_resp?.status_code
        if (response.statusCode !== 200 || status !== 0) {
          finish(false)
          return
        }
        const audio = parsed?.output?.data?.audio
        if (typeof audio !== 'string' || audio === '') {
          finish(false)
          return
        }
        finish(true, audio)
      })
    })
    req.on('error', () => finish(false))
    req.on('timeout', () => finish(false))
    req.end(body)
  })
}

export { ENDPOINT, MODEL, DEFAULT_VOICE }
