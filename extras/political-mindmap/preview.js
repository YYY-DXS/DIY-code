'use strict';
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const { renderPage } = require('./mindlib.js');
const { pages, BOOK1 } = require('./content.js');
const { panels, extras } = require('./panels.js');

pages.forEach((p) => {
  const key = `${p.book === BOOK1 ? 'B1' : 'B2'}-${p.box}`;
  const pn = panels[key] || {};
  p.pitfalls = pn.pitfalls || [];
  p.answers = pn.answers || [];
  (extras[key] || []).forEach(([gi, text]) => {
    if (p.groups[gi]) p.groups[gi].items.push(text);
  });
});

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const idx = Number(process.argv[2] || 0);
const k = Number(process.argv[3] || 1);
const p = pages[idx];
if (!p) throw new Error('no page ' + idx);
const r = renderPage(p, k);
const html =
  '<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;padding:0;background:#FDFBF7;overflow:hidden}svg{display:block}</style></head><body>' +
  r.svg +
  '</body></html>';
fs.writeFileSync(path.join(__dirname, 'preview.html'), html, 'utf8');
spawnSync(
  EDGE,
  [
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    `--user-data-dir=${path.join(__dirname, '.edge-profile')}`,
    '--hide-scrollbars',
    '--force-device-scale-factor=1',
    '--window-size=2480,3508',
    `--screenshot=${path.join(__dirname, 'preview.png')}`,
    'file:///' + path.join(__dirname, 'preview.html').replace(/\\/g, '/'),
  ],
  { stdio: 'ignore', timeout: 120000 }
);
console.log(JSON.stringify({ box: p.box, k, contentH: Math.round(r.contentH), availH: Math.round(r.availH), panelH: Math.round(r.panelH) }));
