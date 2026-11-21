/**
 * Regenerate every fixed voice line through MiniMax speech-2.8-hd.
 *
 * Requires the DashScope credentials (see minimax-tts.mjs). Run from the plugin
 * root:
 *
 *   node tools/regen-minimax.mjs [--dry-run]
 *
 * Billable: the table below is roughly 400 characters, about 0.14 CNY.
 */
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { hasMinimax, synthesizeMinimax } from './minimax-tts.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const OUT = join(HERE, '..', 'assets', 'voice')

/** Every fixed line: file, text, neutral emotion. */
const LINES = [
  ['welcome.mp3', '主人好～人家是鲸鱼娘！', 'happy'],
  ['running-1.mp3', '人家正在努力思考中…', 'calm'],
  ['running-2.mp3', '这个有点难，人家在想办法～', 'calm'],
  ['todo.mp3', '人家记着呢，任务还在进行中～', 'calm'],
  ['approval.mp3', '需要主人批准啦～', 'calm'],
  ['done-1.mp3', '任务完成啦！主人真棒！', 'happy'],
  ['done-2.mp3', '搞定收工！今晚加小鱼干嘛～', 'happy'],
  ['sad.mp3', '呜…刚才那步好像出错了…', 'sad'],
  ['chat-1.mp3', '好想吃小鱼干…啊不是，是投喂～', 'affectionate'],
  ['chat-2.mp3', '嗯哼～人家在呢！', 'happy'],
  ['talk-1.mp3', '主人有事就说嘛，人家听着呢～', 'affectionate'],
  ['talk-2.mp3', '嘿嘿，主人最好了！', 'happy'],
  ['talk-3.mp3', '人家可是很能干的，别小看我哦～', 'happy'],
  ['talk-4.mp3', '忙里偷闲一下下，就一下下嘛～', 'affectionate'],
  ['talk-5.mp3', '主人，今天也要开开心心的呀。', 'gentle'],
  ['pat-1.mp3', '呜哇～主人摸头，好舒服…', 'affectionate'],
  ['pat-2.mp3', '再摸就要收费了哦，一条小鱼干一次～', 'affectionate'],
  ['pat-3.mp3', '哼！摸太多次啦，人家要生气了！', 'angry'],
  ['feed-1.mp3', '哇！小鱼干！谢谢主人～', 'happy'],
  ['feed-2.mp3', '香！主人最懂人家的口味了～', 'happy'],
  ['meal-refuse.mp3', '还没到饭点呢…主人先忙，人家不饿～', 'calm'],
  ['meal-done.mp3', '这顿已经吃过啦，主人别把人家喂胖～', 'gentle'],
  ['tsundere-1.mp3', '这顿真的吃不下了啦…主人再喂，人家要生气了哦。', 'affectionate'],
  ['tsundere-2.mp3', '哼，人家都说吃过了，主人是不是想灌我？', 'angry'],
  ['angry-1.mp3', '喂！再喂就撑爆了！主人是大笨蛋！', 'angry'],
  ['angry-2.mp3', '哼！人家要生气啦！不理你三分钟！', 'angry'],
]

if (!hasMinimax()) {
  console.error('缺少 DashScope 凭据：设置 DASHSCOPE_API_KEY，或写入 %TEMP%\\dsh-whale-pet\\dashscope.json。')
  process.exit(2)
}

const dryRun = process.argv.includes('--dry-run')
let okCount = 0
let failed = 0
for (const [file, text, emotion] of LINES) {
  const out = join(OUT, file)
  if (dryRun) {
    console.log(`plan ${file} [${emotion}] ${text}`)
    continue
  }
  const ok = await synthesizeMinimax({ text, out, emotion })
  if (ok) {
    okCount += 1
    console.log(`ok   ${file} [${emotion}]`)
  } else {
    failed += 1
    console.error(`FAIL ${file}`)
  }
  await new Promise((resolve) => setTimeout(resolve, 1200))
}

console.log(`done: ok=${okCount} failed=${failed}`)
process.exit(failed === 0 ? 0 : 1)
