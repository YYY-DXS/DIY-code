/**
 * Sec-MS-GEC v2 signing for the Edge read-aloud endpoint.
 *
 * The service signs each handshake with a five-minute token: a custom CS64 digest
 * plus a deliberately modified SHA-256. Both algorithms are a faithful port of
 * `edge_tts/drm.py` from rany2/edge-tts, which is the reference implementation the
 * community reverse-engineered (see that project's issue #290).
 */

const MASK = 0xffffffff
const rol16 = (value) => ((value << 16) | (value >>> 16)) >>> 0
const mul = (a, b) => (Math.imul(a, b) >>> 0)
const add = (a, b) => ((a + b) >>> 0)
const addAll = (...values) => {
  let total = 0
  for (const value of values) total = (total + value) >>> 0
  return total
}

const INITIAL = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]
const SEED_STATE = [0xfd9fbea2, 0x91243ce7, 0xbe499094, 0xcd2e1e0a, 0x6c006f49, 0x04bd35ab, 0xfeb0a7e4, 0x03effbd2]
const SCHEDULE = [
  0xeb24bf9e, 0x1558691f, 0xa0c09ee2, 0x0cfa32ba, 0xa622ee8c, 0xd1dd9491, 0xc0dd25a0,
  0xf9e70ab6, 0xf0c31573, 0x7058ce4e, 0x7188e606, 0x00e5ab33, 0xd258b060, 0x72766564,
]
const ROUND = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]
const ADJUSTMENT = 0xc9dc06a7
const BLOCK_ROUND = [...ROUND.slice(0, 14), ADJUSTMENT, ...ROUND.slice(15)]
const SIGMA0_ADJUSTMENT = 0x059c0b80
const SIGMA1_ADJUSTMENT = 0x000b92c0

const rotRight = (value, bits) => ((value >>> bits) | (value << (32 - bits))) >>> 0

/** SHA-256 small sigma zero, matching the modified digest. */
const sigma0 = (value) => (((value >>> 7) ^ (value << 25) ^ (value >>> 18) ^ (value << 14) ^ (value >>> 3)) >>> 0)
/** SHA-256 small sigma one, matching the modified digest. */
const sigma1 = (value) => (((value >>> 17) ^ (value << 15) ^ (value >>> 19) ^ (value << 13) ^ (value >>> 10)) >>> 0)

/** Little-endian 32-bit words of `\x00 + data`, zero padded to an even count. */
export function wordsLe4Even(data) {
  const padded = Buffer.concat([Buffer.from([0]), data])
  const pad = (4 - (padded.length % 4)) % 4
  const buffer = Buffer.concat([padded, Buffer.alloc(pad)])
  const words = []
  for (let offset = 0; offset < buffer.length; offset += 4) words.push(buffer.readUInt32LE(offset))
  if (words.length % 2 === 1) words.push(0)
  return words
}

/** Expand the message schedule from `firstWord` to 64 words. */
function expandSchedule(words, firstWord) {
  for (let index = firstWord; index < 64; index += 1) {
    const x = words[index - 2]
    const y = words[index - 15]
    words.push(addAll(sigma1(x), words[index - 7], sigma0(y), words[index - 16]))
  }
}

/** Run the compression function over `words`, optionally resuming mid-block. */
function compress(state, words, firstRound = 0) {
  let [a, b, c, d, e, f, g, h] = state
  const constants = firstRound === 14 ? BLOCK_ROUND : ROUND
  for (let index = firstRound; index < 64; index += 1) {
    const s1 = (rotRight(e, 6) ^ rotRight(e, 11) ^ rotRight(e, 25)) >>> 0
    const ch = (g ^ (e & (f ^ g))) >>> 0
    const temp1 = addAll(h, s1, ch, constants[index], words[index])
    const s0 = (rotRight(a, 2) ^ rotRight(a, 13) ^ rotRight(a, 22)) >>> 0
    const maj = ((a & b) | (c & (a | b))) >>> 0
    const temp2 = add(s0, maj)
    h = g
    g = f
    f = e
    e = add(d, temp1)
    d = c
    c = b
    b = a
    a = add(temp1, temp2)
  }
  return [a, b, c, d, e, f, g, h]
}

/** Compute the initial state from the seven-byte prefix. */
function initialState(data) {
  const words = new Array(14).fill(0)
  words.push(data.readUIntBE(0, 3))
  words.push(data.readUIntBE(3, 4))
  for (let index = 16; index < 30; index += 1) {
    let value = SCHEDULE[index - 16]
    if (index - 2 >= 14) {
      const s1 = sigma1(words[index - 2])
      value = add(value, index === 16 ? (s1 ^ SIGMA1_ADJUSTMENT) : s1)
    }
    if (index - 7 >= 14) value = add(value, words[index - 7])
    if (index - 15 >= 14) {
      const s0 = sigma0(words[index - 15])
      value = add(value, index === 29 ? (s0 ^ SIGMA0_ADJUSTMENT) : s0)
    }
    words.push(value >>> 0)
  }
  words.push(addAll(sigma1(words[28]), words[23], sigma0(words[15]), words[14], ADJUSTMENT, (MASK + 1 - ROUND[14]) >>> 0))
  expandSchedule(words, 31)
  const working = compress(SEED_STATE, words, 14)
  return INITIAL.map((value, index) => add(value, working[index]))
}

/**
 * The modified SHA-256 used by the token.
 * @param {Buffer} data - material with at least seven bytes.
 * @returns {Buffer} 32-byte digest.
 */
export function customSha256(data) {
  if (data.length < 7) throw new Error('token salt must contain at least seven bytes')
  const length = 57 + data.length
  const padCount = ((55 - length) % 64 + 64) % 64
  const tail = Buffer.alloc(8)
  tail.writeBigUInt64BE(BigInt(length) * 8n, 0)
  const padded = Buffer.concat([data.subarray(7), Buffer.from([0x80]), Buffer.alloc(padCount), tail])
  let state = initialState(data.subarray(0, 7))
  for (let offset = 0; offset < padded.length; offset += 64) {
    const words = []
    for (let word = 0; word < 16; word += 1) words.push(padded.readUInt32BE(offset + word * 4))
    expandSchedule(words, 16)
    const working = compress(state, words, 0)
    state = state.map((value, index) => add(value, working[index]))
  }
  const digest = Buffer.alloc(32)
  state.forEach((value, index) => digest.writeUInt32BE(value, index * 4))
  return digest
}

const CS64_COEFFICIENTS = [
  [0xe82e91b1, 0xb32700d0], [0x44de24c6, 0x88dff51d], [0x3beb65bc, 0x29514038],
  [0xc89c5933, 0xb328cbdf], [0x8d1ec211, 0xd405b4d5], [0x314ef5d5, 0x26e55f3c],
  [0xe92491b1, 0x607801c6], [0xf0a5b9d5, 0x82b2c1fb], [0x06064cf3, 0xfa51a3da],
  [0xda79fa60, 0x207cc464], [0xbed20560, 0x3c3c74f3], [0x89f9c9f8, 0xd2d14b61],
  [0x35fa38c6, 0xbb04a2c1], [0xcb49e3c6, 0xc5626167],
]

/** CS64 digest words over the token material. */
function cs64Digest(data, digest) {
  const keyA = digest.readUInt32LE(0) | 1
  const keyB = digest.readUInt32LE(4) | 1
  const factors = [mul(keyA, 0x82893933), mul(keyB, 0x82893933)]
  const terms = []
  const offsets = []
  CS64_COEFFICIENTS.forEach(([coefficient, offset], index) => {
    terms.push(mul(coefficient, factors[index % 2]))
    offsets.push(offset >>> 0)
  })
  wordsLe4Even(data).forEach((word, index) => {
    const even = index % 2 === 0
    let term = mul(word, even ? keyA : keyB)
    let offset = mul(rol16(word), even ? 0xef0569fb : 0xc31713db)
    if (index === 0) {
      term = add(term, mul(0xf2f90b1a, factors[0]))
      offset = add(offset, 0x0b1a0000)
    }
    terms.push(term >>> 0)
    offsets.push(offset >>> 0)
  })
  let swapAcc = 0
  let swapLast = 0
  let state = 0
  let acc = 0
  for (let index = 0; index < terms.length; index += 2) {
    const x = terms[index]
    const y = terms[index + 1]
    let t = rol16(add(offsets[index], x))
    let q = mul(t, 0x76f50f34)
    swapAcc = add(swapAcc, add(mul(rol16(q), 0xc3efea97), q))
    t = rol16(add(offsets[index + 1], y))
    q = mul(t, 0x1881ce3c)
    swapLast = add(mul(rol16(q), 0x35bd1ec9), q)
    swapAcc = add(swapAcc, swapLast)
    state = add(mul(state, keyA), x)
    state = mul(rol16(state), 0xcf98b111)
    state = mul(rol16(state), 0x87085b9f)
    state = mul(rol16(state), 0x12ceb96d)
    state = mul(rol16(state), 0x257e1d83)
    acc = add(acc, state)
    t = add(mul(state, keyB), y)
    t = mul(rol16(t), 0xa27416f5)
    t = mul(rol16(t), 0xd38396ff)
    state = mul(rol16(mul(rol16(t), 0x7c932b89)), 0xbfa49f69)
    acc = add(acc, state)
  }
  return [(swapLast ^ state) >>> 0, (swapAcc ^ acc) >>> 0]
}

/**
 * The v2 token for one five-minute window.
 * @param {number} unixSeconds - window reference time.
 * @param {string} trustedToken - Edge client token.
 * @returns {string} `<cs64 hex>-<sha256 hex>`.
 */
export function secMsGecV2(unixSeconds, trustedToken) {
  let ticks = Math.floor(unixSeconds) + 11644473600
  ticks -= ticks % 300
  ticks *= 1e7
  const material = Buffer.from(`${BigInt(Math.round(ticks)).toString()}${trustedToken}`, 'ascii')
  const digest = customSha256(material)
  const [low, high] = cs64Digest(material, digest)
  const cs64 = Buffer.alloc(8)
  cs64.writeUInt32LE(low, 0)
  cs64.writeUInt32LE(high, 4)
  return `${cs64.toString('hex').toUpperCase()}-${digest.toString('hex').toUpperCase()}`
}
