/**
 * Check the Azure Speech credentials and which emotion styles the deployment accepts.
 *
 *   node tools/azure-check.mjs
 *
 * Prints one line per style and exits non-zero when the credentials are missing.
 * Nothing is written into the repository: files go to the temp directory.
 */
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { azureCredentials, synthesizeAzure } from './azure-tts.mjs'

const credentials = azureCredentials()
if (credentials === undefined) {
  console.error('缺少 Azure 凭据。')
  console.error('方式一：设置环境变量 AZURE_SPEECH_KEY / AZURE_SPEECH_REGION')
  console.error('方式二：写入 %TEMP%\\dsh-whale-pet\\azure.json  {"key":"...","region":"..."}')
  process.exit(2)
}

console.log(`region=${credentials.region} key=***${credentials.key.slice(-4)}`)
const dir = join(tmpdir(), 'dsh-whale-pet', 'azure-check')
const voice = 'zh-CN-XiaoxiaoNeural'
const STYLES = ['', 'cheerful', 'sad', 'angry', 'affectionate', 'gentle', 'calm', 'chat', 'serious', 'lyrical', 'fearful', 'excited', 'disgruntled', 'annoyed']

const supported = []
for (const style of STYLES) {
  const out = join(dir, `style-${style === '' ? 'plain' : style}.mp3`)
  const ok = await synthesizeAzure({ text: '主人，人家想让你听听这个语气～', out, voice, style, styleDegree: 1.4 })
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${style === '' ? 'plain' : style}`)
  if (ok) supported.push(style === '' ? 'plain' : style)
  await new Promise((resolve) => setTimeout(resolve, 500))
}

console.log(`supported: ${supported.join(', ')}`)
