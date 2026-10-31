import { createServer } from "node:http";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { getAsset, isSea } from "node:sea";
import { collectAll } from "./src/collectors.mjs";
import { enrichReportMedia, isSafeMediaFilename } from "./src/content.mjs";
import { buildReport, dateInTimezone } from "./src/ranker.mjs";
import { Notifier } from "./src/notifier.mjs";
import { Scheduler } from "./src/scheduler.mjs";
import { Store } from "./src/storage.mjs";

const IS_SEA = isSea();
const ROOT = IS_SEA
  ? path.dirname(process.execPath)
  : path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(ROOT, "public");
const PORT = Number(process.env.PORT || 4173);
const HOST = process.env.HOST || "127.0.0.1";
const LOCAL_URL = `http://${HOST}:${PORT}`;
const BACKGROUND = process.argv.includes("--background");

const store = new Store(ROOT);
const toastScriptPath = IS_SEA
  ? path.join(store.dataDir, "toast.ps1")
  : path.join(ROOT, "scripts", "toast.ps1");
const notifier = new Notifier(toastScriptPath);
const clients = new Set();
let activeRun = null;
let desktopWindow = null;
const ready = store.init().then(async () => {
  if (IS_SEA) {
    await writeFile(
      toastScriptPath,
      Buffer.from(getAsset("scripts/toast.ps1")),
      "binary"
    );
  }
});

function broadcast(type, data) {
  const payload = `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
  for (const response of clients) response.write(payload);
}

async function generateReport(reason = "manual") {
  if (activeRun) return activeRun;
  activeRun = (async () => {
    await ready;
    const started = Date.now();
    const config = await store.getConfig();
    broadcast("run-status", { phase: "collecting", reason, message: "正在汇集多个来源…" });
    const collected = await collectAll(config);
    broadcast("run-status", {
      phase: "ranking",
      reason,
      message: `已取得 ${collected.items.length} 条候选，正在计算影响力…`
    });
    let report = buildReport({
      ...collected,
      config,
      durationMs: Date.now() - started
    });
    broadcast("run-status", {
      phase: "media",
      reason,
      message: "正在摘取正文并缓存图片…"
    });
    report = await enrichReportMedia(report, path.join(store.dataDir, "cache"));
    report.durationMs = Date.now() - started;
    await store.saveReport(report);
    const state = await store.getState();
    const nextState = {
      ...state,
      lastRunDate: report.date,
      lastRunAt: report.generatedAt,
      lastResult: {
        candidates: report.stats.candidates,
        news: report.news.length,
        diy: report.diy.length,
        errors: report.sourceErrors
      }
    };
    await store.saveState(nextState);
    let notifications = [];
    if (report.news.length || report.diy.length) {
      notifications = await notifier.send(report, config);
    }
    broadcast("report-complete", { report, notifications });
    return { report, notifications };
  })();
  try {
    return await activeRun;
  } finally {
    activeRun = null;
  }
}

const scheduler = new Scheduler({
  store,
  run: (reason) => generateReport(reason)
});

function json(response, status, value) {
  const body = JSON.stringify(value);
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store"
  });
  response.end(body);
}

async function parseBody(request) {
  let body = "";
  for await (const chunk of request) {
    body += chunk;
    if (body.length > 1_000_000) throw new Error("请求内容过大");
  }
  return body ? JSON.parse(body) : {};
}

function validateConfig(input) {
  if (!input || typeof input !== "object") throw new Error("设置格式无效");
  const config = structuredClone(input);
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(config.editionTime ?? "")) {
    throw new Error("推送时间格式应为 HH:mm");
  }
  try {
    new Intl.DateTimeFormat("en", { timeZone: config.timezone }).format();
  } catch {
    throw new Error("时区无效");
  }
  for (const key of ["lookbackHours", "maxNews", "maxDiy"]) {
    const value = Number(config[key]);
    if (!Number.isFinite(value) || value < 1 || value > 300) {
      throw new Error(`${key} 超出允许范围`);
    }
    config[key] = Math.round(value);
  }
  for (const key of ["keywords", "bilibiliKeywords", "githubTopics"]) {
    if (!Array.isArray(config[key]) || config[key].length > 30) {
      throw new Error(`${key} 格式无效`);
    }
    config[key] = config[key]
      .map((value) => String(value).trim())
      .filter(Boolean)
      .slice(0, 30);
  }
  if (!Array.isArray(config.rssFeeds) || config.rssFeeds.length > 15) {
    throw new Error("RSS 来源格式无效");
  }
  config.rssFeeds = config.rssFeeds.map((feed) => {
    const url = new URL(String(feed.url));
    if (!["http:", "https:"].includes(url.protocol)) throw new Error("RSS 地址无效");
    return {
      name: String(feed.name || url.hostname).trim().slice(0, 60),
      url: url.toString(),
      weight: Math.min(1, Math.max(0.1, Number(feed.weight) || 0.7))
    };
  });
  if (config.delivery.webhookUrl) {
    const url = new URL(String(config.delivery.webhookUrl));
    if (!["http:", "https:"].includes(url.protocol)) throw new Error("Webhook 地址无效");
  }
  return config;
}

function summarizeViewHistory(history, config) {
  const records = [...history.records].sort(
    (left, right) => new Date(right.lastViewedAt) - new Date(left.lastViewedAt)
  );
  const mostViewed = [...records]
    .sort(
      (left, right) =>
        right.viewCount - left.viewCount ||
        new Date(right.lastViewedAt) - new Date(left.lastViewedAt)
    )
    .slice(0, 8);
  const today = dateInTimezone(new Date(), config.timezone);
  const todayViews = records
    .reduce(
      (total, record) =>
        total +
        (record.dailyCounts?.[today] ??
          (dateInTimezone(new Date(record.lastViewedAt), config.timezone) === today
            ? 1
            : 0)),
      0
    );
  const sourceCounts = records.reduce((counts, record) => {
    counts[record.source || "其他"] = (counts[record.source || "其他"] ?? 0) + record.viewCount;
    return counts;
  }, {});
  return {
    totalViews: records.reduce((total, record) => total + record.viewCount, 0),
    uniqueItems: records.length,
    todayViews,
    records: records.slice(0, 100),
    mostViewed,
    sourceCounts
  };
}

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".avif": "image/avif",
  ".ico": "image/x-icon",
  ".webmanifest": "application/manifest+json"
};

async function serveStatic(request, response, pathname) {
  const relative = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
  if (IS_SEA) {
    const assetName = `public/${relative.replaceAll("\\", "/")}`;
    try {
      const asset = Buffer.from(getAsset(assetName));
      response.writeHead(200, {
        "Content-Type": MIME[path.extname(relative)] ?? "application/octet-stream",
        "Cache-Control": relative.endsWith(".html") ? "no-cache" : "public, max-age=3600"
      });
      response.end(asset);
    } catch {
      response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Not found");
    }
    return;
  }
  const target = path.resolve(PUBLIC, relative);
  if (!target.startsWith(`${PUBLIC}${path.sep}`) && target !== path.join(PUBLIC, "index.html")) {
    return json(response, 403, { error: "禁止访问" });
  }
  try {
    const body = await readFile(target);
    response.writeHead(200, {
      "Content-Type": MIME[path.extname(target)] ?? "application/octet-stream",
      "Cache-Control": path.extname(target) === ".html" ? "no-cache" : "public, max-age=3600"
    });
    response.end(body);
  } catch {
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("Not found");
  }
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url, `http://${request.headers.host || "localhost"}`);
  try {
    await ready;
    if (url.pathname === "/api/bootstrap" && request.method === "GET") {
      const [config, state, latest] = await Promise.all([
        store.getConfig(),
        store.getState(),
        store.getLatestReport()
      ]);
      return json(response, 200, { config, state, latest, today: dateInTimezone(new Date(), config.timezone) });
    }
    if (url.pathname === "/api/config" && request.method === "GET") {
      return json(response, 200, await store.getConfig());
    }
    if (url.pathname === "/api/config" && request.method === "PUT") {
      const config = validateConfig(await parseBody(request));
      await store.saveConfig(config);
      broadcast("config-updated", { config });
      return json(response, 200, { ok: true, config });
    }
    if (url.pathname === "/api/history" && request.method === "GET") {
      const [history, config] = await Promise.all([store.getViewHistory(), store.getConfig()]);
      return json(response, 200, summarizeViewHistory(history, config));
    }
    if (url.pathname === "/api/history/view" && request.method === "POST") {
      const body = await parseBody(request);
      let entryUrl;
      try {
        entryUrl = new URL(String(body.url || ""));
      } catch {
        return json(response, 400, { error: "浏览记录地址无效" });
      }
      if (!["http:", "https:"].includes(entryUrl.protocol)) {
        return json(response, 400, { error: "浏览记录地址无效" });
      }
      const config = await store.getConfig();
      const viewedDate = dateInTimezone(new Date(), config.timezone);
      const entry = {
        id: String(body.id || entryUrl.toString()).slice(0, 180),
        title: String(body.title || "未命名内容").slice(0, 500),
        url: entryUrl.toString(),
        source: String(body.source || "其他").slice(0, 80),
        category: body.category === "diy" ? "diy" : "news",
        publishedAt: body.publishedAt ? String(body.publishedAt).slice(0, 40) : null,
        pageDescription: String(body.pageDescription || "").slice(0, 600),
        content: String(body.content || "").slice(0, 4_000),
        image:
          typeof body.image === "string" &&
          body.image.startsWith("/media/") &&
          isSafeMediaFilename(body.image.slice("/media/".length))
            ? body.image
            : "",
        reportDate: /^\d{4}-\d{2}-\d{2}$/.test(body.reportDate || "")
          ? body.reportDate
          : viewedDate,
        viewedDate
      };
      const record = await store.recordView(entry);
      broadcast("history-updated", { record });
      return json(response, 200, { ok: true, record });
    }
    if (url.pathname === "/api/run" && request.method === "POST") {
      return json(response, 200, await generateReport("manual"));
    }
    if (url.pathname === "/api/reports" && request.method === "GET") {
      return json(response, 200, await store.listReports(30));
    }
    if (url.pathname.startsWith("/api/reports/") && request.method === "GET") {
      const date = url.pathname.split("/").pop();
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return json(response, 400, { error: "日期无效" });
      const report = await store.getReport(date);
      return report ? json(response, 200, report) : json(response, 404, { error: "没有这一天的日报" });
    }
    if (url.pathname === "/api/notifications/test" && request.method === "POST") {
      const config = await store.getConfig();
      const latest = await store.getLatestReport();
      const report =
        latest ??
        {
          date: dateInTimezone(new Date(), config.timezone),
          summary: "通知链路测试成功。完整日报生成后会在这里出现。",
          news: [],
          diy: []
        };
      const results = await notifier.send(
        {
          ...report,
          news: report.news.length
            ? report.news
            : [{ title: "通知链路测试成功" }],
          diy: report.diy.length ? report.diy : [{ title: "打开科技脉冲查看设置" }]
        },
        config
      );
      return json(response, 200, { ok: results.every((item) => item.ok), results });
    }
    if (url.pathname === "/api/events" && request.method === "GET") {
      response.writeHead(200, {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive"
      });
      response.write(`event: connected\ndata: ${JSON.stringify({ ok: true })}\n\n`);
      clients.add(response);
      request.on("close", () => clients.delete(response));
      return;
    }
    if (url.pathname.startsWith("/media/") && request.method === "GET") {
      const filename = url.pathname.slice("/media/".length);
      if (!isSafeMediaFilename(filename)) {
        return json(response, 400, { error: "图片地址无效" });
      }
      try {
        const body = await readFile(path.join(store.dataDir, "cache", "images", filename));
        const extension = path.extname(filename).slice(1);
        response.writeHead(200, {
          "Content-Type": MIME[`.${extension}`] ?? "application/octet-stream",
          "Content-Length": body.length,
          "Cache-Control": "public, max-age=86400"
        });
        response.end(body);
      } catch {
        response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
        response.end("Image not found");
      }
      return;
    }
    if (url.pathname.startsWith("/api/")) {
      return json(response, 404, { error: "接口不存在" });
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      return json(response, 405, { error: "请求方式不支持" });
    }
    await serveStatic(request, response, decodeURIComponent(url.pathname));
  } catch (error) {
    console.error(`${request.method} ${url.pathname}:`, error);
    if (!response.headersSent) {
      json(response, 500, { error: error.message || "服务器错误" });
    } else {
      response.end();
    }
  }
});

async function alreadyRunning() {
  try {
    const response = await fetch(`${LOCAL_URL}/api/bootstrap`, {
      signal: AbortSignal.timeout(1_500)
    });
    return response.ok;
  } catch {
    return false;
  }
}

async function openDesktopWindow(ownsServer = false) {
  if (BACKGROUND) return;
  process.env.WEBVIEW2_HOST =
    process.env.WEBVIEW2_HOST || path.join(ROOT, "webview2-host.exe");
  try {
    const loaded = await import("webview-node");
    const { WebView, app } = loaded.default ?? loaded;
    desktopWindow = new WebView({
      title: "科技脉冲",
      width: 1380,
      height: 900,
      minWidth: 760,
      minHeight: 560,
      center: true,
      windowsHide: true,
      backgroundColor: "#f2f0e9",
      icon: path.join(ROOT, "tech-pulse.ico"),
      url: LOCAL_URL,
      userDataFolder: path.join(store.dataDir, "webview2")
    });
    desktopWindow.on("error", (error) => console.error("Desktop window:", error));
    desktopWindow.on("closed", () => {
      desktopWindow = null;
    });
    desktopWindow.on("ready", () => desktopWindow?.loadURL(LOCAL_URL));
    desktopWindow.loadURL(LOCAL_URL);
    desktopWindow.show();
    app.on("all-closed", () => {
      if (ownsServer) server.close();
      process.exit(0);
    });
  } catch (error) {
    console.error("Could not create desktop window:", error);
    if (!ownsServer) throw error;
  }
}

function shutdown() {
  scheduler.stop();
  for (const client of clients) client.end();
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 3_000).unref();
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

async function start() {
  await ready;
  if (IS_SEA && (await alreadyRunning())) {
    await openDesktopWindow(false);
    return;
  }
  scheduler.start();
  server.listen(PORT, HOST, () => {
    console.log(`科技脉冲已启动：${LOCAL_URL}`);
    if (IS_SEA) setTimeout(() => openDesktopWindow(true), 350).unref?.();
  });
}

start().catch((error) => {
  console.error("Startup error:", error);
  process.exitCode = 1;
});
