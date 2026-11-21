/**
 * Edge neural-TTS client for the Host process.
 *
 * Constraints that shaped it:
 *  1. the plugin's spawned children have no network, so synthesis runs inside
 *     the Host process;
 *  2. the handshake carries a `Sec-MS-GEC` v2 token — see `drm.mjs`.
 */
import { randomBytes, randomUUID } from 'node:crypto'
import { writeFileSync } from 'node:fs'
import { request as httpsRequest } from 'node:https'
import { secMsGecV2 } from './drm.mjs'

const TRUSTED_TOKEN = '6A5AA1D4EAFF4E9FB37E23D68491D6F4'
const HOST = 'speech.platform.bing.com'
const CHROMIUM = '143.0.3650.75'
const CHROMIUM_MAJOR = '143'
const GEC_VERSION = `2-${CHROMIUM}`

/** Escape text for the SSML body. */
const escapeXml = (value) => value
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&apos;')

/**
 * Build one masked client frame.
 * @param {number} opcode - frame opcode.
 * @param {Buffer} payload - frame body.
 * @returns {Buffer} complete frame.
 */
function clientFrame(opcode, payload) {
  const length = payload.length
  let header
  if (length < 126) {
    header = Buffer.alloc(2)
    header[1] = 0x80 | length
  } else if (length < 65536) {
    header = Buffer.alloc(4)
    header[1] = 0x80 | 126
    header.writeUInt16BE(length, 2)
  } else {
    header = Buffer.alloc(10)
    header[1] = 0x80 | 127
    header.writeBigUInt64BE(BigInt(length), 2)
  }
  header[0] = 0x80 | opcode
  const mask = randomBytes(4)
  const masked = Buffer.alloc(length)
  for (let index = 0; index < length; index += 1) masked[index] = payload[index] ^ mask[index & 3]
  return Buffer.concat([header, mask, masked])
}

/**
 * Synthesise one line to an mp3 file.
 * @param {object} options - synthesis options.
 * @param {string} options.text - line to speak.
 * @param {string} options.out - destination mp3 path.
 * @param {string} [options.voice] - Edge voice id.
 * @param {string} [options.rate] - prosody rate, such as `-4%`.
 * @param {string} [options.pitch] - prosody pitch, such as `+4Hz`.
 * @param {number} [options.timeoutMs] - overall budget.
 * @returns {Promise<boolean>} whether the file was written.
 */
export function synthesize({ text, out, voice = 'zh-CN-XiaoyiNeural', rate = '-4%', pitch = '+4Hz', timeoutMs = 15000 }) {
  return new Promise((resolve) => {
    const requestId = randomUUID().replace(/-/g, '')
    const audio = []
    let settled = false
    let socket
    const debug = (message) => { if (process.env.WHALE_TTS_DEBUG) console.log('[tts]', message) }
    const finish = (ok) => {
      debug(`finish ok=${ok} audio=${audio.length}`)
      if (settled) return
      settled = true
      clearTimeout(timer)
      try {
        socket?.destroy()
      } catch (error) {
        // Already gone.
      }
      if (ok && audio.length > 0) {
        try {
          writeFileSync(out, Buffer.concat(audio))
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
      host: HOST,
      path: `/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=${TRUSTED_TOKEN}`
        + `&Sec-MS-GEC=${secMsGecV2(Math.floor(Date.now() / 1000), TRUSTED_TOKEN)}`
        + `&Sec-MS-GEC-Version=${GEC_VERSION}`,
      method: 'GET',
      headers: {
        Connection: 'Upgrade',
        Upgrade: 'websocket',
        'Sec-WebSocket-Key': randomBytes(16).toString('base64'),
        'Sec-WebSocket-Version': '13',
        Origin: 'chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold',
        Pragma: 'no-cache',
        'Cache-Control': 'no-cache',
        'Accept-Language': 'en-US,en;q=0.9',
        'User-Agent': `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${CHROMIUM_MAJOR}.0.0.0 Safari/537.36 Edg/${CHROMIUM_MAJOR}.0.0.0`,
        'Sec-CH-UA': `" Not;A Brand";v="99", "Microsoft Edge";v="${CHROMIUM_MAJOR}", "Chromium";v="${CHROMIUM_MAJOR}"`,
        'Sec-CH-UA-Mobile': '?0',
        Cookie: `muid=${randomBytes(16).toString('hex').toUpperCase()};`,
      },
      timeout: timeoutMs,
    })

    req.on('error', () => finish(false))
    req.on('timeout', () => finish(false))
    req.on('response', (response) => {
      debug(`response ${response.statusCode}`)
      response.resume()
      finish(false)
    })
    req.on('upgrade', (_response, upgraded) => {
      debug('upgrade')
      socket = upgraded
      socket.setNoDelay(true)
      socket.on('error', () => finish(false))
      socket.on('close', () => finish(audio.length > 0))

      socket.write(clientFrame(0x1, Buffer.from(
        `Content-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n${JSON.stringify({
          context: { synthesis: { audio: { metadataoptions: { sentenceBoundaryEnabled: false, wordBoundaryEnabled: false }, outputFormat: 'audio-24khz-48kbitrate-mono-mp3' } } },
        })}`, 'utf8')))
      socket.write(clientFrame(0x1, Buffer.from(
        `X-RequestId:${requestId}\r\nContent-Type:application/ssml+xml\r\nX-Timestamp:${new Date().toISOString()}Z\r\nPath:ssml\r\n\r\n`
        + `<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='zh-CN'><voice name='${voice}'><prosody rate='${rate}' pitch='${pitch}'>${escapeXml(text)}</prosody></voice></speak>`, 'utf8')))

      let pending = Buffer.alloc(0)
      socket.on('data', (chunk) => {
        pending = Buffer.concat([pending, chunk])
        for (;;) {
          if (pending.length < 2) return
          const opcode = pending[0] & 0x0f
          let length = pending[1] & 0x7f
          let offset = 2
          if (length === 126) {
            if (pending.length < 4) return
            length = pending.readUInt16BE(2)
            offset = 4
          } else if (length === 127) {
            if (pending.length < 10) return
            length = Number(pending.readBigUInt64BE(2))
            offset = 10
          }
          if (pending.length < offset + length) return
          const payload = pending.subarray(offset, offset + length)
          pending = pending.subarray(offset + length)
          if (opcode === 0x2) {
            if (payload.length > 2) audio.push(Buffer.from(payload.subarray(2 + payload.readUInt16BE(0))))
          } else if (opcode === 0x1) {
            if (process.env.WHALE_TTS_DEBUG && payload.length < 400) debug(`text frame ${payload.length}`)
            if (payload.includes('Path:turn.end')) {
              finish(true)
              return
            }
          } else if (opcode === 0x8) {
            finish(audio.length > 0)
            return
          } else if (opcode === 0x9) {
            socket.write(clientFrame(0xa, payload))
          }
        }
      })
    })
    req.end()
  })
}
