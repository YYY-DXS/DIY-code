import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { DEFAULT_CONFIG } from "./defaults.mjs";

function mergeConfig(base, saved) {
  if (!saved || typeof saved !== "object") return structuredClone(base);
  return {
    ...base,
    ...saved,
    sources: { ...base.sources, ...saved.sources },
    delivery: { ...base.delivery, ...saved.delivery },
    weights: { ...base.weights, ...saved.weights },
    rssFeeds: Array.isArray(saved.rssFeeds) ? saved.rssFeeds : base.rssFeeds,
    keywords: Array.isArray(saved.keywords) ? saved.keywords : base.keywords,
    bilibiliKeywords: Array.isArray(saved.bilibiliKeywords)
      ? saved.bilibiliKeywords
      : base.bilibiliKeywords,
    githubTopics: Array.isArray(saved.githubTopics)
      ? saved.githubTopics
      : base.githubTopics
  };
}

export class Store {
  constructor(rootDir) {
    this.dataDir = path.join(rootDir, "data");
    this.reportDir = path.join(this.dataDir, "reports");
    this.configPath = path.join(this.dataDir, "config.json");
    this.statePath = path.join(this.dataDir, "state.json");
    this.viewHistoryPath = path.join(this.dataDir, "view-history.json");
    this.historyQueue = Promise.resolve();
  }

  async getViewHistory() {
    try {
      const saved = JSON.parse(await readFile(this.viewHistoryPath, "utf8"));
      return Array.isArray(saved.records) ? saved : { version: 1, records: [] };
    } catch {
      return { version: 1, records: [] };
    }
  }

  async recordView(entry) {
    const task = this.historyQueue.then(async () => {
      const history = await this.getViewHistory();
      const now = new Date().toISOString();
      const key = entry.id || entry.url;
      const existing = history.records.find(
        (record) => record.id === key || record.url === entry.url
      );
      if (existing) {
        existing.id = key;
        existing.title = entry.title;
        existing.url = entry.url;
        existing.source = entry.source;
        existing.category = entry.category;
        existing.publishedAt = entry.publishedAt || existing.publishedAt || null;
        existing.pageDescription = entry.pageDescription || existing.pageDescription || "";
        existing.content = entry.content || existing.content || existing.pageDescription || "";
        existing.image = entry.image || existing.image || "";
        existing.lastReportDate = entry.reportDate;
        existing.lastViewedAt = now;
        existing.viewCount = (existing.viewCount || 1) + 1;
        existing.dailyCounts = existing.dailyCounts || {};
        existing.dailyCounts[entry.viewedDate] =
          (existing.dailyCounts[entry.viewedDate] || 0) + 1;
      } else {
        history.records.push({
          id: key,
          title: entry.title,
          url: entry.url,
          source: entry.source,
          category: entry.category,
          publishedAt: entry.publishedAt || null,
          pageDescription: entry.pageDescription || "",
          content: entry.content || entry.pageDescription || "",
          image: entry.image || "",
          firstReportDate: entry.reportDate,
          lastReportDate: entry.reportDate,
          firstViewedAt: now,
          lastViewedAt: now,
          viewCount: 1,
          dailyCounts: { [entry.viewedDate]: 1 }
        });
      }
      history.records.sort(
        (left, right) => new Date(right.lastViewedAt) - new Date(left.lastViewedAt)
      );
      if (history.records.length > 1_000) history.records.length = 1_000;
      await this.writeJson(this.viewHistoryPath, history);
      return history.records.find((record) => record.id === key) || null;
    });
    this.historyQueue = task.catch(() => {});
    return task;
  }

  async init() {
    await mkdir(this.reportDir, { recursive: true });
  }

  async getConfig() {
    try {
      return mergeConfig(DEFAULT_CONFIG, JSON.parse(await readFile(this.configPath, "utf8")));
    } catch (error) {
      if (error.code !== "ENOENT") console.error("Could not read config:", error.message);
      return structuredClone(DEFAULT_CONFIG);
    }
  }

  async saveConfig(config) {
    await this.writeJson(this.configPath, mergeConfig(DEFAULT_CONFIG, config));
  }

  async getState() {
    try {
      return JSON.parse(await readFile(this.statePath, "utf8"));
    } catch {
      return { lastRunDate: null, lastRunAt: null, lastResult: null };
    }
  }

  async saveState(state) {
    await this.writeJson(this.statePath, state);
  }

  async saveReport(report) {
    await this.writeJson(path.join(this.reportDir, `${report.date}.json`), report);
  }

  async getReport(date) {
    try {
      return JSON.parse(
        await readFile(path.join(this.reportDir, `${date}.json`), "utf8")
      );
    } catch {
      return null;
    }
  }

  async getLatestReport() {
    const { readdir } = await import("node:fs/promises");
    try {
      const files = (await readdir(this.reportDir))
        .filter((name) => /^\d{4}-\d{2}-\d{2}\.json$/.test(name))
        .sort()
        .reverse();
      if (!files.length) return null;
      return JSON.parse(
        await readFile(path.join(this.reportDir, files[0]), "utf8")
      );
    } catch {
      return null;
    }
  }

  async listReports(limit = 14) {
    const { readdir } = await import("node:fs/promises");
    try {
      const files = (await readdir(this.reportDir))
        .filter((name) => /^\d{4}-\d{2}-\d{2}\.json$/.test(name))
        .sort()
        .reverse()
        .slice(0, limit);
      return Promise.all(
        files.map(async (file) =>
          JSON.parse(await readFile(path.join(this.reportDir, file), "utf8"))
        )
      );
    } catch {
      return [];
    }
  }

  async writeJson(target, value) {
    await mkdir(path.dirname(target), { recursive: true });
    const temporary = `${target}.${process.pid}.tmp`;
    await writeFile(temporary, JSON.stringify(value, null, 2), "utf8");
    await rename(temporary, target);
  }
}
