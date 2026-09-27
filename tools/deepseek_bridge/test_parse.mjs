/*
 * 离线回归测试：拿真实抓到的报文喂给用户脚本，检查解析和自动拉取。
 *
 *   node tools/deepseek_bridge/test_parse.mjs
 *
 * 数据来源：knowledge/deepseek/data/live_raw.jsonl
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SCRIPT = path.join(ROOT, 'knowledge/deepseek/bridge/deepseek-bridge.user.js');
const RAW = path.join(ROOT, 'knowledge/deepseek/data/live_raw.jsonl');

const source = fs.readFileSync(SCRIPT, 'utf8');
const rows = fs
  .readFileSync(RAW, 'utf8')
  .split('\n')
  .filter((line) => line.trim())
  .map((line) => JSON.parse(line));

const streamRow = rows.filter((r) => r.kind === 'stream').pop();
const historyRow = rows.filter((r) => (r.api || '').includes('history_messages')).pop();
const pageRow = rows.filter((r) => (r.api || '').includes('fetch_page')).pop();
if (!streamRow) {
  console.error('没找到流式报文，先让同步桥跑一次再来测');
  process.exit(1);
}

// ---------------------------------------------------------------- 环境桩

const ingests = [];
const pulls = [];
const pullHeaders = [];
let servedBody = streamRow.body;
let sessionsBody = pageRow ? pageRow.body : '{}';

function reply(opts, status, text) {
  if (opts.onload) setTimeout(() => opts.onload({ status, responseText: text }), 0);
}

globalThis.GM_xmlhttpRequest = (opts) => {
  const url = opts.url || '';
  if (url.endsWith('/ingest') || url.endsWith('/ingest_batch')) {
    const data = JSON.parse(opts.data);
    if (Array.isArray(data.messages)) {
      data.messages.forEach((m) => ingests.push({ node_id: m.node_id, fragments: m.fragments }));
    } else {
      ingests.push({ node_id: data.node_id, fragments: data.fragments });
    }
    return reply(opts, 200, '{}');
  }
  if (url.endsWith('/sessions')) {
    // 服务端告诉我们有两个会话需要拉取
    return reply(opts, 200, JSON.stringify({ ok: true, need: ['sess-a', 'sess-b'] }));
  }
  if (url.includes('history_messages')) {
    pulls.push(url);
    pullHeaders.push(opts.headers || {});
    return reply(opts, 200, historyRow ? historyRow.body : '{}');
  }
  return reply(opts, 200, '{}');
};

globalThis.unsafeWindow = globalThis;
globalThis.window = globalThis;
globalThis.location = {
  pathname: '/a/chat/s/00000000-0000-0000-0000-000000000000',
  href: 'https://chat.deepseek.com/a/chat/s/00000000',
};
globalThis.localStorage = {
  store: { userToken: JSON.stringify({ value: 'tok-abcdefghijklmnopqrstuvwxyz' }) },
  get length() {
    return Object.keys(this.store).length;
  },
  key(i) {
    return Object.keys(this.store)[i] ?? null;
  },
  getItem(k) {
    return this.store[k] ?? null;
  },
  setItem(k, v) {
    this.store[k] = String(v);
  },
};
globalThis.document = {
  readyState: 'complete',
  title: '你好 - DeepSeek',
  body: { appendChild() {} },
  addEventListener() {},
  createElement() {
    return { style: {}, addEventListener() {}, textContent: '', title: '' };
  },
};
globalThis.fetch = async () => ({
  clone: () => ({ text: async () => servedBody }),
});

vm.runInThisContext(source, { filename: SCRIPT });

// ---------------------------------------------- 场景一：流式回复解析

await globalThis.fetch('https://chat.deepseek.com/api/v0/chat/completion', {
  method: 'POST',
  // 故意不带认证头：验证脚本能从 localStorage 兜底取到令牌
  body: JSON.stringify({ prompt: '总结' }),
});
await new Promise((r) => setTimeout(r, 2600));

// ---------------------------------------------- 场景二：自动拉取历史

const pullsBefore = pulls.length;
servedBody = sessionsBody;
await globalThis.fetch('https://chat.deepseek.com/api/v0/chat_session/fetch_page', {
  method: 'GET',
});
await new Promise((r) => setTimeout(r, 4000));

// ------------------------------------------------------------------- 结果

const summary = new Map();
ingests.forEach((payload) => {
  payload.fragments.forEach((frag) => {
    const key = payload.node_id + ' ' + frag.type;
    const prev = summary.get(key) || { chars: 0, searches: 0 };
    prev.chars = Math.max(prev.chars, (frag.content || '').length);
    prev.searches = Math.max(prev.searches, (frag.results || []).length);
    summary.set(key, prev);
  });
});

console.log('解析出的消息：');
[...summary.entries()].sort().forEach(([key, value]) => {
  console.log(
    `  ${key}  正文 ${value.chars} 字` +
      (value.searches ? ` / 搜索 ${value.searches} 条` : '')
  );
});

console.log(`\n自动拉取触发了 ${pulls.length - pullsBefore} 次历史请求`);
pulls.slice(pullsBefore).forEach((url) => console.log('  ' + url));

const okAsk = ingests.some((p) => p.fragments.some((f) => f.content === '总结'));
const okPull = pulls.length - pullsBefore === 2;
const usedHeaders = pullHeaders[pullsBefore] || {};
const authKey = Object.keys(usedHeaders).find(
  (k) => k.toLowerCase() === 'authorization'
);
const auth = authKey ? String(usedHeaders[authKey]) : '';
console.log('\n结果：');
console.log(okAsk ? '  ✓ 流式回复解析正常' : '  ✗ 流式回复解析异常');
console.log(okPull ? '  ✓ 自动拉取按会话列表逐个执行' : '  ✗ 自动拉取没有按预期执行');
console.log(
  auth.indexOf('Bearer tok-') === 0
    ? '  ✓ 没有抓到请求头时，能从 localStorage 取到令牌'
    : `  ✗ 拉取请求没带上认证头（实际：${auth || '空'}）`
);

process.exit(okAsk && okPull && auth.indexOf('Bearer tok-') === 0 ? 0 : 1);
