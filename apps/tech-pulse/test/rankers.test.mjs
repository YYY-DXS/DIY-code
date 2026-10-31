import test from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_CONFIG } from "../src/defaults.mjs";
import {
  buildReport,
  relevanceScore,
  scoreAndClassifyItems,
  titleTokens
} from "../src/ranker.mjs";
import {
  classifyItem,
  containsKeyword,
  parseRss,
  stripHtml
} from "../src/collectors.mjs";

const NOW = new Date("2026-10-31T00:00:00.000Z");

function item(overrides = {}) {
  return {
    id: Math.random().toString(36),
    kind: "rss",
    source: "Ars Technica",
    title: "A new AI chip changes edge computing",
    url: `https://example.com/${Math.random()}`,
    summary: "Hardware for local artificial intelligence.",
    publishedAt: "2026-10-30T20:00:00.000Z",
    tags: ["AI", "hardware"],
    metrics: {},
    authority: 0.9,
    ...overrides
  };
}

test("RSS parser extracts RSS and Atom metadata", () => {
  const xml = `<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title><![CDATA[ESP32 weather station]]></title>
        <link>https://example.com/esp32</link>
        <description><![CDATA[<p>Build a sensor &amp; display.</p>]]></description>
        <pubDate>Fri, 30 Oct 2026 20:00:00 GMT</pubDate>
        <category>Hardware</category>
      </item>
    </channel></rss>`;
  const [parsed] = parseRss(xml, "Test Feed", 0.8);
  assert.equal(parsed.title, "ESP32 weather station");
  assert.equal(parsed.summary, "Build a sensor & display.");
  assert.equal(parsed.tags[0], "Hardware");
  assert.equal(parsed.authority, 0.8);
});

test("HTML cleanup removes markup and decodes entities", () => {
  assert.equal(stripHtml("<b>A &amp; B</b>"), "A & B");
});

test("short keywords do not match fragments of unrelated words", () => {
  assert.equal(containsKeyword("Captain Picard", "AI"), false);
  assert.equal(containsKeyword("A new AI model", "AI"), true);
  assert.equal(containsKeyword("ESP32-C6 board", "ESP32"), true);
});

test("AI model news is not misclassified as a DIY project", () => {
  assert.equal(
    classifyItem(
      item({
        title: "AI model generates music",
        summary: "The new large model is available today.",
        tags: ["AI"]
      })
    ),
    "news"
  );
  assert.equal(
    classifyItem(
      item({
        title: "ESP32 weather station",
        summary: "Build this open source hardware project.",
        tags: ["microcontroller"]
      })
    ),
    "diy"
  );
  assert.equal(
    classifyItem(
      item({
        title: "The state of Apple gadgets",
        summary: "The most successful product maker experiments again.",
        tags: []
      })
    ),
    "news"
  );
});

test("interest matching prizes configured keywords", () => {
  const result = relevanceScore(
    item({ title: "ESP32 robot with Arduino control", summary: "Open source hardware" }),
    DEFAULT_CONFIG.keywords
  );
  assert.ok(result.value > 0.7);
  assert.ok(result.matches.includes("ESP32"));
  assert.ok(result.matches.includes("Arduino"));
  assert.ok(result.matches.includes("hardware"));
});

test("source-specific engagement keeps scores in a useful range", () => {
  const scored = scoreAndClassifyItems(
    [
      item({ kind: "hackerNews", metrics: { points: 900, comments: 250 } }),
      item({
        kind: "github",
        source: "GitHub",
        title: "esp32/robot-kit",
        tags: ["esp32", "arduino"],
        metrics: { stars: 1200, forks: 120, issues: 10 }
      })
    ],
    DEFAULT_CONFIG,
    NOW
  );
  assert.equal(scored.length, 2);
  for (const result of scored) {
    assert.ok(result.score > 0);
    assert.ok(result.score <= 100);
  }
  assert.equal(scored[0].category, "news");
  assert.equal(scored[1].category, "diy");
});

test("similar headlines add cross-source corroboration", () => {
  const scored = scoreAndClassifyItems(
    [
      item({ title: "OpenAI launches a new local robotics model" }),
      item({
        source: "The Verge",
        title: "OpenAI launches new local robotics model"
      })
    ],
    DEFAULT_CONFIG,
    NOW
  );
  assert.equal(scored[0].corroboratingSources.length, 2);
  assert.ok(scored[0].breakdown.corroboration > 0);
});

test("title tokenization supports Chinese headlines", () => {
  const tokens = titleTokens("高中生制作 ESP32 外骨骼");
  assert.ok(tokens.has("esp32"));
  assert.ok(tokens.has("外骨"));
});

test("report keeps source diversity and separates news from DIY", () => {
  const items = [
    item({ title: "Quantum computer reaches new milestone" }),
    item({ title: "New semiconductor factory announced" }),
    item({ title: "Space telescope finds distant world" }),
    item({ title: "A second chip company reports earnings" }),
    item({
      kind: "github",
      source: "GitHub",
      title: "pi/robot-arm",
      tags: ["raspberry-pi", "robotics"],
      metrics: { stars: 900, forks: 60 }
    }),
    item({
      kind: "bilibili",
      source: "B站",
      title: "自制 ESP32 机器人",
      tags: ["ESP32"],
      metrics: { views: 500_000, favorites: 2000 }
    })
  ];
  const report = buildReport({
    items,
    errors: [],
    config: { ...DEFAULT_CONFIG, maxNews: 3, maxDiy: 2 },
    durationMs: 1234,
    now: NOW
  });
  assert.equal(report.news.length, 3);
  assert.ok(report.news.every((entry) => entry.category === "news"));
  assert.equal(report.diy.length, 2);
  assert.ok(report.summary.includes("科技焦点"));
  assert.equal(report.date, "2026-10-31");
});
