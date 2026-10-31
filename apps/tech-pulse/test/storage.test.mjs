import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { Store } from "../src/storage.mjs";

test("view history increments repeat visits and preserves first view time", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "tech-pulse-history-"));
  try {
    const store = new Store(root);
    await store.init();
    const entry = {
      id: "github-example",
      title: "ESP32 desk lamp",
      url: "https://github.com/example/esp32-lamp",
      source: "GitHub",
      category: "diy",
      publishedAt: "2026-10-30T00:00:00.000Z",
      reportDate: "2026-10-31",
      viewedDate: "2026-10-31"
    };
    await store.recordView(entry);
    const secondEntry = {
      ...entry,
      title: "ESP32 desk lamp v2",
      viewedDate: "2026-11-01",
      reportDate: "2026-11-01"
    };
    await store.recordView(secondEntry);
    const history = await store.getViewHistory();
    assert.equal(history.records.length, 1);
    assert.equal(history.records[0].viewCount, 2);
    assert.equal(history.records[0].title, "ESP32 desk lamp v2");
    assert.deepEqual(history.records[0].dailyCounts, {
      "2026-10-31": 1,
      "2026-11-01": 1
    });
    assert.ok(history.records[0].firstViewedAt);
    assert.ok(history.records[0].lastViewedAt);
  } finally {
    const expectedPrefix = path.join(os.tmpdir(), "tech-pulse-history-");
    assert.ok(root.startsWith(expectedPrefix));
    await rm(root, { recursive: true, force: true });
  }
});
