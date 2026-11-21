/**
 * Regenerate every fixed voice line through Azure Speech with real emotions.
 *
 * Requires `AZURE_SPEECH_KEY` / `AZURE_SPEECH_REGION` (or the azure.json config).
 * Run from the plugin root:
 *
 *   node tools/regen-azure.mjs [--dry-run]
 *
 * Lines whose style is rejected fall back to the same voice without a style, so
 * the pack always ends up complete.
 */
import { existsSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { hasAzure, synthesizeAzure } from './azure-tts.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const OUT = join(HERE, '..', 'assets', 'voice')
const VOICE = 'zh-CN-XiaoxiaoNeural'

/** Every fixed line: file, text, emotion style, rate, pitch. */
const LINES = [
  ['welcome.mp3', '主人好～人家是鲸鱼娘！', 'cheerful', '-4%', '+6Hz'],
  ['running-1.mp3', '人家正在努力思考中…', 'chat', '-6%', '+4Hz'],
  ['running-2.mp3', '这个有点难，人家在想办法～', 'chat', '-6%', '+4Hz'],
  ['todo.mp3', '人家记着呢，任务还在进行中～', 'chat', '-6%', '+4Hz'],
  ['approval.mp3', '需要主人批准啦～', 'calm', '-4%', '+6Hz'],
  ['done-1.mp3', '任务完成啦！主人真棒！', 'cheerful', '-2%', '+8Hz'],
  ['done-2.mp3', '搞定收工！今晚加小鱼干嘛～', 'cheerful', '-2%', '+8Hz'],
  ['sad.mp3', '呜…刚才那步好像出错了…', 'sad', '-8%', '+2Hz'],
  ['chat-1.mp3', '好想吃小鱼干…啊不是，是投喂～', 'affectionate', '-4%', '+6Hz'],
  ['chat-2.mp3', '嗯哼～人家在呢！', 'cheerful', '0%', '+8Hz'],
  ['talk-1.mp3', '主人有事就说嘛，人家听着呢～', 'affectionate', '-4%', '+6Hz'],
  ['talk-2.mp3', '嘿嘿，主人最好了！', 'cheerful', '0%', '+8Hz'],
  ['talk-3.mp3', '人家可是很能干的，别小看我哦～', 'cheerful', '-2%', '+6Hz'],
  ['talk-4.mp3', '忙里偷闲一下下，就一下下嘛～', 'chat', '-6%', '+4Hz'],
  ['talk-5.mp3', '主人，今天也要开开心心的呀。', 'gentle', '-8%', '+2Hz'],
  ['pat-1.mp3', '呜哇～主人摸头，好舒服…', 'affectionate', '-8%', '+4Hz'],
  ['pat-2.mp3', '再摸就要收费了哦，一条小鱼干一次～', 'affectionate', '-4%', '+6Hz'],
  ['pat-3.mp3', '哼！摸太多次啦，人家要生气了！', 'angry', '-2%', '+8Hz'],
  ['feed-1.mp3', '哇！小鱼干！谢谢主人～', 'cheerful', '0%', '+8Hz'],
  ['feed-2.mp3', '香！主人最懂人家的口味了～', 'cheerful', '-4%', '+6Hz'],
  ['meal-refuse.mp3', '还没到饭点呢…主人先忙，人家不饿～', 'calm', '-4%', '+4Hz'],
  ['meal-done.mp3', '这顿已经吃过啦，主人别把人家喂胖～', 'gentle', '-2%', '+4Hz'],
  ['tsundere-1.mp3', '这顿真的吃不下了啦…主人再喂，人家要生气了哦。', 'affectionate', '-2%', '+6Hz'],
  ['tsundere-2.mp3', '哼，人家都说吃过了，主人是不是想灌我？', 'angry', '-2%', '+8Hz'],
  ['angry-1.mp3', '喂！再喂就撑爆了！主人是大笨蛋！', 'angry', '0%', '+10Hz'],
  ['angry-2.mp3', '哼！人家要生气啦！不理你三分钟！', 'angry', '2%', '+10Hz'],
]

const dryRun = process.argv.includes('--dry-run')

if (!hasAzure()) {
  console.error('缺少 Azure 凭据：请设置 AZURE_SPEECH_KEY / AZURE_SPEECH_REGION，')
  console.error('或写入 %TEMP%\\dsh-whale-pet\\azure.json（{"key":"...","region":"..."}）。')
  process.exit(2)
}

let styled = 0
let plain = 0
let failed = 0
for (const [file, text, style, rate, pitch] of LINES) {
  const out = join(OUT, file)
  if (existsSync(out) && statSync(out).size > 1000 && process.argv.includes('--skip-existing')) {
    console.log(`skip ${file}`)
    continue
  }
  if (dryRun) {
    console.log(`plan ${file} [${style}] ${text}`)
    continue
  }
  const ok = await synthesizeAzure({ text, out, voice: VOICE, style, rate, pitch })
  if (ok) {
    styled += 1
    console.log(`styled ${file} [${style}]`)
    continue
  }
  const fallback = await synthesizeAzure({ text, out, voice: VOICE, rate, pitch })
  if (fallback) {
    plain += 1
    console.log(`plain  ${file} (style ${style} rejected)`)
  } else {
    failed += 1
    console.error(`FAILED ${file}`)
  }
  await new Promise((resolve) => setTimeout(resolve, 700))
}

console.log(`done: styled=${styled} plain=${plain} failed=${failed}`)
process.exit(failed === 0 ? 0 : 1)
