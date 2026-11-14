// 把 data/chats/*.json 汇总成 data/messages.jsonl（auto_publish.py 需要的老格式）
// 用法: node build-jsonl.mjs <knowledgeDir>
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const OUT = process.argv[2]
if (!OUT) {
  console.error('用法: node build-jsonl.mjs <knowledgeDir>')
  process.exit(1)
}
const chats = join(OUT, 'data', 'chats')
if (!existsSync(chats)) {
  console.error('找不到 ' + chats)
  process.exit(1)
}

const SEARCH = new Set(['SEARCH', 'TOOL_SEARCH'])
const lines = []

// 旧格式里时间戳是 ISO 字符串（auto_publish 会直接切片取日期）
const iso = (value) => {
  if (typeof value === 'number' && value > 1000000) return new Date(value * 1000).toISOString()
  if (typeof value === 'string' && value) {
    const t = Date.parse(value)
    if (!Number.isNaN(t)) return new Date(t).toISOString()
  }
  return new Date().toISOString()
}

for (const file of readdirSync(chats)) {
  if (!file.endsWith('.json')) continue
  let biz
  try {
    biz = JSON.parse(readFileSync(join(chats, file), 'utf8'))?.data?.biz_data
  } catch {
    continue
  }
  const conv = biz?.chat_session || {}
  const msgs = biz?.chat_messages || []
  msgs.forEach((m, index) => {
    const out = { request: '', response: '', think: '', searches: [], files: [] }
    const req = []
    const res = []
    const think = []
    for (const frag of m.fragments || []) {
      const kind = frag?.type
      if (kind === 'REQUEST') req.push(frag.content || '')
      else if (kind === 'RESPONSE') res.push(frag.content || '')
      else if (kind === 'THINK') think.push(frag.content || '')
      else if (SEARCH.has(kind)) {
        for (const item of frag.results || []) {
          if (item && item.url) out.searches.push({ title: item.title || '', url: item.url })
        }
      } else if (kind === 'FILE') {
        for (const f of frag.files || []) {
          if (f) out.files.push({ name: f.file_name || '', bytes: f.file_size || 0 })
        }
      }
    }
    out.request = req.filter((t) => t.trim()).join('\n\n')
    out.response = res.filter((t) => t.trim()).join('\n\n')
    out.think = think.filter((t) => t.trim()).join('\n\n')
    lines.push(
      JSON.stringify({
        conv_id: conv.id,
        title: conv.title || '未命名',
        conv_created: iso(conv.inserted_at),
        conv_updated: iso(conv.updated_at),
        node_id: 'web-' + m.message_id,
        order: m.message_id,
        index,
        ts: iso(m.inserted_at),
        model: m.model || '',
        source: 'web-cdp',
        ...out,
        fragments: m.fragments || [],
      })
    )
  })
}

writeFileSync(join(OUT, 'data', 'messages.jsonl'), lines.join('\n') + '\n')
console.log(`messages.jsonl: ${lines.length} 条记录`)
