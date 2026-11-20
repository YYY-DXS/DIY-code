/**
 * 英文 → 中文实时翻译。
 *
 * 复用 Lumen 译的有道线路（https://aidemo.youdao.com/trans，免 Key、国内直连），
 * 拉不到时退到 MyMemory。结果按原文做本地缓存（内存 + data/translate-cache.json），
 * 同一句话只请求一次，避免触发限流。
 */
import { readFile, writeFile, rename } from "node:fs/promises";
import path from "node:path";

const YOUDAO_URL = "https://aidemo.youdao.com/trans";
const MYMEMORY_URL = "https://api.mymemory.translated.net/get";
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TechPulse/2";
const CJK_RE = /[\u3400-\u9fff]/g;
const LATIN_RE = /[A-Za-z]/g;

/** 真正需要翻译的英文（纯中文、纯数字、太短的都跳过）。 */
export function needsTranslation(value) {
  const text = String(value ?? "").trim();
  if (text.length < 3) return false;
  const latin = (text.match(LATIN_RE) || []).length;
  if (latin < 3) return false;
  const cjk = (text.match(CJK_RE) || []).length;
  return cjk / Math.max(1, latin + cjk) < 0.45;
}

function splitChunks(text, limit = 900) {
  if (text.length <= limit) return [text];
  const chunks = [];
  let rest = text;
  while (rest.length > limit) {
    let cut = rest.lastIndexOf(" ", limit);
    if (cut < limit * 0.5) cut = rest.lastIndexOf("。", limit);
    if (cut < limit * 0.5) cut = limit;
    chunks.push(rest.slice(0, cut));
    rest = rest.slice(cut).trimStart();
  }
  if (rest) chunks.push(rest);
  return chunks;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function youdaoCode(target) {
  if (!target || target === "auto") return "zh-CHS";
  if (target === "zh-CN") return "zh-CHS";
  if (target === "zh-TW") return "zh-CHT";
  return target;
}

export class Translator {
  constructor({ cacheFile = "", maxCache = 3000, concurrency = 2 } = {}) {
    this.cacheFile = cacheFile;
    this.maxCache = maxCache;
    this.concurrency = Math.max(1, concurrency);
    this.cache = new Map();
    this.writeTimer = null;
    this.dirty = false;
  }

  async load() {
    if (!this.cacheFile) return;
    try {
      const raw = JSON.parse(await readFile(this.cacheFile, "utf8"));
      if (raw && typeof raw === "object") {
        for (const [key, value] of Object.entries(raw)) {
          if (typeof value === "string" && value) this.cache.set(key, value);
        }
      }
    } catch {
      // 没有缓存文件是正常情况
    }
  }

  scheduleSave() {
    if (!this.cacheFile || this.writeTimer) return;
    this.dirty = true;
    this.writeTimer = setTimeout(async () => {
      this.writeTimer = null;
      if (!this.dirty) return;
      this.dirty = false;
      try {
        const temp = `${this.cacheFile}.tmp`;
        await writeFile(temp, JSON.stringify(Object.fromEntries(this.cache)), "utf8");
        await rename(temp, this.cacheFile);
      } catch {
        // 写缓存失败不影响翻译
      }
    }, 1500);
    this.writeTimer.unref?.();
  }

  cached(text) {
    return this.cache.get(String(text ?? "").trim()) ?? "";
  }

  /**
   * 批量翻译。返回与输入等长的数组；跳过/失败的位置返回原文。
   */
  async translate(values, { to = "zh-CN" } = {}) {
    const texts = (Array.isArray(values) ? values : []).map((value) => String(value ?? ""));
    const result = new Array(texts.length);
    const queue = [];
    const seen = new Set();

    texts.forEach((value, index) => {
      const text = value.trim();
      if (!text || !needsTranslation(text)) {
        result[index] = value;
        return;
      }
      const hit = this.cache.get(text);
      if (hit) {
        result[index] = hit;
        return;
      }
      result[index] = value;
      if (!seen.has(text)) {
        seen.add(text);
        queue.push(text);
      }
    });

    if (!queue.length) return result;

    const worker = async () => {
      while (queue.length) {
        const text = queue.shift();
        const translated = await this.translateOne(text, to);
        if (translated) {
          this.cache.set(text, translated);
          if (this.cache.size > this.maxCache) {
            const oldest = this.cache.keys().next().value;
            this.cache.delete(oldest);
          }
          this.scheduleSave();
        }
      }
    };

    await Promise.all(
      Array.from({ length: Math.min(this.concurrency, queue.length) }, () => worker())
    );

    return texts.map((value, index) => {
      const text = value.trim();
      return (text && this.cache.get(text)) || value;
    });
  }

  async translateOne(text, to) {
    const target = youdaoCode(to);
    const parts = [];
    for (const chunk of splitChunks(text)) {
      let piece = await this.youdao(chunk, target);
      if (!piece) piece = await this.mymemory(chunk, to);
      if (!piece) return "";
      parts.push(piece);
    }
    return parts.join("");
  }

  async youdao(text, target) {
    for (let attempt = 1; attempt <= 2; attempt++) {
      try {
        const response = await fetch(YOUDAO_URL, {
          method: "POST",
          headers: {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded"
          },
          body: new URLSearchParams({ q: text, from: "auto", to: target }),
          signal: AbortSignal.timeout(12_000)
        });
        const data = await response.json();
        const code = String(data?.errorCode ?? "").trim();
        if (code === "0" || code === "") {
          const translated = (data.translation || []).join("").trim();
          if (translated) return translated;
          return "";
        }
        if ((code === "411" || code === "429") && attempt === 1) {
          await sleep(900);
          continue;
        }
        return "";
      } catch {
        if (attempt === 1) {
          await sleep(400);
          continue;
        }
      }
    }
    return "";
  }

  async mymemory(text, target) {
    try {
      const lang = target === "zh-CN" ? "zh-CN" : target;
      const url = `${MYMEMORY_URL}?q=${encodeURIComponent(text)}&langpair=${encodeURIComponent(
        `Autodetect|${lang}`
      )}`;
      const response = await fetch(url, {
        headers: { "User-Agent": USER_AGENT },
        signal: AbortSignal.timeout(12_000)
      });
      const data = await response.json();
      const translated = String(data?.responseData?.translatedText || "").trim();
      if (!translated) return "";
      if (/MYMEMORY WARNING|QUERY LENGTH LIMIT|INVALID (SOURCE|LANGUAGE)/i.test(translated)) return "";
      return translated;
    } catch {
      return "";
    }
  }
}
