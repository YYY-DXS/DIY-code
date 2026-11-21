/**
 * Azure Speech (free F0 tier) synthesis with real emotion styles.
 *
 * Credentials, in order: `AZURE_SPEECH_KEY` / `AZURE_SPEECH_REGION` environment
 * variables, then `%TEMP%/dsh-whale-pet/azure.json` (`{ "key": "...", "region": "..." }`).
 * The file stays outside the repository so the key is never committed.
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { request as httpsRequest } from 'node:https'

/** Where the runtime keeps its private configuration. */
const CONFIG_PATH = join(tmpdir(), 'dsh-whale-pet', 'azure.json')

/**
 * Read the Azure credentials, if any.
 * @returns {{ key: string, region: string } | undefined} usable credentials.
 */
export function azureCredentials() {
  const key = process.env.AZURE_SPEECH_KEY ?? ''
  const region = process.env.AZURE_SPEECH_REGION ?? ''
  if (key !== '' && region !== '') return { key, region }
  try {
    if (!existsSync(CONFIG_PATH)) return undefined
    const parsed = JSON.parse(readFileSync(CONFIG_PATH, 'utf8'))
    if (typeof parsed.key === 'string' && parsed.key !== '' && typeof parsed.region === 'string' && parsed.region !== '') {
      return { key: parsed.key, region: parsed.region }
    }
  } catch (error) {
    // A missing or broken config simply disables Azure.
  }
  return undefined
}

/** @returns {boolean} whether Azure synthesis is configured. */
export const hasAzure = () => azureCredentials() !== undefined

/** Escape text for the SSML body. */
const escapeXml = (value) => value
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&apos;')

/**
 * Build the SSML document, optionally wrapped in an emotion style.
 * @param {object} options - SSML options.
 * @param {string} options.text - line to speak.
 * @param {string} options.voice - Azure voice name.
 * @param {string} options.rate - prosody rate.
 * @param {string} options.pitch - prosody pitch.
 * @param {string} [options.style] - mstts style, such as `cheerful`.
 * @param {number} [options.styleDegree] - style intensity, 0.5 to 2.
 * @returns {string} SSML document.
 */
function buildSsml({ text, voice, rate, pitch, style, styleDegree }) {
  const prosody = `<prosody rate='${rate}' pitch='${pitch}'>${escapeXml(text)}</prosody>`
  const body = style === undefined || style === ''
    ? prosody
    : `<mstts:express-as style='${style}' styledegree='${styleDegree}'>${prosody}</mstts:express-as>`
  return `<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xmlns:mstts='http://www.w3.org/2001/mstts' xml:lang='zh-CN'>`
    + `<voice name='${voice}'>${body}</voice></speak>`
}

/**
 * Synthesise one line through Azure Speech.
 * @param {object} options - synthesis options.
 * @param {string} options.text - line to speak.
 * @param {string} options.out - destination mp3 path.
 * @param {string} [options.voice] - Azure voice name.
 * @param {string} [options.style] - emotion style.
 * @param {number} [options.styleDegree] - style intensity.
 * @param {string} [options.rate] - prosody rate.
 * @param {string} [options.pitch] - prosody pitch.
 * @param {number} [options.timeoutMs] - request budget.
 * @returns {Promise<boolean>} whether the file was written.
 */
export function synthesizeAzure({ text, out, voice = 'zh-CN-XiaoxiaoNeural', style = '', styleDegree = 1.4, rate = '-4%', pitch = '+4Hz', timeoutMs = 15000 }) {
  const credentials = azureCredentials()
  if (credentials === undefined) return Promise.resolve(false)
  return new Promise((resolve) => {
    const body = Buffer.from(buildSsml({ text, voice, rate, pitch, style, styleDegree }), 'utf8')
    let settled = false
    const finish = (ok, audio) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      if (ok && audio !== undefined && audio.length > 0) {
        try {
          writeFileSync(out, audio)
          resolve(true)
          return
        } catch (error) {
          resolve(false)
          return
        }
      }
      resolve(false)
    }
    const timer = setTimeout(() => finish(false), timeoutMs)
    const req = httpsRequest({
      host: `${credentials.region}.tts.speech.microsoft.com`,
      path: '/cognitiveservices/v1',
      method: 'POST',
      headers: {
        'Ocp-Apim-Subscription-Key': credentials.key,
        'Content-Type': 'application/ssml+xml',
        'X-Microsoft-OutputFormat': 'audio-24khz-48kbitrate-mono-mp3',
        'User-Agent': 'dsh-whale-notify',
      },
      timeout: timeoutMs,
    }, (response) => {
      const chunks = []
      response.on('data', (chunk) => chunks.push(chunk))
      response.on('end', () => {
        if (response.statusCode !== 200) {
          finish(false)
          return
        }
        finish(true, Buffer.concat(chunks))
      })
    })
    req.on('error', () => finish(false))
    req.on('timeout', () => finish(false))
    req.end(body)
  })
}
