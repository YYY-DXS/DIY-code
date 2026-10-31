import { classifyItem, containsKeyword, stripHtml } from "./collectors.mjs";

const STOP_WORDS = new Set([
  "the",
  "and",
  "for",
  "with",
  "from",
  "that",
  "this",
  "into",
  "your",
  "you",
  "has",
  "have",
  "its",
  "are",
  "new",
  "how",
  "why",
  "what",
  "today",
  "using",
  "based",
  "open",
  "source",
  "project",
  "github",
  "今日",
  "一个",
  "我们",
  "这个",
  "如何",
  "可以"
]);

function clamp(value, min = 0, max = 1) {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, value));
}

function logScore(value, scale) {
  return clamp(Math.log10(Math.max(0, value) + 1) / Math.log10(scale + 1));
}

function engagementScore(item) {
  const metrics = item.metrics ?? {};
  if (item.kind === "hackerNews") {
    return clamp(logScore(metrics.points ?? 0, 1500) * 0.72 + logScore(metrics.comments ?? 0, 800) * 0.28);
  }
  if (item.kind === "bilibili") {
    return clamp(
      logScore(metrics.views ?? 0, 1_500_000) * 0.55 +
        logScore(metrics.danmaku ?? 0, 20_000) * 0.2 +
        logScore(metrics.favorites ?? 0, 50_000) * 0.25
    );
  }
  if (item.kind === "github") {
    return clamp(
      logScore(metrics.stars ?? 0, 20_000) * 0.7 +
        logScore(metrics.forks ?? 0, 5_000) * 0.2 +
        logScore(metrics.issues ?? 0, 1_500) * 0.1
    );
  }
  return 0.42;
}

export function relevanceScore(item, keywords) {
  const text = `${item.title} ${item.summary} ${(item.tags ?? []).join(" ")}`.toLowerCase();
  let hits = 0;
  let weightedHits = 0;
  keywords.forEach((keyword, index) => {
    const normalized = keyword.trim().toLowerCase();
    if (!normalized || !containsKeyword(text, normalized)) return;
    hits += 1;
    const priority = index < 6 ? 1.15 : 1;
    weightedHits += priority;
  });
  return {
    value: clamp(1 - Math.exp(-weightedHits / 2.4)),
    matches: keywords.filter((keyword) => containsKeyword(text, keyword)).slice(0, 5)
  };
}

export function titleTokens(value = "") {
  const normalized = value
    .toLowerCase()
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/[^\p{L}\p{N}]+/gu, " ");
  const words = normalized
    .split(/\s+/)
    .filter((word) => word.length >= 3 && !STOP_WORDS.has(word));
  const chinese = [...value].filter((character) => /[\u3400-\u9fff]/.test(character));
  const bigrams = [];
  for (let index = 0; index < chinese.length - 1; index += 1) {
    bigrams.push(`${chinese[index]}${chinese[index + 1]}`);
  }
  return new Set([...words, ...bigrams]);
}

function similarity(left, right) {
  if (!left.size || !right.size) return 0;
  let intersection = 0;
  for (const token of left) if (right.has(token)) intersection += 1;
  return intersection / (left.size + right.size - intersection);
}

export function addCorroboration(items) {
  const tokenSets = items.map((item) => titleTokens(item.title));
  const sourceSets = items.map((item, index) => {
    const sources = new Set([item.source]);
    for (let other = 0; other < items.length; other += 1) {
      if (other === index) continue;
      if (similarity(tokenSets[index], tokenSets[other]) >= 0.38) {
        sources.add(items[other].source);
      }
    }
    return sources;
  });
  return items.map((item, index) => ({
    ...item,
    corroboratingSources: [...sourceSets[index]],
    corroborationScore: clamp(Math.log2(sourceSets[index].size) / 2.3)
  }));
}

export function scoreAndClassifyItems(items, config, now = new Date()) {
  const corroborated = addCorroboration(items);
  return corroborated.map((item) => {
    const publishedTimestamp = new Date(
      item.updatedAt && item.kind === "github" ? item.updatedAt : item.publishedAt
    ).getTime();
    const ageHours = Math.max(0, (now.getTime() - publishedTimestamp) / 3_600_000);
    const freshness = clamp(Math.exp(-ageHours / Math.max(18, config.lookbackHours * 1.25)));
    const relevance = relevanceScore(item, config.keywords);
    const engagement = engagementScore(item);
    const breakdown = {
      freshness,
      relevance: relevance.value,
      engagement,
      authority: clamp(Number(item.authority) || 0.5),
      corroboration: item.corroborationScore ?? 0
    };
    const score = Object.entries(config.weights).reduce(
      (total, [key, weight]) => total + (breakdown[key] ?? 0) * Number(weight),
      0
    );
    return {
      ...item,
      summary: stripHtml(item.summary).slice(0, 460),
      category: classifyItem(item),
      score: Math.round(score * 1000) / 10,
      breakdown: Object.fromEntries(
        Object.entries(breakdown).map(([key, value]) => [key, Math.round(value * 100)])
      ),
      matchedInterests: relevance.matches
    };
  });
}

function diversityPick(sorted, limit, perSource = 2) {
  const selected = [];
  const sourceCounts = new Map();
  for (const item of sorted) {
    if (selected.length >= limit) break;
    if ((sourceCounts.get(item.source) ?? 0) >= perSource) continue;
    selected.push(item);
    sourceCounts.set(item.source, (sourceCounts.get(item.source) ?? 0) + 1);
  }
  for (const item of sorted) {
    if (selected.length >= limit) break;
    if (!selected.some((existing) => existing.id === item.id)) selected.push(item);
  }
  return selected;
}

function metricLine(item) {
  if (item.kind === "hackerNews") {
    return `Hacker News ${item.metrics.points ?? 0} 热度、${item.metrics.comments ?? 0} 条讨论`;
  }
  if (item.kind === "github") {
    return `${formatNumber(item.metrics.stars ?? 0)} stars、${formatNumber(
      item.metrics.forks ?? 0
    )} forks，近期仍在更新`;
  }
  if (item.kind === "bilibili") {
    return `${formatNumber(item.metrics.views ?? 0)} 播放、${formatNumber(
      item.metrics.danmaku ?? 0
    )} 弹幕`;
  }
  return "来自已关注的科技媒体";
}

export function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN", {
    notation: value >= 10_000 ? "compact" : "standard",
    maximumFractionDigits: 1
  }).format(value);
}

function whyItMatters(item) {
  const parts = [metricLine(item)];
  if (item.matchedInterests.length) {
    parts.push(`命中兴趣：${item.matchedInterests.join("、")}`);
  }
  if (item.corroboratingSources.length > 1) {
    parts.push(`${item.corroboratingSources.length} 个来源出现相近主题`);
  }
  return parts.join("；");
}

export function buildReport({ items, errors, config, durationMs, now = new Date() }) {
  const scored = scoreAndClassifyItems(items, config, now);
  const newsSorted = scored.filter((item) => item.category === "news").sort((a, b) => b.score - a.score);
  const diySorted = scored.filter((item) => item.category === "diy").sort((a, b) => b.score - a.score);
  const news = diversityPick(newsSorted, config.maxNews, 2).map(enrich);
  const diy = diversityPick(diySorted, config.maxDiy, 2).map(enrich);
  const sourceCounts = scored.reduce((counts, item) => {
    counts[item.source] = (counts[item.source] ?? 0) + 1;
    return counts;
  }, {});
  const date = dateInTimezone(now, config.timezone);
  const total = scored.length;
  const leadingNews = news[0]?.title ?? "暂无足够的新科技新闻";
  const leadingDiy = diy[0]?.title ?? "暂无新的 DIY 项目";
  const summary = `今日从 ${Object.keys(sourceCounts).length} 个来源筛选了 ${total} 条候选内容。科技焦点是「${leadingNews}」；DIY 雷达最值得看的是「${leadingDiy}」。`;

  return {
    date,
    generatedAt: now.toISOString(),
    durationMs,
    summary,
    news,
    diy,
    stats: {
      candidates: total,
      news: newsSorted.length,
      diy: diySorted.length,
      sourceCounts
    },
    sourceErrors: errors
  };
}

function enrich(item, index) {
  return {
    ...item,
    rank: index + 1,
    whyItMatters: whyItMatters(item),
    sourceStatus:
      item.corroboratingSources.length > 1
        ? item.corroboratingSources.join(" · ")
        : item.source
  };
}

export function dateInTimezone(date, timezone) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(date);
}

export function timeInTimezone(date, timezone) {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: timezone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23"
  }).format(date);
}

export function reportToMarkdown(report) {
  const lines = [
    `# 科技脉冲 · ${report.date}`,
    "",
    report.summary,
    "",
    "## 今日科技焦点",
    ""
  ];
  for (const item of report.news) {
    lines.push(`${item.rank}. [${item.title}](${item.url}) — ${item.source}`);
    lines.push(`   ${item.whyItMatters}`);
  }
  lines.push("", "## DIY 项目雷达", "");
  for (const item of report.diy) {
    lines.push(`${item.rank}. [${item.title}](${item.url}) — ${item.source}`);
    lines.push(`   ${item.whyItMatters}`);
  }
  return lines.join("\n");
}
