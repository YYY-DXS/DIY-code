import test from "node:test";
import assert from "node:assert/strict";
import {
  enrichReportMedia,
  extractWebPageContent,
  isSafeMediaFilename
} from "../src/content.mjs";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

test("web page extraction captures metadata, paragraphs and a hero image", () => {
  const html = `
    <html>
      <head>
        <title>Fallback title</title>
        <meta property="og:title" content="A useful technology story" />
        <meta name="description" content="A concise page description." />
        <meta property="og:image" content="/images/hero.jpg" />
      </head>
      <body>
        <nav><p>Navigation text that should not be included in the article body.</p></nav>
        <article>
          <p>This is the first substantial paragraph from the web page and it contains useful context for the reader.</p>
          <p>This is the second substantial paragraph with more details about the project and its hardware.</p>
          <p>Short.</p>
        </article>
      </body>
    </html>`;
  const result = extractWebPageContent(html, "https://example.com/story");
  assert.equal(result.title, "A useful technology story");
  assert.equal(result.description, "A concise page description.");
  assert.equal(result.image, "https://example.com/images/hero.jpg");
  assert.match(result.content, /first substantial paragraph/);
  assert.match(result.content, /second substantial paragraph/);
  assert.doesNotMatch(result.content, /Navigation text/);
  assert.doesNotMatch(result.content, /Short/);
});

test("media route accepts only generated cache filenames", () => {
  assert.equal(isSafeMediaFilename("0123456789abcdef01234567.jpg"), true);
  assert.equal(isSafeMediaFilename("../secret.jpg"), false);
  assert.equal(isSafeMediaFilename("0123456789abcdef01234567.exe"), false);
});

test("cached page content remains readable when the external site is unavailable", async () => {
  const cacheDir = await mkdtemp(path.join(os.tmpdir(), "tech-pulse-content-"));
  const originalFetch = globalThis.fetch;
  const item = {
    id: "rss-cache-test",
    kind: "rss",
    source: "Example",
    title: "Offline cache test",
    url: "https://example.com/cache-test",
    summary: "Short source summary.",
    publishedAt: "2026-10-31T00:00:00.000Z",
    tags: [],
    thumbnail: ""
  };
  const report = { news: [item], diy: [] };
  try {
    globalThis.fetch = async () =>
      new Response(
        `<html><head><meta property="og:description" content="Cached description"></head>
          <body><article><p>This cached paragraph is long enough to survive extraction and be readable while offline for the reader.</p></article></body></html>`,
        { headers: { "Content-Type": "text/html; charset=utf-8" } }
      );
    await enrichReportMedia(report, cacheDir);

    globalThis.fetch = async () => {
      throw new Error("network unavailable");
    };
    const offline = await enrichReportMedia(report, cacheDir);
    assert.match(offline.news[0].content, /cached paragraph/);
    assert.equal(offline.news[0].pageDescription, "Cached description");
    assert.equal(offline.news[0].mediaOffline, true);
  } finally {
    globalThis.fetch = originalFetch;
    const expectedPrefix = path.join(os.tmpdir(), "tech-pulse-content-");
    assert.ok(cacheDir.startsWith(expectedPrefix));
    await rm(cacheDir, { recursive: true, force: true });
  }
});
