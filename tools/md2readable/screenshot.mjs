/*
 * 用系统里的 Edge 把生成的 HTML 截成图片，用于检查排版。
 *
 *   node screenshot.mjs [输出目录]
 */

import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

// 依赖装在 Codex 的运行时目录里，ESM 不认 NODE_PATH，所以显式定位
const depsModules =
  process.env.CODEX_NODE_MODULES ||
  path.join(
    process.env.USERPROFILE || '',
    '.cache',
    'codex-runtimes',
    'codex-primary-runtime',
    'dependencies',
    'node',
    'node_modules'
  );
const require = createRequire(path.join(depsModules, 'noop.js'));
const { chromium } = require('playwright');

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '..', '..');
const projects = path.join(repo, 'projects');
const outDir = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.join(repo, '.preview');

fs.mkdirSync(outDir, { recursive: true });

function collectHtml(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return collectHtml(full);
    return entry.name.toLowerCase().endsWith('.html') ? [full] : [];
  });
}

const files = collectHtml(projects);
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 900, height: 1200 } });

for (const file of files) {
  await page.goto(pathToFileURL(file).href, { waitUntil: 'load' });
  const name = path
    .relative(projects, file)
    .replace(/\\/g, '_')
    .replace(/\.html$/i, '.png');
  await page.screenshot({ path: path.join(outDir, name), fullPage: true });
  console.log('  截图：' + name);
}

await browser.close();
console.log(`\n共 ${files.length} 张，输出目录：${outDir}`);
