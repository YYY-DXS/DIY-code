import { createHash } from "node:crypto";

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 TechPulse/1.0";

const TECH_HINTS = [
  "ai",
  "artificial intelligence",
  "chip",
  "computer",
  "robot",
  "software",
  "space",
  "science",
  "hardware",
  "科技",
  "芯片",
  "人工智能",
  "航天",
  "互联网"
];

const DIY_HINTS = [
  "esp32",
  "arduino",
  "raspberry pi",
  "diy",
  "3d print",
  "open source hardware",
  "hardware project",
  "外骨骼",
  "航模",
  "开源硬件",
  "3d打印",
  "模型制作",
  "机器人制作"
];

export function stripHtml(value = "") {
  return decodeEntities(
    String(value)
      .replace(/<script[\s\S]*?<\/script>/gi, " ")
      .replace(/<style[\s\S]*?<\/style>/gi, " ")
      .replace(/<[^>]+>/g, " ")
      .replace(/\s+/g, " ")
      .trim()
  );
}

function findImage(block) {
  const candidates = [
    /<enclosure\b[^>]*\burl=["']([^"']+)["'][^>]*>/i,
    /<media:(?:content|thumbnail)\b[^>]*\burl=["']([^"']+)["'][^>]*>/i,
    /<img\b[^>]*\bsrc=["']([^"']+)["'][^>]*>/i
  ];
  for (const pattern of candidates) {
    const match = block.match(pattern);
    if (match) return decodeEntities(match[1]);
  }
  return "";
}

function parseMetric(value) {
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  const text = String(value ?? "")
    .trim()
    .replaceAll(",", "");
  const match = text.match(/^([\d.]+)\s*(万|亿)?$/);
  if (!match) return 0;
  const multiplier = match[2] === "亿" ? 100_000_000 : match[2] === "万" ? 10_000 : 1;
  return Number(match[1]) * multiplier;
}

export function decodeEntities(value = "") {
  const named = {
    amp: "&",
    lt: "<",
    gt: ">",
    quot: '"',
    apos: "'",
    nbsp: " "
  };
  return String(value)
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&#(\d+);/g, (_, number) => String.fromCodePoint(Number(number)))
    .replace(/&#x([\da-f]+);/gi, (_, number) =>
      String.fromCodePoint(Number.parseInt(number, 16))
    )
    .replace(/&([a-z]+);/gi, (match, name) => named[name.toLowerCase()] ?? match);
}

function firstTag(block, tagNames) {
  for (const tag of tagNames) {
    const match = block.match(
      new RegExp(`<${tag}(?:\\s[^>]*)?>([\\s\\S]*?)<\\/${tag}>`, "i")
    );
    if (match) return decodeEntities(match[1]).trim();
  }
  return "";
}

function findLink(block) {
  const plain = firstTag(block, ["link"]);
  if (plain) return plain;
  const href = block.match(/<link\b[^>]*\bhref=["']([^"']+)["'][^>]*>/i);
  return href ? decodeEntities(href[1]) : "";
}

function safeDate(value, fallback = new Date()) {
  const date = value ? new Date(value) : fallback;
  return Number.isNaN(date.getTime()) ? fallback.toISOString() : date.toISOString();
}

export function parseRss(xml, source, feedWeight = 0.7) {
  const blocks =
    xml.match(/<item\b[\s\S]*?<\/item>/gi) ??
    xml.match(/<entry\b[\s\S]*?<\/entry>/gi) ??
    [];

  return blocks
    .map((block) => {
      const title = stripHtml(firstTag(block, ["title"]));
      const summary = stripHtml(
        firstTag(block, ["description", "summary", "content:encoded", "content"])
      ).slice(0, 520);
      const url = findLink(block);
      const published = firstTag(block, ["pubDate", "published", "updated", "date"]);
      const categoryText = [...block.matchAll(/<category\b[^>]*>([\s\S]*?)<\/category>/gi)]
        .map((match) => stripHtml(match[1]))
        .filter(Boolean);
      if (!title || !url) return null;
      return {
        id: idFor("rss", url),
        kind: "rss",
        source,
        title,
        url,
        summary,
        publishedAt: safeDate(published),
        tags: categoryText.slice(0, 5),
        thumbnail: findImage(block),
        metrics: {},
        authority: feedWeight
      };
    })
    .filter(Boolean);
}

async function fetchText(url, options = {}, timeoutMs = 12_000) {
  const response = await fetch(url, {
    ...options,
    signal: AbortSignal.timeout(timeoutMs),
    headers: {
      "User-Agent": USER_AGENT,
      Accept: options.accept ?? "application/json, text/xml, application/xml, text/html;q=0.9, */*;q=0.8",
      ...options.headers
    }
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response;
}

export async function collectRss(feeds, lookbackHours) {
  const cutoff = Date.now() - lookbackHours * 3_600_000;
  const results = await Promise.allSettled(
    feeds.map(async (feed) => {
      const response = await fetchText(feed.url, { accept: "application/rss+xml, application/xml, text/xml" });
      return parseRss(await response.text(), feed.name, feed.weight).filter(
        (item) => new Date(item.publishedAt).getTime() >= cutoff
      );
    })
  );
  return {
    items: results.flatMap((result) => (result.status === "fulfilled" ? result.value : [])),
    errors: results
      .map((result, index) =>
        result.status === "rejected"
          ? `${feeds[index].name}: ${result.reason.message}`
          : null
      )
      .filter(Boolean)
  };
}

export async function collectHackerNews(lookbackHours) {
  const response = await fetchText("https://hacker-news.firebaseio.com/v0/topstories.json");
  const ids = (await response.json()).slice(0, 55);
  const cutoff = Date.now() - lookbackHours * 3_600_000;
  const results = await Promise.allSettled(
    ids.map(async (id) => {
      const itemResponse = await fetchText(
        `https://hacker-news.firebaseio.com/v0/item/${id}.json`,
        {},
        8_000
      );
      return itemResponse.json();
    })
  );

  return results
    .flatMap((result) => (result.status === "fulfilled" ? [result.value] : []))
    .filter(
      (item) =>
        item?.title &&
        item.url &&
        !item.deleted &&
        !item.dead &&
        item.time * 1000 >= cutoff &&
        matchesAny(`${item.title} ${item.text ?? ""}`, TECH_HINTS)
    )
    .map((item) => ({
      id: idFor("hn", String(item.id)),
      kind: "hackerNews",
      source: "Hacker News",
      title: item.title,
      url: item.url,
      summary: stripHtml(item.text ?? "").slice(0, 420),
      publishedAt: new Date(item.time * 1000).toISOString(),
      tags: ["科技"],
      metrics: { points: item.score ?? 0, comments: item.descendants ?? 0 },
      authority: 0.88
    }));
}

const MIXIN_KEY_ENC_TAB = [
  46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5,
  49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55,
  40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57,
  62, 11, 36, 20, 34, 44, 52
];

function md5(value) {
  return createHash("md5").update(value).digest("hex");
}

async function getWbiKeys() {
  const response = await fetchText(
    "https://api.bilibili.com/x/web-interface/nav",
    {
      headers: {
        Referer: "https://www.bilibili.com/",
        Cookie: process.env.BILIBILI_COOKIE ?? ""
      }
    },
    8_000
  );
  const data = (await response.json()).data;
  const getKey = (url) => url?.split("/").pop()?.split(".")[0] ?? "";
  return { imgKey: getKey(data.wbi_img?.img_url), subKey: getKey(data.wbi_img?.sub_url) };
}

function signedBiliUrl(params, keys) {
  const raw = `${keys.imgKey}${keys.subKey}`;
  const mixinKey = MIXIN_KEY_ENC_TAB.map((index) => raw[index] ?? "").join("").slice(0, 32);
  const clean = Object.fromEntries(
    Object.entries({ ...params, wts: Math.floor(Date.now() / 1000) }).map(
      ([key, value]) => [key, String(value).replace(/[!'()*]/g, "")]
    )
  );
  const query = new URLSearchParams(
    Object.keys(clean)
      .sort()
      .map((key) => [key, clean[key]])
  );
  return `https://api.bilibili.com/x/web-interface/wbi/search/type?${query}&w_rid=${md5(
    `${query}${mixinKey}`
  )}`;
}

async function collectBilibiliSearch(keyword, keys) {
  const response = await fetchText(
    signedBiliUrl(
      {
        search_type: "video",
        keyword,
        order: "pubdate",
        page: 1,
        page_size: 20
      },
      keys
    ),
    {
      headers: {
        Referer: `https://search.bilibili.com/all?keyword=${encodeURIComponent(keyword)}`,
        Cookie: process.env.BILIBILI_COOKIE ?? ""
      }
    }
  );
  const payload = await response.json();
  if (payload.code !== 0) throw new Error(`Bilibili API ${payload.code}: ${payload.message}`);
  return (payload.data?.result ?? []).map((video) => {
    const bvid = video.bvid;
    return {
      id: idFor("bilibili", bvid || video.arcurl),
      kind: "bilibili",
      source: "B站",
      title: stripHtml(video.title),
      url: bvid ? `https://www.bilibili.com/video/${bvid}` : video.arcurl,
      summary: stripHtml(video.description).slice(0, 420),
      publishedAt: new Date(video.pubdate * 1000).toISOString(),
      tags: [video.typename, ...(video.tag ? video.tag.split(",") : [])].filter(Boolean).slice(0, 6),
      thumbnail: normalizeBiliImage(video.pic),
      author: video.author,
      metrics: {
        views: parseMetric(video.play),
        danmaku: parseMetric(video.video_review),
        favorites: parseMetric(video.favorites)
      },
      authority: 0.72
    };
  });
}

function normalizeBiliImage(url = "") {
  if (!url) return "";
  return url.startsWith("//") ? `https:${url}` : url.replace(/^http:/, "https:");
}

export async function collectBilibili(keywords, lookbackHours) {
  const cutoff = Date.now() - lookbackHours * 3_600_000;
  try {
    const keys = await getWbiKeys();
    if (!keys.imgKey || !keys.subKey) throw new Error("WBI key unavailable");
    const results = await Promise.allSettled(
      keywords.slice(0, 4).map((keyword) => collectBilibiliSearch(keyword, keys))
    );
    const items = results
      .flatMap((result) => (result.status === "fulfilled" ? result.value : []))
      .filter((item) => new Date(item.publishedAt).getTime() >= cutoff);
    if (!items.length) {
      throw new Error(
        results.find((result) => result.status === "rejected")?.reason?.message ??
          "B站近期没有匹配内容"
      );
    }
    return { items: dedupe(items), errors: [] };
  } catch (error) {
    return { items: [], errors: [`B站: ${error.message}`] };
  }
}

export async function collectGithub(topics, lookbackHours) {
  const twoWeeksAgo = new Date(Date.now() - 14 * 86_400_000).toISOString().slice(0, 10);
  const headers = {
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
  };
  if (process.env.GITHUB_TOKEN) headers.Authorization = `Bearer ${process.env.GITHUB_TOKEN}`;

  // GitHub repository search combines topics with AND. Query a spread of up to
  // four configured topics separately to stay inside the unauthenticated
  // search quota while still covering ESP32/Arduino/robotics-style interests.
  const selectedTopics = topics.slice(0, 12).filter((_, index, all) => {
    if (all.length <= 4) return true;
    const slots = new Set(
      [0, 1, 2, 3].map((slot) => Math.round((slot * (all.length - 1)) / 3))
    );
    return slots.has(index);
  });
  const results = await Promise.allSettled(
    selectedTopics.map(async (topic) => {
      const url = new URL("https://api.github.com/search/repositories");
      url.searchParams.set("q", `topic:${topic} created:>=${twoWeeksAgo} stars:>2`);
      url.searchParams.set("sort", "stars");
      url.searchParams.set("order", "desc");
      url.searchParams.set("per_page", "15");
      const response = await fetchText(url, { headers });
      return (await response.json()).items ?? [];
    })
  );
  const repos = results.flatMap((result) =>
    result.status === "fulfilled" ? result.value : []
  );
  if (!repos.length) {
    const message = results.find((result) => result.status === "rejected")?.reason?.message;
    throw new Error(message ? `GitHub 搜索失败：${message}` : "GitHub 近期没有匹配项目");
  }
  const cutoff = Date.now() - Math.max(lookbackHours, 24 * 7) * 3_600_000;
  return dedupe(
    repos
    .filter((repo) => new Date(repo.pushed_at ?? repo.created_at).getTime() >= cutoff)
    .map((repo) => ({
      id: idFor("github", String(repo.id)),
      kind: "github",
      source: "GitHub",
      title: repo.full_name,
      url: repo.html_url,
      summary: stripHtml(repo.description ?? "暂无项目描述").slice(0, 420),
      publishedAt: safeDate(repo.created_at),
      updatedAt: safeDate(repo.pushed_at ?? repo.updated_at),
      tags: [...(repo.topics ?? []), repo.language].filter(Boolean).slice(0, 8),
      author: repo.owner?.login,
      thumbnail: repo.owner?.avatar_url,
      metrics: {
        stars: repo.stargazers_count ?? 0,
        forks: repo.forks_count ?? 0,
        issues: repo.open_issues_count ?? 0
      },
      authority: 0.78
    }))
  );
}

export async function collectAll(config) {
  const collectors = [
    {
      name: "科技媒体 RSS",
      enabled: config.sources.rss,
      task: () => collectRss(config.rssFeeds, config.lookbackHours)
    },
    {
      name: "Hacker News",
      enabled: config.sources.hackerNews,
      task: () =>
        collectHackerNews(config.lookbackHours).then((items) => ({ items, errors: [] }))
    },
    {
      name: "B站",
      enabled: config.sources.bilibili,
      task: () => collectBilibili(config.bilibiliKeywords, config.lookbackHours)
    },
    {
      name: "GitHub",
      enabled: config.sources.github,
      task: () =>
        collectGithub(config.githubTopics, config.lookbackHours).then((items) => ({
          items,
          errors: []
        }))
    }
  ];
  const settled = await Promise.allSettled(
    collectors.map((collector) =>
      collector.enabled
        ? collector.task()
        : Promise.resolve({ items: [], errors: [] })
    )
  );
  const result = settled.map((entry, index) =>
    entry.status === "fulfilled"
      ? entry.value
      : {
          items: [],
          errors: [`${collectors[index].name}: ${entry.reason?.message ?? "未知抓取错误"}`]
        }
  );
  return {
    items: dedupe(result.flatMap((group) => group.items)),
    errors: result.flatMap((group) => group.errors).filter(Boolean)
  };
}

export function classifyItem(item) {
  const text = `${item.title} ${item.summary} ${item.tags.join(" ")}`.toLowerCase();
  if (item.kind === "github" || item.kind === "bilibili") return "diy";
  return matchesAny(text, DIY_HINTS) ? "diy" : "news";
}

function matchesAny(text, words) {
  return words.some((word) => containsKeyword(text, word));
}

export function containsKeyword(text, keyword) {
  const haystack = String(text).toLowerCase();
  const needle = String(keyword).trim().toLowerCase();
  if (!needle) return false;
  // Short Latin keywords such as "AI" must match a whole word, otherwise
  // ordinary words like "captain" and "said" create false positives.
  if (/^[a-z0-9][a-z0-9 .+#/-]*$/.test(needle)) {
    const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(?<![a-z0-9])${escaped}(?![a-z0-9])`, "i").test(haystack);
  }
  return haystack.includes(needle);
}

function idFor(kind, value) {
  return `${kind}-${createHash("sha1").update(`${kind}:${value}`).digest("hex").slice(0, 12)}`;
}

export function dedupe(items) {
  const seen = new Set();
  return items.filter(Boolean).filter((item) => {
    const key = item.url || item.id;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
