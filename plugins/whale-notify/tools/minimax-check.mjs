/**
 * Check the MiniMax credentials and every emotion, then report the billable size.
 *
 *   node tools/minimax-check.mjs
 *
 * Files land in the temp directory; nothing touches the repository.
 */
import { tmpdir } from 'node:os'
import { statSync } from 'node:fs'
import { join } from 'node:path'
import { minimaxCredentials, synthesizeMinimax } from './minimax-tts.mjs'

const credentials = minimaxCredentials()
if (credentials === undefined) {
  console.error('缺少 DashScope 凭据：设置 DASHSCOPE_API_KEY，')
  console.error('或写入 %TEMP%\\dsh-whale-pet\\dashscope.json  {"key":"sk-...","voice_id":"female-shaonv"}')
  process.exit(2)
}

console.log(`voice=${credentials.voiceId} key=***${credentials.key.slice(-4)}`)
const dir = join(tmpdir(), 'dsh-whale-pet', 'minimax-check')
const TEXT = '主人，人家今天超乖的，要不要摸摸头呀？'
for (const emotion of ['calm', 'happy', 'sad', 'angry', 'affectionate', 'gentle']) {
  const out = join(dir, `emotion-${emotion}.mp3`)
  const started = Date.now()
  const ok = await synthesizeMinimax({ text: TEXT, out, emotion })
  const size = ok ? statSync(out).size : 0
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${emotion.padEnd(13)} ${size} B  ${Date.now() - started}ms`)
  await new Promise((resolve) => setTimeout(resolve, 1200))
}
console.log(`billable per attempt: ${TEXT.length} characters`)
