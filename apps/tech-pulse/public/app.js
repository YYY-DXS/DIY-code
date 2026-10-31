const state = {
  config: null,
  latest: null,
  currentReport: null,
  running: false,
  reports: [],
  browseHistory: null,
  historyTab: "viewed"
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const SOURCE_NAMES = {
  rss: "科技媒体",
  hackerNews: "Hacker News",
  bilibili: "B站",
  github: "GitHub"
};

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.toString() : "#";
  } catch {
    return "#";
  }
}

function truncate(value, length = 230) {
  const text = String(value || "");
  return text.length > length ? `${text.slice(0, length).trim()}…` : text;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `请求失败（${response.status}）`);
  return payload;
}

function showToast(message, duration = 2800) {
  const toast = $("#app-toast");
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => {
    toast.hidden = true;
  }, duration);
}

function setStatus(message, mode = "ready") {
  $("#status-text").textContent = message;
  const strip = $("#status-strip");
  strip.classList.toggle("is-running", mode === "running");
  strip.classList.toggle("is-error", mode === "error");
}

function setRunning(running) {
  state.running = running;
  $("#run-button").disabled = running;
  $("#run-button").classList.toggle("is-loading", running);
  $("#run-progress").hidden = !running;
  if (running) setStatus("正在寻找今天最值得关注的内容…", "running");
}

function updateHeaderDate(config) {
  const now = new Date();
  const locale = config?.timezone || "Asia/Shanghai";
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("zh-CN", {
      timeZone: locale,
      year: "numeric",
      month: "long",
      day: "numeric",
      weekday: "long"
    })
      .formatToParts(now)
      .map((part) => [part.type, part.value])
  );
  $("#date-day").textContent = parts.day?.padStart(2, "0") || "--";
  $("#date-month").textContent = `${parts.month || ""} · ${parts.weekday || ""}`;
  $("#date-year").textContent = parts.year || "";
  updateNextEdition(config);
}

function updateNextEdition(config) {
  if (!config) return;
  const target = new Intl.DateTimeFormat("en-GB", {
    timeZone: config.timezone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23"
  }).format(new Date());
  $("#next-edition").textContent = config.enabled
    ? target < config.editionTime
      ? config.editionTime
      : `明日 ${config.editionTime}`
    : "已暂停";
}

function relativeTime(value) {
  if (!value) return "尚未生成";
  const seconds = Math.round((Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86_400)} 天前`;
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function renderReport(report) {
  state.currentReport = report;
  $("#welcome").hidden = true;
  $("#report-content").hidden = false;
  $("#edition-date").textContent = `${report.date} · ${formatDate(report.generatedAt)} 生成`;
  $("#brief-summary").textContent = report.summary;
  $("#metric-candidates").textContent = report.stats?.candidates ?? 0;
  $("#metric-sources").textContent = Object.keys(report.stats?.sourceCounts ?? {}).length;
  $("#metric-time").textContent = `${Math.max(0.1, (report.durationMs ?? 0) / 1000).toFixed(1)}s`;

  const sourceCounts = Object.entries(report.stats?.sourceCounts ?? {}).sort(
    (left, right) => right[1] - left[1]
  );
  $("#source-rail").innerHTML = sourceCounts
    .map(
      ([source, count]) =>
        `<span class="source-chip">${escapeHtml(source)} <b>${count}</b></span>`
    )
    .join("");

  $("#news-list").innerHTML = report.news.length
    ? report.news.map(renderStory).join("")
    : `<p class="empty-history">今天没有筛到足够相关的科技新闻，可以扩大回溯时间或增加关键词。</p>`;
  $("#diy-list").innerHTML = report.diy.length
    ? report.diy.map(renderProject).join("")
    : `<p class="empty-history">今天还没有新的 DIY 项目。GitHub 与 B站的数据源状态见页面底部。</p>`;

  const errors = report.sourceErrors ?? [];
  $("#error-note").hidden = errors.length === 0;
  $("#error-note").innerHTML = errors.length
    ? `<strong>部分来源未完整返回：</strong>${errors.map(escapeHtml).join(" · ")}。其余来源仍已正常聚合。`
    : "";
  setStatus(
    report.news.length || report.diy.length
      ? `日报已就绪 · ${relativeTime(report.generatedAt)} · ${report.news.length} 条新闻 / ${report.diy.length} 个 DIY 项目`
      : "本次未取得有效内容，请检查网络或来源设置",
    report.news.length || report.diy.length ? "ready" : "error"
  );
}

function renderStory(item) {
  const tags = (item.tags ?? [])
    .slice(0, 4)
    .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
    .join("");
  const interests = (item.matchedInterests ?? [])
    .map((interest) => `<span class="interest-chip">命中 · ${escapeHtml(interest)}</span>`)
    .join("");
  const hasLongContent =
    item.content && item.content.length > (item.pageDescription || item.summary || "").length + 60;
  const image = item.image
    ? `<a class="story-image" data-track-id="${escapeHtml(item.id)}" href="${escapeHtml(
        safeUrl(item.url)
      )}" target="_blank" rel="noopener noreferrer">
        <img src="${escapeHtml(item.image)}" alt="" loading="lazy" />
        <span>${item.mediaOffline ? "本地缓存" : "网页图片"}</span>
      </a>`
    : "";
  return `
    <article class="story">
      <div class="story-rank">${String(item.rank).padStart(2, "0")}</div>
      <div>
        <h3 class="story-title">
          <a data-track-id="${escapeHtml(item.id)}" href="${escapeHtml(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer">
            ${escapeHtml(item.title)}
          </a>
        </h3>
        ${image}
        <p class="story-summary">${escapeHtml(
          truncate(item.pageDescription || item.summary || "打开原文查看详细报道。")
        )}</p>
        ${
          hasLongContent
            ? `<details class="story-excerpt">
                <summary>展开网页正文摘录${item.mediaOffline ? " · 来自本地缓存" : ""}</summary>
                <p>${escapeHtml(truncate(item.content, 1_100))}</p>
              </details>`
            : ""
        }
        <div class="story-meta">
          <span class="story-source">${escapeHtml(item.sourceStatus || item.source)}</span>
          <span>${escapeHtml(formatDate(item.publishedAt))}</span>
          <span class="story-why">${escapeHtml(item.whyItMatters)}</span>
        </div>
        ${interests ? `<div class="interest-row">${interests}</div>` : ""}
        ${tags ? `<div class="story-tags">${tags}</div>` : ""}
      </div>
      <div class="score">
        <div class="score-value"><strong>${Number(item.score).toFixed(1)}</strong><span>/100</span></div>
        <div class="score-bar"><i style="width:${Math.min(100, Number(item.score))}%"></i></div>
        <span class="score-label">IMPACT</span>
        <a class="open-link" data-track-id="${escapeHtml(item.id)}" href="${escapeHtml(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer">阅读原文</a>
      </div>
    </article>
  `;
}

function renderProject(item) {
  const tags = (item.tags ?? [])
    .slice(0, 3)
    .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
    .join("");
  const interests = (item.matchedInterests ?? [])
    .map((interest) => `<span class="interest-chip">命中 · ${escapeHtml(interest)}</span>`)
    .join("");
  const hasLongContent =
    item.content && item.content.length > (item.pageDescription || item.summary || "").length + 60;
  const image = item.image
    ? `<a class="project-image" data-track-id="${escapeHtml(item.id)}" href="${escapeHtml(
        safeUrl(item.url)
      )}" target="_blank" rel="noopener noreferrer">
        <img src="${escapeHtml(item.image)}" alt="" loading="lazy" />
        <span>${item.mediaOffline ? "本地缓存" : "项目图片"}</span>
      </a>`
    : "";
  return `
    <article class="project-card" data-rank="${String(item.rank).padStart(2, "0")}">
      <div class="project-topline">
        <span class="project-source">${escapeHtml(item.sourceStatus || item.source)}</span>
        <span class="project-score">IMPACT ${Number(item.score).toFixed(1)}</span>
      </div>
      ${image}
      <h3 class="project-title">
        <a data-track-id="${escapeHtml(item.id)}" href="${escapeHtml(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer">
          ${escapeHtml(item.title)}
        </a>
      </h3>
      <p class="project-summary">${escapeHtml(
        truncate(item.pageDescription || item.summary || "这是一个值得打开看看的新项目。", 165)
      )}</p>
      ${
        hasLongContent
          ? `<details class="project-excerpt">
              <summary>展开说明${item.mediaOffline ? " · 离线缓存" : ""}</summary>
              <p>${escapeHtml(truncate(item.content, 900))}</p>
            </details>`
          : ""
      }
      ${interests ? `<div class="interest-row">${interests}</div>` : ""}
      <div class="project-bottom">
        <div class="story-tags">${tags || `<span class="tag">DIY</span>`}</div>
        <div class="project-metric">
          ${escapeHtml(item.whyItMatters)}
          <br />
          <a class="open-link" data-track-id="${escapeHtml(item.id)}" href="${escapeHtml(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer">查看项目</a>
        </div>
      </div>
    </article>
  `;
}

async function generateReport() {
  if (state.running) return;
  setRunning(true);
  $("#progress-label").textContent = "正在汇集多个来源…";
  try {
    const payload = await api("/api/run", { method: "POST" });
    state.latest = payload.report;
    renderReport(payload.report);
    const failed = (payload.notifications ?? []).filter((item) => !item.ok);
    showToast(
      failed.length
        ? "日报已生成；部分通知渠道发送失败"
        : "今日日报已生成"
    );
  } catch (error) {
    setStatus(`生成失败：${error.message}`, "error");
    showToast(`生成失败：${error.message}`, 5000);
  } finally {
    setRunning(false);
  }
}

function populateSettings(config) {
  const form = $("#settings-form");
  form.elements.editionTime.value = config.editionTime;
  if (![...form.elements.timezone.options].some((option) => option.value === config.timezone)) {
    form.elements.timezone.add(new Option(config.timezone, config.timezone));
  }
  form.elements.timezone.value = config.timezone;
  form.elements.enabled.checked = config.enabled;
  form.elements.lookbackHours.value = config.lookbackHours;
  form.elements.maxNews.value = config.maxNews;
  form.elements.maxDiy.value = config.maxDiy;
  form.elements["source-rss"].checked = config.sources.rss;
  form.elements["source-hackerNews"].checked = config.sources.hackerNews;
  form.elements["source-bilibili"].checked = config.sources.bilibili;
  form.elements["source-github"].checked = config.sources.github;
  form.elements.rssFeeds.value = config.rssFeeds
    .map((feed) => `${feed.name} | ${feed.url}`)
    .join("\n");
  form.elements.bilibiliKeywords.value = config.bilibiliKeywords.join(", ");
  form.elements.githubTopics.value = config.githubTopics.join(", ");
  form.elements.keywords.value = config.keywords.join("\n");
  form.elements.windowsToast.checked = config.delivery.windowsToast;
  form.elements.browserNotification.checked = config.delivery.browserNotification;
  form.elements.webhookUrl.value = config.delivery.webhookUrl;
  form.elements.serverChanKey.value = config.delivery.serverChanKey;
}

function parseFeedLines(value) {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const separator = line.indexOf("|");
      if (separator === -1) throw new Error(`RSS 行缺少“|”：${line}`);
      return {
        name: line.slice(0, separator).trim(),
        url: line.slice(separator + 1).trim(),
        weight: 0.8
      };
    });
}

function configFromForm() {
  const form = $("#settings-form");
  const existingWeights = new Map(
    state.config.rssFeeds.map((feed) => [feed.url, feed.weight])
  );
  const feeds = parseFeedLines(form.elements.rssFeeds.value).map((feed) => ({
    ...feed,
    weight: existingWeights.get(feed.url) ?? feed.weight
  }));
  return {
    ...state.config,
    editionTime: form.elements.editionTime.value,
    timezone: form.elements.timezone.value,
    enabled: form.elements.enabled.checked,
    lookbackHours: Number(form.elements.lookbackHours.value),
    maxNews: Number(form.elements.maxNews.value),
    maxDiy: Number(form.elements.maxDiy.value),
    keywords: form.elements.keywords.value
      .split(/\r?\n|,/)
      .map((item) => item.trim())
      .filter(Boolean),
    bilibiliKeywords: form.elements.bilibiliKeywords.value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    githubTopics: form.elements.githubTopics.value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    rssFeeds: feeds,
    sources: {
      rss: form.elements["source-rss"].checked,
      hackerNews: form.elements["source-hackerNews"].checked,
      bilibili: form.elements["source-bilibili"].checked,
      github: form.elements["source-github"].checked
    },
    delivery: {
      windowsToast: form.elements.windowsToast.checked,
      browserNotification: form.elements.browserNotification.checked,
      webhookUrl: form.elements.webhookUrl.value.trim(),
      serverChanKey: form.elements.serverChanKey.value.trim()
    }
  };
}

async function saveSettings(config) {
  $("#settings-error").hidden = true;
  const payload = await api("/api/config", {
    method: "PUT",
    body: JSON.stringify(config)
  });
  state.config = payload.config;
  populateSettings(payload.config);
  updateHeaderDate(payload.config);
  return payload.config;
}

async function submitSettings(event) {
  event.preventDefault();
  const button = event.submitter;
  try {
    button.disabled = true;
    const config = configFromForm();
    if (config.delivery.browserNotification && "Notification" in window) {
      await Notification.requestPermission();
    }
    await saveSettings(config);
    closeDrawers();
    showToast("设置已保存");
  } catch (error) {
    const note = $("#settings-error");
    note.textContent = error.message;
    note.hidden = false;
  } finally {
    button.disabled = false;
  }
}

async function testNotification() {
  const button = $("#test-notification");
  try {
    button.disabled = true;
    button.textContent = "发送中…";
    const config = configFromForm();
    if (config.delivery.browserNotification && "Notification" in window) {
      await Notification.requestPermission();
    }
    await saveSettings(config);
    const result = await api("/api/notifications/test", { method: "POST" });
    if (!result.ok) {
      const failure = result.results.find((item) => !item.ok);
      throw new Error(failure?.error || "通知发送失败");
    }
    if (
      state.config.delivery.browserNotification &&
      Notification.permission === "granted"
    ) {
      new Notification("科技脉冲 · 通知测试", {
        body: "通知链路可用。日报将在设定时间自动生成。"
      });
    }
    showToast("测试通知已发送");
  } catch (error) {
    showToast(`通知测试失败：${error.message}`, 5000);
  } finally {
    button.disabled = false;
    button.textContent = "测试当前通知";
  }
}

function openDrawer(id) {
  closeDrawers();
  $("#drawer-backdrop").hidden = false;
  const drawer = $(`#${id}`);
  drawer.classList.add("is-open");
  drawer.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
}

function closeDrawers() {
  $$(".drawer").forEach((drawer) => {
    drawer.classList.remove("is-open");
    drawer.setAttribute("aria-hidden", "true");
  });
  $("#drawer-backdrop").hidden = true;
  document.body.style.overflow = "";
}

function renderBrowseRow(record, index, showCount = false) {
  return `
    <a class="browse-item" data-track-id="${escapeHtml(record.id)}" href="${escapeHtml(safeUrl(record.url))}" target="_blank" rel="noopener noreferrer">
      <span class="browse-rank">${String(index + 1).padStart(2, "0")}</span>
      <span class="browse-copy">
        <strong>${escapeHtml(record.title)}</strong>
        <small>${escapeHtml(record.source || "其他")} · ${escapeHtml(relativeTime(record.lastViewedAt))}</small>
      </span>
      <span class="browse-count">${showCount ? `${record.viewCount} 次` : "↗"}</span>
    </a>
  `;
}

function renderViewHistory(history) {
  state.browseHistory = history;
  const sourceEntries = Object.entries(history.sourceCounts ?? {}).sort(
    (left, right) => right[1] - left[1]
  );
  const topSource = sourceEntries[0];
  $("#view-history-stats").innerHTML = `
    <div><strong>${history.todayViews}</strong><span>今日浏览</span></div>
    <div><strong>${history.uniqueItems}</strong><span>不同内容</span></div>
    <div><strong>${escapeHtml(topSource?.[0] ?? "—")}</strong><span>最常来源</span></div>
  `;
  $("#most-viewed-list").innerHTML = history.mostViewed.length
    ? history.mostViewed
        .slice(0, 6)
        .map((record, index) => renderBrowseRow(record, index, true))
        .join("")
    : `<p class="empty-history">还没有阅读记录。打开任意文章或项目后，这里会开始统计。</p>`;
  $("#recent-viewed-list").innerHTML = history.records.length
    ? history.records
        .slice(0, 20)
        .map((record, index) => renderBrowseRow(record, index))
        .join("")
    : `<p class="empty-history">最近看过的内容会按时间出现在这里。</p>`;
}

function renderArchive() {
  const list = $("#history-list");
  list.innerHTML = state.reports.length
    ? state.reports
        .map(
          (report) => `
            <button class="history-item" data-date="${escapeHtml(report.date)}" type="button">
              <strong>${escapeHtml(report.date)}</strong>
              <span>${report.news.length} + ${report.diy.length}</span>
              <p>${escapeHtml(truncate(report.summary, 100))}</p>
            </button>
          `
        )
        .join("")
    : `<p class="empty-history">还没有日报历史。先生成今天的第一份吧。</p>`;
  $$(".history-item").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        const report = await api(`/api/reports/${button.dataset.date}`);
        renderReport(report);
        closeDrawers();
        window.scrollTo({ top: 0, behavior: "smooth" });
      } catch (error) {
        showToast(error.message);
      }
    });
  });
}

function switchHistoryTab(tab) {
  state.historyTab = tab;
  $$("[data-history-tab]").forEach((button) => {
    const active = button.dataset.historyTab === tab;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  $("#view-history-panel").hidden = tab !== "viewed";
  $("#archive-history-panel").hidden = tab !== "archive";
  if (tab === "archive") renderArchive();
}

async function openHistory() {
  openDrawer("history-drawer");
  $("#view-history-stats").innerHTML = "";
  $("#most-viewed-list").innerHTML = `<p class="empty-history">正在读取本地阅读记录…</p>`;
  $("#recent-viewed-list").innerHTML = "";
  try {
    const [history, reports] = await Promise.all([
      api("/api/history"),
      api("/api/reports")
    ]);
    state.reports = reports;
    renderViewHistory(history);
    switchHistoryTab(state.historyTab);
  } catch (error) {
    $("#most-viewed-list").innerHTML = `<p class="empty-history">${escapeHtml(error.message)}</p>`;
  }
}

function findTrackedItem(id) {
  const report = state.currentReport;
  const reportItem = report
    ? [...report.news, ...report.diy].find((item) => item.id === id)
    : null;
  if (reportItem) return { ...reportItem, reportDate: report.date };
  const historyItem = state.browseHistory?.records.find((item) => item.id === id);
  return historyItem
    ? {
        ...historyItem,
        reportDate: historyItem.lastReportDate,
        publishedAt: historyItem.publishedAt
      }
    : null;
}

function closeReader() {
  $("#reader-overlay").hidden = true;
  document.body.style.overflow = "";
}

function showReader(item) {
  const image = $("#reader-image");
  if (item.image) {
    image.src = item.image;
    image.hidden = false;
  } else {
    image.removeAttribute("src");
    image.hidden = true;
  }
  $("#reader-meta").textContent = `${item.source || "其他"} · ${
    item.category === "diy" ? "DIY 项目" : "科技新闻"
  } · ${formatDate(item.publishedAt) || item.reportDate || ""}`;
  $("#reader-title").textContent = item.title;
  $("#reader-source-link").href = safeUrl(item.url);
  $("#reader-interests").innerHTML = (item.matchedInterests ?? [])
    .map((interest) => `<span class="interest-chip">命中 · ${escapeHtml(interest)}</span>`)
    .join("");
  const paragraphs = String(item.content || item.pageDescription || item.summary || "")
    .split(/\n{2,}/)
    .map((text) => text.trim())
    .filter(Boolean);
  $("#reader-body").innerHTML = (paragraphs.length ? paragraphs : ["暂时没有可显示的正文摘录。"])
    .map((text) => `<p>${escapeHtml(text)}</p>`)
    .join("");
  $("#reader-cache-note").textContent = item.mediaOffline
    ? "外部网站暂时不可用，当前显示的是本地缓存内容。"
    : "正文和图片已在生成本期日报时缓存，断网后仍可继续阅读。";
  $("#reader-overlay").hidden = false;
  document.body.style.overflow = "hidden";
  $("#reader-close").focus();
}

function recordOpen(event) {
  if (!(event.target instanceof Element)) return;
  const link = event.target.closest("a[data-track-id]");
  if (!link) return;
  const item = findTrackedItem(link.dataset.trackId);
  if (!item) return;
  const payload = {
    id: item.id,
    title: item.title,
    url: item.url,
    source: item.source,
    category: item.category,
    publishedAt: item.publishedAt,
    reportDate: item.reportDate,
    pageDescription: item.pageDescription || item.summary,
    content: item.content || item.summary,
    image: item.image || ""
  };
  const body = JSON.stringify(payload);
  if (navigator.sendBeacon) {
    navigator.sendBeacon(
      "/api/history/view",
      new Blob([body], { type: "application/json" })
    );
  } else {
    fetch("/api/history/view", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true
    }).catch(() => {});
  }
  if (event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey) {
    event.preventDefault();
    showReader(item);
  }
}

function connectEvents() {
  if (!("EventSource" in window)) return;
  const events = new EventSource("/api/events");
  events.addEventListener("run-status", (event) => {
    const data = JSON.parse(event.data);
    $("#progress-label").textContent = data.message;
  });
  events.addEventListener("report-complete", (event) => {
    const data = JSON.parse(event.data);
    if (state.currentReport?.generatedAt !== data.report.generatedAt) {
      renderReport(data.report);
    }
    if (
      state.config?.delivery.browserNotification &&
      "Notification" in window &&
      Notification.permission === "granted"
    ) {
      const notification = new Notification(`科技脉冲 · ${data.report.date}`, {
        body: `${data.report.news[0]?.title ?? "今日科技日报已生成"} · 另含 ${
          data.report.diy.length
        } 个 DIY 项目`
      });
      notification.onclick = () => window.focus();
    }
  });
  events.onerror = () => {
    // EventSource reconnects automatically; no user-facing error is needed.
  };
}

async function init() {
  $("#run-button").addEventListener("click", generateReport);
  $("#settings-button").addEventListener("click", () => openDrawer("settings-drawer"));
  $("#interests-button").addEventListener("click", () => {
    openDrawer("settings-drawer");
    setTimeout(() => {
      const keywords = $("#settings-form").elements.keywords;
      keywords.scrollIntoView({ behavior: "smooth", block: "center" });
      keywords.focus();
    }, 320);
  });
  $("#history-button").addEventListener("click", openHistory);
  $("#settings-form").addEventListener("submit", submitSettings);
  $("#test-notification").addEventListener("click", testNotification);
  $("#drawer-backdrop").addEventListener("click", closeDrawers);
  $("#reader-close").addEventListener("click", closeReader);
  $("#reader-overlay").addEventListener("click", (event) => {
    if (event.target === $("#reader-overlay")) closeReader();
  });
  $$(".close-drawer").forEach((button) => button.addEventListener("click", closeDrawers));
  $$("[data-history-tab]").forEach((button) =>
    button.addEventListener("click", () => switchHistoryTab(button.dataset.historyTab))
  );
  document.addEventListener("click", recordOpen);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeDrawers();
      closeReader();
    }
  });
  connectEvents();

  try {
    const payload = await api("/api/bootstrap");
    state.config = payload.config;
    state.latest = payload.latest;
    populateSettings(payload.config);
    updateHeaderDate(payload.config);
    if (payload.latest) {
      renderReport(payload.latest);
    } else {
      $("#welcome").hidden = false;
      setStatus(
        payload.config.enabled
          ? `等待首次生成 · 每日 ${payload.config.editionTime} 自动推送`
          : "定时推送当前已暂停"
      );
    }
    if (new URLSearchParams(window.location.search).get("view") === "history") {
      await openHistory();
    }
  } catch (error) {
    $("#welcome").hidden = false;
    setStatus(`无法读取本地配置：${error.message}`, "error");
  }
}

init();
