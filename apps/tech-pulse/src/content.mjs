import { createHash } from "node:crypto";
import { mkdir, readFile, rename, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { decodeEntities, stripHtml } from "./collectors.mjs";

const PAGE_LIMIT = 1_800_000;
const IMAGE_LIMIT = 6_000_000;
const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 TechPulse/1.1";

function attribute(tag, name) {
  const match = tag.match(new RegExp(`${name}\\s*=\\s*["']([^"']*)["']`, "i"));
  return match ? decodeEntities(match[1]) : "";
}

function metaContent(html, names) {
  const wanted = new Set(names.map((name) => name.toLowerCase()));
  for (const match of html.matchAll(/<meta\b[^>]*>/gi)) {
    const tag = match[0];
    const key = (attribute(tag, "property") || attribute(tag, "name")).toLowerCase();
    if (wanted.has(key)) {
      const content = attribute(tag, "content").trim();
      if (content) return content;
    }
  }
  return "";
}

function absoluteUrl(value, baseUrl) {
  if (!value) return "";
  try {
    const url = new URL(value, baseUrl);
    return ["http:", "https:"].includes(url.protocol) ? url.toString() : "";
  } catch {
    return "";
  }
}

export function extractWebPageContent(html, pageUrl) {
  const title =
    metaContent(html, ["og:title", "twitter:title"]) ||
    stripHtml(html.match(/<title\b[^>]*>([\s\S]*?)<\/title>/i)?.[1] ?? "");
  const description = metaContent(html, [
    "og:description",
    "twitter:description",
    "description"
  ]);
  const image = absoluteUrl(
    metaContent(html, ["og:image", "og:image:url", "twitter:image"]),
    pageUrl
  );

  const article =
    html.match(/<article\b[^>]*>([\s\S]*?)<\/article>/i)?.[1] ||
    html.match(/<main\b[^>]*>([\s\S]*?)<\/main>/i)?.[1] ||
    html;
  const cleaned = article
    .replace(/<script\b[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[\s\S]*?<\/style>/gi, " ")
    .replace(/<(nav|footer|header|aside|form|noscript)\b[\s\S]*?<\/\1>/gi, " ");
  const paragraphs = [...cleaned.matchAll(/<p\b[^>]*>([\s\S]*?)<\/p>/gi)]
    .map((match) => stripHtml(match[1]))
    .filter((text) => text.length >= 35)
    .filter(
      (text) =>
        !/(cookie|privacy policy|subscribe|all rights reserved|点击订阅|隐私政策)/i.test(
          text
        )
    );
  const uniqueParagraphs = [...new Set(paragraphs)];
  const content = uniqueParagraphs.join("\n\n").slice(0, 1_500);

  return {
    title: stripHtml(title).slice(0, 300),
    description: description.slice(0, 600),
    content,
    image
  };
}

function hash(value) {
  return createHash("sha1").update(value).digest("hex").slice(0, 24);
}

async function cachedPagePath(cacheDir, url) {
  return path.join(cacheDir, "pages", `${hash(url)}.json`);
}

async function readPageCache(cacheDir, url) {
  try {
    return JSON.parse(await readFile(await cachedPagePath(cacheDir, url), "utf8"));
  } catch {
    return null;
  }
}

async function writePageCache(cacheDir, url, value) {
  const target = await cachedPagePath(cacheDir, url);
  await mkdir(path.dirname(target), { recursive: true });
  const temporary = `${target}.${process.pid}.tmp`;
  await writeFile(temporary, JSON.stringify(value, null, 2), "utf8");
  await rename(temporary, target);
}

async function fetchPage(url) {
  const response = await fetch(url, {
    headers: {
      "User-Agent": USER_AGENT,
      Accept: "text/html,application/xhtml+xml;q=0.9,*/*;q=0.6",
      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"
    },
    redirect: "follow",
    signal: AbortSignal.timeout(10_000)
  });
  if (!response.ok) throw new Error(`网页返回 ${response.status}`);
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("html") && !contentType.includes("text")) {
    throw new Error("网页不是可读取的 HTML");
  }
  return (await response.text()).slice(0, PAGE_LIMIT);
}

function extensionFor(contentType) {
  return (
    {
      "image/jpeg": "jpg",
      "image/png": "png",
      "image/webp": "webp",
      "image/gif": "gif",
      "image/avif": "avif"
    }[contentType.split(";")[0].trim().toLowerCase()] || ""
  );
}

async function cacheImage(cacheDir, imageUrl) {
  if (!imageUrl) return "";
  const key = hash(imageUrl);
  const imageDir = path.join(cacheDir, "images");
  await mkdir(imageDir, { recursive: true });
  for (const extension of ["jpg", "png", "webp", "gif", "avif"]) {
    const filename = `${key}.${extension}`;
    try {
      await stat(path.join(imageDir, filename));
      return `/media/${filename}`;
    } catch {
      // Try the next cached extension.
    }
  }

  const response = await fetch(imageUrl, {
    headers: { "User-Agent": USER_AGENT, Accept: "image/avif,image/webp,image/*,*/*;q=0.5" },
    redirect: "follow",
    signal: AbortSignal.timeout(12_000)
  });
  if (!response.ok) throw new Error(`图片返回 ${response.status}`);
  const extension = extensionFor(response.headers.get("content-type") || "");
  if (!extension) throw new Error("不支持的图片格式");
  const length = Number(response.headers.get("content-length") || 0);
  if (length > IMAGE_LIMIT) throw new Error("图片过大");
  const image = Buffer.from(await response.arrayBuffer());
  if (image.length > IMAGE_LIMIT) throw new Error("图片过大");
  const filename = `${key}.${extension}`;
  const target = path.join(imageDir, filename);
  const temporary = `${target}.${process.pid}.tmp`;
  await writeFile(temporary, image);
  await rename(temporary, target);
  return `/media/${filename}`;
}

async function enrichItem(item, cacheDir) {
  let page = await readPageCache(cacheDir, item.url);
  let usedCache = Boolean(page);

  if (item.kind !== "bilibili") {
    try {
      const html = await fetchPage(item.url);
      page = {
        ...extractWebPageContent(html, item.url),
        fetchedAt: new Date().toISOString()
      };
      await writePageCache(cacheDir, item.url, page);
      usedCache = false;
    } catch {
      // Existing page content remains usable when the external site is unavailable.
    }
  }

  const pageContent = page?.content || "";
  const pageDescription = page?.description || "";
  const itemContent = item.summary || pageDescription;
  let image = "";
  try {
    image = await cacheImage(cacheDir, page?.image || item.thumbnail);
  } catch {
    image = "";
  }

  return {
    ...item,
    content: pageContent || itemContent,
    pageDescription: pageDescription || item.summary,
    image,
    mediaCachedAt: page?.fetchedAt || null,
    mediaOffline: usedCache
  };
}

async function mapWithConcurrency(items, concurrency, mapper) {
  const results = new Array(items.length);
  let next = 0;
  async function worker() {
    while (next < items.length) {
      const index = next;
      next += 1;
      results[index] = await mapper(items[index], index);
    }
  }
  await Promise.all(
    Array.from({ length: Math.min(concurrency, items.length) }, () => worker())
  );
  return results;
}

export async function enrichReportMedia(report, cacheDir) {
  const hydrate = (item) =>
    enrichItem(item, cacheDir).catch(() => ({
      ...item,
      content: item.summary,
      pageDescription: item.summary,
      image: "",
      mediaCachedAt: null,
      mediaOffline: true
    }));
  const news = await mapWithConcurrency(report.news, 3, hydrate);
  const diy = await mapWithConcurrency(report.diy, 3, hydrate);
  return {
    ...report,
    news,
    diy,
    mediaStats: {
      cachedImages: [...news, ...diy].filter((item) => item.image).length,
      offlineItems: [...news, ...diy].filter((item) => item.mediaOffline).length
    }
  };
}

export function isSafeMediaFilename(filename) {
  return /^[a-f0-9]{24}\.(jpg|png|webp|gif|avif)$/.test(filename);
}
