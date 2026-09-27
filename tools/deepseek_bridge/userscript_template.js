// ==UserScript==
// @name         DeepSeek 本地同步桥
// @namespace    local.deepseek.bridge
// @version      0.7.0
// @description  把 DeepSeek 网页版的新对话实时写入本机知识库
// @match        https://chat.deepseek.com/*
// @run-at       document-start
// @updateURL    http://127.0.0.1:__PORT__/install/deepseek-bridge.user.js
// @downloadURL  http://127.0.0.1:__PORT__/install/deepseek-bridge.user.js
// @grant        unsafeWindow
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// ==/UserScript==

/*
 * 工作方式：监听页面自己发出的网络请求，把已经收到的内容抄送给本机服务。
 * 登录凭证不出浏览器，脚本只读取页面已经拿到的数据。
 *
 * 实测到的接口（2026-09）：
 *   GET  /api/v0/chat_session/fetch_page   会话列表（标题）
 *   GET  /api/v0/chat/history_messages     某个会话的完整历史
 *   POST /api/v0/chat_session/create       新建会话
 *   POST /api/v0/chat/completion           流式回复（SSE，三种事件混着发）
 *
 * 流式事件有三种形态，缺一不可：
 *   1. {"v": {"response": {...}}}                  整条消息（含已有片段）
 *   2. {"v": "文字"}                               往最后一个片段追加文字
 *   3. {"p": "response/fragments/...", "v": ...}   JSON 补丁，含 APPEND/BATCH
 *
 * 自动拉取：页面加载时会顺带把本地缺失或过期的会话历史补齐（6 小时一次），
 * 点击右下角标签可以强制重新拉取全部会话。
 */

(function () {
  'use strict';

  const PORT = __PORT__;
  const TOKEN = '__TOKEN__';
  const BASE = 'http://127.0.0.1:' + PORT;

  const API_RE = /\/api\/v\d+\/chat/i;
  const FLUSH_DELAY = 1200;
  const RAW_LIMIT = 200000;
  const PULL_COOLDOWN_MS = 6 * 60 * 60 * 1000;
  const KEEP = new Set([
    'REQUEST',
    'RESPONSE',
    'THINK',
    'SEARCH',
    'TOOL_SEARCH',
    'FILE',
  ]);

  const W = (typeof unsafeWindow !== 'undefined' && unsafeWindow) || window;

  // ---------------------------------------------------------------- 状态提示

  let badge = null;
  let statusTimer = null;

  function setStatus(text, ok) {
    if (!badge) return;
    badge.textContent = '同步桥 ' + text;
    badge.style.background = ok ? 'rgba(22,131,60,.92)' : 'rgba(150,40,40,.92)';
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => {
      if (badge) badge.style.opacity = '0.35';
    }, 4000);
  }

  function mountBadge() {
    if (badge || !document.body) return;
    badge = document.createElement('div');
    badge.textContent = '同步桥 待命';
    badge.style.cssText = [
      'position:fixed',
      'right:12px',
      'bottom:12px',
      'z-index:2147483647',
      'padding:4px 10px',
      'border-radius:12px',
      'font:12px/1.6 system-ui,sans-serif',
      'color:#fff',
      'background:rgba(60,60,60,.85)',
      'opacity:.35',
      'pointer-events:auto',
      'cursor:pointer',
      'transition:opacity .3s',
    ].join(';');
    badge.title = '点击重新拉取全部会话';
    badge.addEventListener('click', () => forcePull());
    document.body.appendChild(badge);
  }

  function ping() {
    GM_xmlhttpRequest({
      method: 'GET',
      url: BASE + '/ping',
      timeout: 3000,
      onload: (r) => setStatus(r.status === 200 ? '已连接' : '异常', r.status === 200),
      onerror: () => setStatus('未启动', false),
    });
  }

  // ---------------------------------------------------------------- 发送数据

  function send(path, payload, onDone) {
    const body = Object.assign(
      { token: TOKEN, url: location.href, page_title: document.title },
      payload
    );
    try {
      GM_xmlhttpRequest({
        method: 'POST',
        url: BASE + path,
        headers: { 'Content-Type': 'application/json', 'X-Bridge-Token': TOKEN },
        data: JSON.stringify(body),
        timeout: 8000,
        onload: (r) => {
          if (r.status === 200) {
            setStatus('已连接', true);
            if (onDone) {
              try {
                onDone(r.responseText);
              } catch (e) {
                /* 回调出错不影响页面 */
              }
            }
          }
          else if (r.status === 403) setStatus('令牌错误', false);
          else setStatus('服务异常', false);
        },
        onerror: () => setStatus('未启动', false),
      });
    } catch (e) {
      setStatus('发送失败', false);
    }
  }

  function sendRaw(kind, api, body) {
    send('/raw', {
      kind: kind,
      api: api,
      body: typeof body === 'string' ? body.slice(0, RAW_LIMIT) : body,
    });
  }

  // ------------------------------------------------------------------ 工具

  /* 接口里的时间戳有两种：unix 秒（浮点）和 ISO 字符串 */
  function iso(value) {
    if (typeof value === 'number' && value > 1000000) {
      return new Date(value * 1000).toISOString();
    }
    if (typeof value === 'string' && value) {
      const t = new Date(value);
      if (!isNaN(t.getTime())) return t.toISOString();
    }
    return new Date().toISOString();
  }

  function cloneFragment(frag) {
    const item = { type: frag.type };
    if (frag.id !== undefined) item.id = frag.id;
    if (typeof frag.content === 'string') item.content = frag.content;
    if (Array.isArray(frag.results)) item.results = frag.results.slice();
    if (Array.isArray(frag.files)) item.files = frag.files.slice();
    return item;
  }

  function sessionIdFromUrl() {
    const m = location.pathname.match(/\/s\/([0-9a-fA-F-]{8,})/);
    return m ? m[1] : null;
  }

  let lastSessionId = null;
  function currentSessionId() {
    return sessionIdFromUrl() || lastSessionId || 'pending';
  }

  const titles = new Map(); // convId -> 标题
  const states = new Map(); // convId|msgId -> 消息状态
  let pendingPrompt = null; // 请求体里抓到的用户输入，等流式响应告诉我们是哪条消息
  let currentMsgId = null; // 当前正在流式输出的是哪条助手消息
  let lastSessionsSig = ''; // 会话列表签名，置顶有变化才上报
  let lastSessions = []; // 最近一次会话列表，用于手动全量拉取
  let authHeaders = null; // 从页面请求里学到的认证头，用于自己发拉取请求
  let pulling = false;
  let lastPullAt = 0; // 内存里的冷却时间，localStorage 不可用时兜底
  let flushTimer = null;

  /* 偷学页面自己的认证头：只记住和鉴权有关的字段，值不出浏览器 */
  function learnHeaders(raw) {
    if (!raw) return;
    let entries = [];
    try {
      if (typeof Headers !== 'undefined' && raw instanceof Headers) {
        entries = Array.from(raw.entries());
      } else if (Array.isArray(raw)) {
        entries = raw;
      } else if (typeof raw === 'object') {
        entries = Object.entries(raw);
      }
    } catch (e) {
      return;
    }
    const picked = {};
    entries.forEach((pair) => {
      const key = pair && pair[0] ? String(pair[0]) : '';
      if (!key) return;
      const lower = key.toLowerCase();
      if (
        lower === 'authorization' ||
        lower.indexOf('token') >= 0 ||
        lower.indexOf('x-ds') === 0 ||
        lower.indexOf('x-client') === 0 ||
        lower.indexOf('cookie') === 0
      ) {
        picked[key] = pair[1];
      }
    });
    if (Object.keys(picked).length) authHeaders = picked;
  }

  /* 页面把令牌存在 localStorage 里（形如 {"value":"..."}）。
     抓不到请求头时，就用它自己拼一个。 */
  function tokenFromStorage() {
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (!key || !/token/i.test(key)) continue;
        let value = localStorage.getItem(key);
        if (!value) continue;
        try {
          const parsed = JSON.parse(value);
          if (parsed && typeof parsed === 'object' && parsed.value) value = parsed.value;
        } catch (e) {
          /* 不是 JSON 就直接用原值 */
        }
        if (typeof value === 'string' && value.length > 20) return value;
      }
    } catch (e) {
      /* 读不到就算了 */
    }
    return null;
  }

  function resolveAuth() {
    if (authHeaders && Object.keys(authHeaders).length) return authHeaders;
    const token = tokenFromStorage();
    if (token) {
      authHeaders = { Authorization: 'Bearer ' + token };
      sendRaw('headers', '', 'localStorage:' + Object.keys(authHeaders).join(','));
    }
    return authHeaders || {};
  }

  // ------------------------------------------------------------ 自动拉取历史

  function pullSessions(ids) {
    if (pulling || !ids || !ids.length) return;
    pulling = true;
    const queue = ids.slice();
    const total = queue.length;
    let done = 0;
    setStatus('拉取 0/' + total, true);
    const next = () => {
      if (!queue.length) {
        pulling = false;
        setStatus('已连接', true);
        return;
      }
      const id = queue.shift();
      const url =
        'https://chat.deepseek.com/api/v0/chat/history_messages?chat_session_id=' +
        encodeURIComponent(id);
      const headers = Object.assign({ Accept: 'application/json' }, resolveAuth());
      try {
        GM_xmlhttpRequest({
          method: 'GET',
          url: url,
          headers: headers,
          timeout: 20000,
          onload: (r) => {
            try {
              if (r.status === 200) {
                handleBody(url, r.responseText);
                const data = JSON.parse(r.responseText);
                if (data && data.code && data.code !== 0) {
                  sendRaw('pull', url, 'code=' + data.code + ' ' + (data.msg || ''));
                }
              } else {
                sendRaw('pull', url, 'http=' + r.status);
              }
            } catch (e) {
              /* 单条失败不影响后续 */
            }
            done += 1;
            setStatus('拉取 ' + done + '/' + total, true);
            setTimeout(next, 1200);
          },
          onerror: () => setTimeout(next, 1500),
        });
      } catch (e) {
        pulling = false;
      }
    };
    next();
  }

  function maybeAutoPull(ids) {
    if (!ids || !ids.length) return;
    let last = 0;
    try {
      last = parseInt(localStorage.getItem('dsBridgeLastPull') || '0', 10) || 0;
    } catch (e) {
      last = 0;
    }
    last = Math.max(last, lastPullAt);
    if (Date.now() - last < PULL_COOLDOWN_MS) return;
    lastPullAt = Date.now();
    try {
      localStorage.setItem('dsBridgeLastPull', String(Date.now()));
    } catch (e) {
      /* 存不了就算了 */
    }
    pullSessions(ids);
  }

  function forcePull() {
    if (!lastSessions.length) {
      setStatus('还没有会话列表', false);
      return;
    }
    setStatus('准备全量拉取', true);
    send('/sessions', { sessions: lastSessions, force: true }, (text) => {
      try {
        const data = JSON.parse(text);
        pullSessions(data.need || []);
      } catch (e) {
        setStatus('拉取失败', false);
      }
    });
  }

  function stateFor(convId, msgId) {
    const key = convId + '|' + msgId;
    if (!states.has(key)) {
      states.set(key, {
        convId: convId,
        msgId: msgId,
        ts: null,
        order: null,
        frags: [],
        sent: null,
      });
    }
    return states.get(key);
  }

  function setMessage(state, resp) {
    if (Array.isArray(resp.fragments)) {
      state.frags = resp.fragments.map(cloneFragment);
    }
    if (resp.inserted_at) state.ts = iso(resp.inserted_at);
    if (resp.message_id !== undefined) state.order = resp.message_id;
  }

  function pushFragments(state, list) {
    (Array.isArray(list) ? list : [list]).forEach((frag) => {
      if (!frag || !frag.type) return;
      const at = state.frags.findIndex(
        (item) => frag.id !== undefined && item.id === frag.id
      );
      if (at >= 0) state.frags[at] = cloneFragment(frag);
      else state.frags.push(cloneFragment(frag));
    });
  }

  function appendToLast(state, text) {
    if (!text) return;
    if (!state.frags.length) {
      state.frags.push({ type: 'RESPONSE', content: text });
      return;
    }
    const frag = state.frags[state.frags.length - 1];
    frag.content = (frag.content || '') + text;
  }

  /* JSON 补丁：response/fragments/-1/content 表示最后一个片段的正文 */
  function applyPatch(state, path, op, value) {
    if (op === 'BATCH') {
      (Array.isArray(value) ? value : []).forEach((sub) => {
        if (sub && sub.p) applyPatch(state, String(sub.p), sub.o || 'APPEND', sub.v);
      });
      return;
    }
    if (path === 'response/fragments' && op === 'APPEND') {
      pushFragments(state, value);
      return;
    }
    const m = path.match(/^response\/fragments\/(\d+|-1)\/(.+)$/);
    if (!m) return;
    const index = m[1] === '-1' ? state.frags.length - 1 : parseInt(m[1], 10);
    const frag = state.frags[index];
    if (!frag) return;
    const field = m[2];
    if (field === 'content') {
      frag.content = op === 'SET' ? String(value) : (frag.content || '') + String(value);
    } else if (field === 'results' || field === 'files') {
      const incoming = Array.isArray(value) ? value : [];
      frag[field] = op === 'APPEND' ? (frag[field] || []).concat(incoming) : incoming;
    } else {
      frag[field] = value;
    }
  }

  // ------------------------------------------------------ 接口一：完整历史

  function onHistory(bizData) {
    const sess = bizData.chat_session;
    const list = bizData.chat_messages;
    if (!sess || !sess.id || !Array.isArray(list)) return false;
    lastSessionId = sess.id;
    if (sess.title) titles.set(sess.id, sess.title);
    const created = iso(sess.inserted_at);
    const messages = [];
    list.forEach((msg) => {
      if (!msg || msg.message_id === undefined) return;
      const fragments = (msg.fragments || [])
        .filter((f) => f && KEEP.has(f.type))
        .map(cloneFragment);
      if (!fragments.length) return;
      messages.push({
        node_id: 'live-' + msg.message_id,
        order: msg.message_id,
        ts: iso(msg.inserted_at),
        model: msg.model || '',
        fragments: fragments,
      });
    });
    if (!messages.length) return false;
    // 整段历史一次发过去，服务端只写一次盘
    send('/ingest_batch', {
      conv_id: sess.id,
      title: sess.title || titles.get(sess.id) || '未命名会话',
      conv_created: created,
      messages: messages,
    });
    return true;
  }

  // -------------------------------------------------- 接口二：会话与标题

  function onSessionList(bizData) {
    const list = bizData.chat_sessions;
    if (!Array.isArray(list)) return false;
    const payload = [];
    list.forEach((s) => {
      if (!s || !s.id) return;
      if (s.title) titles.set(s.id, s.title);
      payload.push({
        id: s.id,
        title: s.title || '',
        pinned: !!s.pinned,
        updated_at: s.updated_at || null,
      });
    });
    if (!payload.length) return false;
    // 置顶或标题变化才上报，避免每次翻页都发一遍
    const sig = payload.map((s) => s.id + '|' + (s.pinned ? 1 : 0) + '|' + s.title).join(',');
    if (sig !== lastSessionsSig) {
      lastSessionsSig = sig;
      lastSessions = payload;
      send('/sessions', { sessions: payload }, (text) => {
        try {
          maybeAutoPull((JSON.parse(text) || {}).need || []);
        } catch (e) {
          /* 返回体异常就跳过自动拉取 */
        }
      });
    }
    return true;
  }

  function onCreate(bizData) {
    const sess = bizData.chat_session;
    if (!sess || !sess.id) return false;
    lastSessionId = sess.id;
    if (sess.title) titles.set(sess.id, sess.title);
    return true;
  }

  // -------------------------------------------------- 接口三：流式回复 SSE

  function onStreamEvent(ev) {
    if (!ev || typeof ev !== 'object') return false;
    const convId = currentSessionId();

    // 开场事件：告诉我们这条问答的两条消息编号
    if (ev.response_message_id !== undefined) {
      currentMsgId = String(ev.response_message_id);
      const state = stateFor(convId, currentMsgId);
      state.order = ev.response_message_id;
      if (ev.request_message_id !== undefined && pendingPrompt) {
        const ask = stateFor(convId, String(ev.request_message_id));
        ask.order = ev.request_message_id;
        ask.ts = pendingPrompt.ts;
        ask.frags = [{ type: 'REQUEST', content: pendingPrompt.text }];
        ask.sent = null;
        pendingPrompt = null;
      }
      scheduleFlush();
      return true;
    }

    // 形态一：整条消息
    const resp = ev.v && ev.v.response;
    if (resp && typeof resp === 'object') {
      const id = resp.message_id !== undefined ? String(resp.message_id) : currentMsgId;
      if (!id) return false;
      currentMsgId = id;
      const state = stateFor(convId, id);
      setMessage(state, resp);
      scheduleFlush();
      return true;
    }

    // 形态二：裸的文字增量
    if (typeof ev.v === 'string') {
      if (!currentMsgId) return false;
      appendToLast(stateFor(convId, currentMsgId), ev.v);
      scheduleFlush();
      return true;
    }

    // 形态三：JSON 补丁
    if (typeof ev.p === 'string') {
      const target =
        ev.p.indexOf('response/fragments') === 0 && currentMsgId
          ? stateFor(convId, currentMsgId)
          : null;
      if (!target) return false;
      applyPatch(target, ev.p, ev.o || 'APPEND', ev.v);
      scheduleFlush();
      return true;
    }
    return false;
  }

  /* 请求体里带着用户刚发的话，流式响应本身不含这段文字 */
  function onRequestBody(bodyText) {
    if (!bodyText || typeof bodyText !== 'string') return;
    let data;
    try {
      data = JSON.parse(bodyText);
    } catch (e) {
      return;
    }
    let prompt = '';
    if (typeof data.prompt === 'string') prompt = data.prompt;
    else if (Array.isArray(data.messages)) {
      for (let i = data.messages.length - 1; i >= 0; i--) {
        const item = data.messages[i];
        if (item && item.role === 'user' && typeof item.content === 'string') {
          prompt = item.content;
          break;
        }
      }
    }
    if (!prompt.trim()) return;
    pendingPrompt = { text: prompt, ts: new Date().toISOString() };
    currentMsgId = null;
  }

  // ------------------------------------------------------------------ 落盘

  function scheduleFlush() {
    clearTimeout(flushTimer);
    flushTimer = setTimeout(flush, FLUSH_DELAY);
  }

  function flush() {
    states.forEach((state) => {
      const fragments = state.frags
        .filter((f) => f && KEEP.has(f.type))
        .filter((f) => f.content || (f.results && f.results.length) || (f.files && f.files.length))
        .map((f) => {
          const item = { type: f.type };
          if (typeof f.content === 'string' && f.content) item.content = f.content;
          if (Array.isArray(f.results)) {
            item.results = f.results
              .map((r) => ({ title: (r && r.title) || '', url: (r && r.url) || '' }))
              .filter((r) => r.url);
          }
          if (Array.isArray(f.files)) {
            item.files = f.files.map((x) => ({
              name: (x && (x.file_name || x.name)) || '',
              bytes: (x && (x.file_size || x.size)) || 0,
            }));
          }
          return item;
        });
      if (!fragments.length) return;
      const serial = JSON.stringify(fragments);
      if (state.sent === serial) return;
      send('/ingest', {
        conv_id: state.convId,
        title:
          titles.get(state.convId) ||
          document.title.replace(/ ?[-|] ?DeepSeek.*$/, '') ||
          '未命名会话',
        node_id: 'live-' + state.msgId,
        order: state.order,
        ts: state.ts || new Date().toISOString(),
        fragments: fragments,
      });
      state.sent = serial;
    });
  }

  // ------------------------------------------------------------ 解析响应体

  function parseEvents(text) {
    const trimmed = text.trim();
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      try {
        const one = JSON.parse(trimmed);
        return Array.isArray(one) ? one : [one];
      } catch (e) {
        /* 落到按行解析 */
      }
    }
    const out = [];
    text.split(/\r?\n/).forEach((line) => {
      const payload = line.replace(/^\s*(data|event):\s*/, '').trim();
      if (!payload || payload === '[DONE]') return;
      if (payload[0] !== '{' && payload[0] !== '[') return;
      try {
        out.push(JSON.parse(payload));
      } catch (e) {
        /* 半截的流式片段，忽略 */
      }
    });
    return out;
  }

  function handleBody(url, text) {
    if (!text || typeof text !== 'string') return;
    const isStream = text.indexOf('data:') === 0 || text.indexOf('\ndata:') > -1;
    sendRaw(isStream ? 'stream' : 'json', url, text);
    let handled = false;
    parseEvents(text).forEach((ev) => {
      if (!ev || typeof ev !== 'object') return;
      if (onStreamEvent(ev)) handled = true;
      const biz = ev.data && ev.data.biz_data;
      if (!biz) return;
      if (onHistory(biz) || onSessionList(biz) || onCreate(biz)) handled = true;
    });
    if (handled) scheduleFlush();
  }

  function interesting(url) {
    return typeof url === 'string' && API_RE.test(url);
  }

  // -------------------------------------------------------------- 挂上钩子

  if (typeof W.fetch === 'function') {
    const originalFetch = W.fetch;
    W.fetch = function (input, init) {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      const promise = originalFetch.apply(this, arguments);
      try {
        if (interesting(url)) {
          // 页面可能用 fetch(url, {headers}) 也可能用 new Request(url, {headers})
          learnHeaders((init && init.headers) || (input && input.headers));
          if (init && typeof init.body === 'string') {
            sendRaw('req', url, init.body);
            onRequestBody(init.body);
          }
          promise
            .then((res) => {
              try {
                res
                  .clone()
                  .text()
                  .then((t) => handleBody(url, t))
                  .catch(() => {});
              } catch (e) {
                /* 响应体不可读就算了 */
              }
            })
            .catch(() => {});
        }
      } catch (e) {
        /* 绝不影响页面本身 */
      }
      return promise;
    };
  }

  if (W.XMLHttpRequest && W.XMLHttpRequest.prototype) {
    const proto = W.XMLHttpRequest.prototype;
    const originalOpen = proto.open;
    const originalSend = proto.send;
    proto.open = function (method, url) {
      this.__bridgeUrl = url;
      return originalOpen.apply(this, arguments);
    };
    const originalSetHeader = proto.setRequestHeader;
    proto.setRequestHeader = function (name, value) {
      try {
        learnHeaders({ [name]: value });
      } catch (e) {
        /* 忽略 */
      }
      return originalSetHeader.apply(this, arguments);
    };
    proto.send = function (body) {
      try {
        if (interesting(this.__bridgeUrl)) {
          if (typeof body === 'string') {
            sendRaw('req', this.__bridgeUrl, body);
            onRequestBody(body);
          }
          this.addEventListener('load', () => {
            try {
              handleBody(this.__bridgeUrl, this.responseText);
            } catch (e) {
              /* 忽略 */
            }
          });
        }
      } catch (e) {
        /* 忽略 */
      }
      return originalSend.apply(this, arguments);
    };
  }

  // -------------------------------------------------------------------- 启动

  function boot() {
    mountBadge();
    ping();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
  setInterval(ping, 60000);
})();
