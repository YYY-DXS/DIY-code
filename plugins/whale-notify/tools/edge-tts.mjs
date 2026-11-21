/**
 * Minimal Edge neural-TTS client for the Host process.
 *
 * The plugin's spawned Python children cannot reach the speech endpoint in this
 * environment, so the Host talks to the same service itself over the global
 * WebSocket (Node 22) and writes the returned mp3. The voice, rate and pitch are
 * the same ones the pre-generated clips use.
 */
import { randomUUID } from 'node:crypto'
import { writeFileSync } from 'node:fs'

const TRUSTED_TOKEN = '6A5AA1D4EAFF4E9FB37E23D68491D6F4'
const ENDPOINT = `wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=${TRUSTED_TOKEN}`

/**
 * Escape text for the SSML body.
 * @param {string} value - raw text.
 * @returns {string} escaped text.
 */
function escapeXml(value) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

/**
 * Build the SSML payload for one line.
 * @param {string} text - line to speak.
 * @param {string} voice - Edge voice id.
 * @param {string} rate - prosody rate, such as `-4%`.
 * @param {string} pitch - prosody pitch, such as `+4Hz`.
 * @returns {string} SSML document.
 */
function buildSsml(text, voice, rate, pitch) {
  return `<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='zh-CN'>`
    + `<voice name='${voice}'><prosody rate='${rate}' pitch='${pitch}'>${escapeXml(text)}</prosody></voice>`
    + '</speak>'
}

/**
 * Synthesise one line to an mp3 file.
 * @param {object} options - synthesis options.
 * @param {string} options.text - line to speak.
 * @param {string} options.out - destination mp3 path.
 * @param {string} [options.voice] - Edge voice id.
 * @param {string} [options.rate] - prosody rate.
 * @param {string} [options.pitch] - prosody pitch.
 * @param {number} [options.timeoutMs] - overall budget.
 * @returns {Promise<boolean>} whether the file was written.
 */
export function synthesize({ text, out, voice = 'zh-CN-XiaoyiNeural', rate = '-4%', pitch = '+4Hz', timeoutMs = 15000 }) {
  return new Promise((resolve) => {
    const Ctor = globalThis.WebSocket
    if (typeof Ctor !== 'function') {
      resolve(false)
      return
    }
    const requestId = randomUUID().replace(/-/g, '')
    const connectionId = randomUUID().replace(/-/g, '')
    const socket = new Ctor(`${ENDPOINT}&ConnectionId=${connectionId}`)
    socket.binaryType = 'arraybuffer'
    const chunks = []
    let settled = false
    const finish = (ok) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      try {
        socket.close()
      } catch (error) {
        // Already closed.
      }
      if (ok && chunks.length > 0) {
        try {
          writeFileSync(out, Buffer.concat(chunks))
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

    socket.addEventListener('open', () => {
      socket.send(
        'Content-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n'
        + JSON.stringify({
          context: { synthesis: { audio: { metadataoptions: { sentenceBoundaryEnabled: false, wordBoundaryEnabled: false }, outputFormat: 'audio-24khz-48kbitrate-mono-mp3' } } },
        }),
      )
      const stamp = new Date().toISOString()
      socket.send(
        `X-RequestId:${requestId}\r\nContent-Type:application/ssml+xml\r\nX-Timestamp:${stamp}Z\r\nPath:ssml\r\n\r\n`
        + buildSsml(text, voice, rate, pitch),
      )
    })
    socket.addEventListener('message', (event) => {
      const data = event.data
      if (typeof data === 'string') {
        if (data.includes('Path:turn.end')) finish(true)
        return
      }
      const buffer = Buffer.from(data)
      if (buffer.length < 2) return
      const headerLength = buffer.readUInt16BE(0)
      if (buffer.length <= 2 + headerLength) return
      chunks.push(buffer.subarray(2 + headerLength))
    })
    socket.addEventListener('error', () => finish(false))
    socket.addEventListener('close', () => finish(chunks.length > 0))
  })
}
