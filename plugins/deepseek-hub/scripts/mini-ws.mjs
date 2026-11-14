// 最小 WebSocket 客户端 + CDP 客户端（无第三方依赖，走 net/crypto）
// 目的：Node 的全局 WebSocket 连不上 Chrome DevTools（握手后 1006），
// 这里自己实现 RFC6455 客户端帧，稳定可控。
import net from 'node:net'
import crypto from 'node:crypto'

export class MiniWS {
  constructor(url) {
    const u = new URL(url)
    this.host = u.hostname
    this.port = Number(u.port || 80)
    this.path = u.pathname + u.search
    this.handlers = { message: [], open: [], close: [], error: [] }
    this.buffer = Buffer.alloc(0)
    this.ready = new Promise((resolve, reject) => {
      this._resolveOpen = resolve
      this._rejectOpen = reject
    })
  }

  on(event, fn) {
    this.handlers[event]?.push(fn)
    return this
  }

  emit(event, arg) {
    for (const fn of this.handlers[event] || []) fn(arg)
  }

  connect() {
    const key = crypto.randomBytes(16).toString('base64')
    this.sock = net.connect(this.port, this.host, () => {
      const req =
        `GET ${this.path} HTTP/1.1\r\n` +
        `Host: ${this.host}:${this.port}\r\n` +
        'Upgrade: websocket\r\n' +
        'Connection: Upgrade\r\n' +
        `Sec-WebSocket-Key: ${key}\r\n` +
        'Sec-WebSocket-Version: 13\r\n\r\n'
      this.sock.write(req)
    })
    this.sock.on('error', (e) => {
      this.emit('error', e)
      this._rejectOpen?.(e)
    })
    this.sock.on('close', () => this.emit('close'))
    this.sock.on('data', (chunk) => this._onData(chunk))
    return this.ready
  }

  _onData(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk])
    if (!this.upgraded) {
      const idx = this.buffer.indexOf('\r\n\r\n')
      if (idx < 0) return
      const head = this.buffer.subarray(0, idx).toString('latin1')
      if (!/^HTTP\/1\.1 101/.test(head)) {
        this.emit('error', new Error('Upgrade 失败: ' + head.split('\r\n')[0]))
        this.sock.destroy()
        return
      }
      this.upgraded = true
      this.buffer = this.buffer.subarray(idx + 4)
      this._resolveOpen()
    }
    this._drain()
  }

  _drain() {
    while (this.buffer.length >= 2) {
      const b0 = this.buffer[0]
      const b1 = this.buffer[1]
      const fin = (b0 & 0x80) !== 0
      let len = b1 & 0x7f
      let offset = 2
      if (len === 126) {
        if (this.buffer.length < 4) return
        len = this.buffer.readUInt16BE(2)
        offset = 4
      } else if (len === 127) {
        if (this.buffer.length < 10) return
        len = Number(this.buffer.readBigUInt64BE(2))
        offset = 10
      }
      if (this.buffer.length < offset + len) return
      const payload = this.buffer.subarray(offset, offset + len)
      this.buffer = this.buffer.subarray(offset + len)
      const opcode = b0 & 0x0f
      if (process.env.WS_DEBUG && opcode !== 0x0) {
        console.log(`  <frame op=${opcode} len=${len} fin=${fin} mask=${(b1 & 0x80) !== 0}>`)
      }
      if (opcode === 0x8) {
        const code = payload.length >= 2 ? payload.readUInt16BE(0) : 0
        const reason = payload.length > 2 ? payload.subarray(2).toString('utf8') : ''
        if (process.env.WS_DEBUG) console.log(`  <close ${code} ${reason}>`)
        this.sock.end()
        this.emit('close')
        return
      }
      if (opcode === 0x9) {
        this._sendFrame(payload, 0xa)
        continue
      }
      if (opcode === 0xa) continue

      // 处理分片：0x1/0x2 开始，0x0 续帧，FIN 结束
      if (opcode !== 0x0) {
        this.fragments = [payload]
        this.fragOpcode = opcode
      } else {
        this.fragments.push(payload)
      }
      if (!fin) continue
      const whole = Buffer.concat(this.fragments)
      this.fragments = []
      if (this.fragOpcode === 0x1 || this.fragOpcode === 0x0) {
        this.emit('message', whole.toString('utf8'))
      }
    }
  }

  _sendFrame(payload, opcode = 0x1) {
    if (!this.sock || this.sock.destroyed) return
    const data = Buffer.isBuffer(payload) ? payload : Buffer.from(payload, 'utf8')
    const mask = crypto.randomBytes(4)
    let header
    if (data.length < 126) {
      header = Buffer.from([0x80 | opcode, 0x80 | data.length])
    } else if (data.length < 65536) {
      header = Buffer.alloc(4)
      header[0] = 0x80 | opcode
      header[1] = 0x80 | 126
      header.writeUInt16BE(data.length, 2)
    } else {
      header = Buffer.alloc(10)
      header[0] = 0x80 | opcode
      header[1] = 0x80 | 127
      header.writeBigUInt64BE(BigInt(data.length), 2)
    }
    const masked = Buffer.alloc(data.length)
    for (let i = 0; i < data.length; i++) masked[i] = data[i] ^ mask[i % 4]
    this.sock.write(Buffer.concat([header, mask, masked]))
  }

  send(text) {
    this._sendFrame(text, 0x1)
  }

  close() {
    try {
      this.sock?.end()
    } catch {
      /* ignore */
    }
  }
}

// 极简 CDP 客户端：按 id 匹配响应，支持事件订阅
export class CDP {
  constructor(wsUrl) {
    this.ws = new MiniWS(wsUrl)
    this.nextId = 1
    this.pending = new Map()
    this.listeners = new Set()
    this.ws.on('message', (text) => {
      let msg
      try {
        msg = JSON.parse(text)
      } catch {
        return
      }
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id)
        this.pending.delete(msg.id)
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result)
      } else if (msg.method) {
        for (const fn of this.listeners) fn(msg)
      }
    })
  }

  async open() {
    await this.ws.connect()
    return this
  }

  send(method, params = {}, sessionId) {
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      const msg = { id, method, params }
      if (sessionId) msg.sessionId = sessionId
      this.ws.send(JSON.stringify(msg))
    })
  }

  onEvent(fn) {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  close() {
    this.ws.close()
  }
}
