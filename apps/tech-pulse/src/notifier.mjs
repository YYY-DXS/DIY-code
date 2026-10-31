import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { reportToMarkdown } from "./ranker.mjs";

const execFileAsync = promisify(execFile);

export class Notifier {
  constructor(toastScriptPath) {
    this.toastScriptPath = toastScriptPath;
  }

  async send(report, config) {
    const pending = [];
    if (process.platform === "win32" && config.delivery.windowsToast) {
      pending.push({
        channel: "Windows 通知",
        task: this.sendWindowsToast(report)
      });
    }
    if (config.delivery.webhookUrl) {
      pending.push({
        channel: "Webhook",
        task: this.sendWebhook(report, config.delivery.webhookUrl)
      });
    }
    if (config.delivery.serverChanKey) {
      pending.push({
        channel: "Server酱",
        task: this.sendServerChan(report, config.delivery.serverChanKey)
      });
    }
    const results = await Promise.allSettled(pending.map((entry) => entry.task));
    return results.map((result, index) => ({
      channel: pending[index].channel,
      ok: result.status === "fulfilled",
      error: result.status === "rejected" ? result.reason.message : null
    }));
  }

  async sendWindowsToast(report) {
    const body = `科技 ${report.news.length} 条 · DIY ${report.diy.length} 条。${
      report.news[0]?.title ?? report.summary
    }`;
    await execFileAsync(
      "powershell.exe",
      [
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        this.toastScriptPath,
        "科技脉冲",
        body,
        report.diy[0]?.title ?? "打开日报查看完整概览"
      ],
      { timeout: 10_000, windowsHide: true }
    );
  }

  async sendWebhook(report, webhookUrl) {
    const url = new URL(webhookUrl);
    if (!["http:", "https:"].includes(url.protocol)) {
      throw new Error("Webhook 必须使用 http 或 https");
    }
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: `科技脉冲 · ${report.date}`,
        text: report.summary,
        markdown: reportToMarkdown(report),
        url: "http://127.0.0.1:4173",
        report
      }),
      signal: AbortSignal.timeout(10_000)
    });
    if (!response.ok) throw new Error(`Webhook 返回 ${response.status}`);
  }

  async sendServerChan(report, key) {
    const body = new URLSearchParams({
      title: `科技脉冲 · ${report.date}`,
      desp: reportToMarkdown(report)
    });
    const response = await fetch(`https://sctapi.ftqq.com/${encodeURIComponent(key)}.send`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
      signal: AbortSignal.timeout(10_000)
    });
    if (!response.ok) throw new Error(`Server酱返回 ${response.status}`);
    const payload = await response.json().catch(() => ({}));
    if (payload.code !== undefined && payload.code !== 0) {
      throw new Error(payload.message ?? "Server酱推送失败");
    }
  }
}
