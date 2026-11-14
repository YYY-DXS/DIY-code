'use strict';
/* 高中思想政治 必修1-2 · 一框一页 A4 思维导图 —— 构建脚本
   版式沿用 Codex：米色纸面 + 金色点缀 + 左根节点 + 分支 + 底部结论 */

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const { renderPage, PW, PH, texts } = require('./mindlib.js');
const { pages, TOTAL, BOOK1, BOOK2 } = require('./content.js');
const { panels, extras } = require('./panels.js');

/* 合并易错/答题面板与补充细节 */
pages.forEach((p) => {
  const key = `${p.book === BOOK1 ? 'B1' : 'B2'}-${p.box}`;
  const pn = panels[key] || {};
  p.pitfalls = pn.pitfalls || [];
  p.answers = pn.answers || [];
  (extras[key] || []).forEach(([gi, text]) => {
    if (p.groups[gi]) p.groups[gi].items.push(text);
  });
});

const EDGE = process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const WORK = __dirname;
const PAGES_DIR = path.join(WORK, 'pages');
const OUT_DIR = path.join(WORK, 'output');
const PNG_DIR = path.join(OUT_DIR, 'png');
const PROFILE = path.join(WORK, '.edge-profile');

const FONT = "'Microsoft YaHei UI','Microsoft YaHei','PingFang SC',sans-serif";
const BG = '#FDFBF7';
const INK = '#2B2420';
const INK_SOFT = '#7A6F64';
const LINE = '#E3D9CB';
const GOLD = '#C9A227';

const esc = (s) =>
  String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const SHORT_LESSON = {
  '社会主义从空想到科学、从理论到实践的发展': '社会主义从空想到科学、从理论到实践',
  '只有坚持和发展中国特色社会主义才能实现中华民族伟大复兴':
    '只有坚持和发展中国特色社会主义',
};
function fitText(text, fs, maxW) {
  if (texts.textWidth(text, fs) <= maxW) return text;
  let s = text;
  while (s.length && texts.textWidth(s + '…', fs) > maxW) s = s.slice(0, -1);
  return s + '…';
}

const LESSONS = {
  [BOOK1]: [
    ['第一课', '社会主义从空想到科学、从理论到实践的发展', '3', '#8E3B2F'],
    ['第二课', '只有社会主义才能救中国', '5', '#B2352C'],
    ['第三课', '只有中国特色社会主义才能发展中国', '7', '#2F6BA0'],
    ['第四课', '只有坚持和发展中国特色社会主义才能实现中华民族伟大复兴', '9', '#7A4E9E'],
  ],
  [BOOK2]: [
    ['第一课', '我国的生产资料所有制', '11', '#1F6F5C'],
    ['第二课', '我国的社会主义市场经济体制', '13', '#2F6BA0'],
    ['第三课', '我国的经济发展', '15', '#A05A1E'],
    ['第四课', '我国的个人收入分配与社会保障', '17', '#B2352C'],
  ],
};

const COVER_ROWS = [
  ['01', '第一课', '社会主义从空想到科学、从理论到实践的发展', '1.1 原始社会的解体 · 1.2 科学社会主义', 'P.3', '#8E3B2F'],
  ['02', '第二课', '只有社会主义才能救中国', '2.1 新民主主义革命 · 2.2 社会主义制度确立', 'P.5', '#B2352C'],
  ['03', '第三课', '只有中国特色社会主义才能发展中国', '3.1 改革开放 · 3.2 创立发展完善', 'P.7', '#2F6BA0'],
  ['04', '第四课', '只有坚持和发展中国特色社会主义才能实现中华民族伟大复兴', '4.1 新时代 · 4.2 中国梦', 'P.9', '#7A4E9E'],
];
const COVER_ROWS2 = [
  ['05', '第一课', '我国的生产资料所有制', '1.1 公有制为主体 · 1.2 两个毫不动摇', 'P.11', '#1F6F5C'],
  ['06', '第二课', '我国的社会主义市场经济体制', '2.1 市场决定性作用 · 2.2 政府作用', 'P.13', '#2F6BA0'],
  ['07', '第三课', '我国的经济发展', '3.1 新发展理念 · 3.2 高质量发展', 'P.15', '#A05A1E'],
  ['08', '第四课', '我国的个人收入分配与社会保障', '4.1 收入分配 · 4.2 社会保障', 'P.17', '#B2352C'],
];

function defsCommon() {
  return (
    `<filter id="cg" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="60"/></filter>` +
    `<filter id="cs" x="-30%" y="-30%" width="160%" height="170%"><feDropShadow dx="0" dy="8" stdDeviation="14" flood-color="#5C2B18" flood-opacity="0.18"/></filter>` +
    `<pattern id="cd" width="30" height="30" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.2" fill="#DCCFBC" opacity="0.5"/></pattern>`
  );
}

/* ---------------- 封面 ---------------- */
function coverSvg() {
  const out = [];
  out.push(
    `<rect width="${PW}" height="${PH}" fill="${BG}"/>`,
    `<rect width="${PW}" height="${PH}" fill="url(#cd)"/>`,
    `<ellipse cx="${PW - 120}" cy="120" rx="620" ry="420" fill="#F1D9D4" opacity="0.8" filter="url(#cg)"/>`,
    `<ellipse cx="120" cy="${PH - 100}" rx="560" ry="380" fill="#DFE7F2" opacity="0.75" filter="url(#cg)"/>`,
    `<rect x="26" y="26" width="${PW - 52}" height="${PH - 52}" rx="24" fill="none" stroke="${LINE}" stroke-width="2.2"/>`,
    `<rect x="${PW / 2 - 60}" y="196" width="120" height="7" rx="3.5" fill="#A32126"/>`,
    `<text x="${PW / 2}" y="312" font-family="${FONT}" font-size="36" fill="${INK_SOFT}" text-anchor="middle" letter-spacing="10">高中思想政治 · 一框一页</text>`,
    `<text x="${PW / 2}" y="500" font-family="${FONT}" font-size="146" font-weight="700" fill="#A32126" text-anchor="middle" letter-spacing="8">政治思维导图</text>`,
    `<text x="${PW / 2}" y="600" font-family="${FONT}" font-size="42" fill="${INK}" text-anchor="middle" letter-spacing="3">必修1《中国特色社会主义》 × 必修2《经济与社会》</text>`,
    `<text x="${PW / 2}" y="668" font-family="${FONT}" font-size="27" fill="${INK_SOFT}" text-anchor="middle" letter-spacing="2">16 个框题 · 每个框题 1 页 A4 · 主干 + 细节 + 易错 + 结论</text>`,
    `<line x1="${PW / 2 - 540}" y1="716" x2="${PW / 2 + 540}" y2="716" stroke="${GOLD}" stroke-width="3"/>`
  );

  function bookCards(rows, startY, bookTag, bookColor) {
    let y = startY;
    out.push(
      `<rect x="230" y="${y}" width="102" height="52" rx="12" fill="${bookColor}"/>`,
      `<text x="281" y="${y + 38}" font-family="${FONT}" font-size="27" font-weight="700" fill="#FFFFFF" text-anchor="middle">${bookTag}</text>`,
      `<text x="352" y="${y + 38}" font-family="${FONT}" font-size="30" font-weight="700" fill="${INK}">${
        bookTag === '必修1' ? '中国特色社会主义' : '经济与社会'
      }　·　每课两框，共 8 页</text>`
    );
    y += 74;
    rows.forEach(([idx, tag, title, sub, pg, color]) => {
      out.push(
        `<rect x="230" y="${y}" width="${PW - 460}" height="176" rx="18" fill="#FFFFFF" stroke="${LINE}" stroke-width="1.5" filter="url(#cs)"/>`,
        `<rect x="230" y="${y}" width="9" height="176" rx="4.5" fill="${color}"/>`,
        `<rect x="268" y="${y + 42}" width="92" height="92" rx="18" fill="${color}"/>`,
        `<text x="314" y="${y + 103}" font-family="${FONT}" font-size="38" font-weight="700" fill="#FFFFFF" text-anchor="middle">${idx}</text>`,
        `<text x="392" y="${y + 62}" font-family="${FONT}" font-size="26" font-weight="700" fill="${color}" letter-spacing="2">${tag}</text>`,
        `<text x="392" y="${y + 108}" font-family="${FONT}" font-size="34" font-weight="700" fill="${INK}">${esc(title)}</text>`,
        `<text x="392" y="${y + 148}" font-family="${FONT}" font-size="23" fill="${INK_SOFT}">${esc(sub)}</text>`,
        `<text x="${PW - 268}" y="${y + 108}" font-family="${FONT}" font-size="26" fill="${color}" text-anchor="end" font-weight="700">${pg}</text>`
      );
      y += 202;
    });
    return y;
  }

  let y1 = bookCards(COVER_ROWS, 790, '必修1', '#8E3B2F');
  let y2 = bookCards(COVER_ROWS2, y1 + 26, '必修2', '#1F6F5C');

  const boxY = y2 + 34;
  out.push(
    `<rect x="230" y="${boxY}" width="${PW - 460}" height="252" rx="18" fill="#FFFFFF" stroke="${LINE}" stroke-width="1.5"/>`,
    `<text x="272" y="${boxY + 54}" font-family="${FONT}" font-size="27" font-weight="700" fill="#8E3B2F" letter-spacing="3">使用说明</text>`,
    `<line x1="272" y1="${boxY + 74}" x2="${PW - 272}" y2="${boxY + 74}" stroke="${LINE}" stroke-width="1.5"/>`,
    `<text x="272" y="${boxY + 122}" font-family="${FONT}" font-size="25" fill="${INK}">① 一框一页：先看左侧根节点把握本框主线，再沿中间分支读右侧细节。</text>`,
    `<text x="272" y="${boxY + 172}" font-family="${FONT}" font-size="25" fill="${INK}">② “★”为高频考点；粉底“※”为易错提醒；底部“本框结论”用于背诵定位。</text>`,
    `<text x="272" y="${boxY + 222}" font-family="${FONT}" font-size="25" fill="${INK}">③ 必修1按社会形态、革命、改革、新时代推进；必修2按所有制、市场、发展、分配展开。</text>`,
    `<line x1="${PW / 2 - 190}" y1="3020" x2="${PW / 2 + 190}" y2="3020" stroke="${GOLD}" stroke-width="2"/>`,
    `<text x="${PW / 2}" y="3104" font-family="${FONT}" font-size="44" font-weight="700" fill="#A32126" text-anchor="middle" letter-spacing="6">把书读薄</text>`,
    `<text x="${PW / 2}" y="3164" font-family="${FONT}" font-size="44" font-weight="700" fill="#A32126" text-anchor="middle" letter-spacing="6">把理读透</text>`,
    `<text x="${PW / 2}" y="3244" font-family="${FONT}" font-size="24" fill="${INK_SOFT}" text-anchor="middle" letter-spacing="3">主干成线 · 细节成块 · 易错成点</text>`,
    `<line x1="${PW / 2 - 190}" y1="3298" x2="${PW / 2 + 190}" y2="3298" stroke="${GOLD}" stroke-width="2"/>`,
    `<text x="${PW / 2}" y="${PH - 92}" font-family="${FONT}" font-size="23" fill="${INK_SOFT}" text-anchor="middle">共 ${TOTAL} 页 · A4 210×297mm · 300dpi · 可直接双面打印</text>`
  );

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${PW}" height="${PH}" viewBox="0 0 ${PW} ${PH}"><defs>${defsCommon()}</defs>${out.join(
    ''
  )}</svg>`;
}

/* ---------------- 目录 ---------------- */
function tocSvg() {
  const out = [];
  out.push(
    `<rect width="${PW}" height="${PH}" fill="${BG}"/>`,
    `<rect width="${PW}" height="${PH}" fill="url(#cd)"/>`,
    `<rect x="26" y="26" width="${PW - 52}" height="${PH - 52}" rx="24" fill="none" stroke="${LINE}" stroke-width="2.2"/>`,
    `<rect x="110" y="92" width="152" height="62" rx="15" fill="#A32126"/>`,
    `<text x="186" y="136" font-family="${FONT}" font-size="32" font-weight="700" fill="#FFFFFF" text-anchor="middle">目录</text>`,
    `<text x="292" y="141" font-family="${FONT}" font-size="45" font-weight="700" fill="${INK}">全册知识地图 · 16 个框题</text>`,
    `<text x="112" y="200" font-family="${FONT}" font-size="22" fill="${INK_SOFT}">必修1《中国特色社会主义》 第 3—10 页　·　必修2《经济与社会》 第 11—18 页</text>`,
    `<line x1="110" y1="228" x2="${PW - 110}" y2="228" stroke="${LINE}" stroke-width="2.4"/>`
  );

  const cols = [
    { x: 110, book: BOOK1, color: '#8E3B2F' },
    { x: 1270, book: BOOK2, color: '#1F6F5C' },
  ];
  cols.forEach((col) => {
    let y = 292;
    out.push(
      `<rect x="${col.x}" y="${y}" width="1100" height="66" rx="12" fill="${col.color}"/>`,
      `<text x="${col.x + 28}" y="${y + 44}" font-family="${FONT}" font-size="28" font-weight="700" fill="#FFFFFF">${col.book}　·　4 课 8 框</text>`
    );
    y += 92;
    const rows = pages.filter((p) => p.book === col.book);
    rows.forEach((p, i) => {
      const rh = 300;
      out.push(
        `<rect x="${col.x}" y="${y}" width="1100" height="${rh - 16}" rx="14" fill="#FFFFFF" stroke="${LINE}" stroke-width="1.3"/>`,
        `<rect x="${col.x}" y="${y}" width="7" height="${rh - 16}" rx="3.5" fill="${p.accent}"/>`,
        `<rect x="${col.x + 26}" y="${y + 64}" width="112" height="70" rx="14" fill="${p.accent}"/>`,
        `<text x="${col.x + 82}" y="${y + 111}" font-family="${FONT}" font-size="31" font-weight="700" fill="#FFFFFF" text-anchor="middle">${p.box}</text>`,
        `<text x="${col.x + 166}" y="${y + 92}" font-family="${FONT}" font-size="22" fill="${INK_SOFT}">${
          p.lesson
        } · ${esc(fitText(SHORT_LESSON[p.lessonTitle] || p.lessonTitle, 22, 800))}</text>`,
        `<text x="${col.x + 166}" y="${y + 150}" font-family="${FONT}" font-size="32" font-weight="700" fill="${INK}">${esc(
          fitText(p.title, 32, 640)
        )}</text>`,
        `<text x="${col.x + 166}" y="${y + 198}" font-family="${FONT}" font-size="21" fill="${INK_SOFT}">${esc(
          fitText(p.focus.split(' · ').slice(0, 3).join(' · '), 21, 800)
        )}</text>`,
        `<line x1="${col.x + 820}" y1="${y + 150}" x2="${col.x + 990}" y2="${y + 150}" stroke="${LINE}" stroke-width="1.5" stroke-dasharray="3 5"/>`,
        `<text x="${col.x + 1052}" y="${y + 162}" font-family="${FONT}" font-size="40" font-weight="700" fill="${p.accent}" text-anchor="end">P.${p.pageNo}</text>`
      );
      y += rh;
    });
  });

  out.push(
    `<rect x="110" y="2846" width="${PW - 220}" height="330" rx="18" fill="#FFFFFF" stroke="${LINE}" stroke-width="1.5"/>`,
    `<text x="152" y="2900" font-family="${FONT}" font-size="27" font-weight="700" fill="#8E3B2F" letter-spacing="3">复习路线</text>`,
    `<line x1="152" y1="2922" x2="${PW - 152}" y2="2922" stroke="${LINE}" stroke-width="1.5"/>`,
    `<text x="152" y="2972" font-family="${FONT}" font-size="24" fill="${INK}">必修1主线：原始社会→阶级社会→科学社会主义→新民主主义革命→社会主义制度→改革开放→新时代→中国梦</text>`,
    `<text x="152" y="3022" font-family="${FONT}" font-size="24" fill="${INK}">必修2主线：生产资料所有制→社会主义市场经济体制→新发展理念与高质量发展→收入分配与社会保障</text>`,
    `<text x="152" y="3072" font-family="${FONT}" font-size="24" fill="${INK}">建议：每天 1 框，先默写分支标题，再补细节；周末用目录页串成整册框架。</text>`,
    `<text x="152" y="3128" font-family="${FONT}" font-size="21" fill="${INK_SOFT}">页码即打印顺序；每页页脚标注“框号 · 第几页”，便于抽背时快速定位。</text>`
  );

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${PW}" height="${PH}" viewBox="0 0 ${PW} ${PH}"><defs>${defsCommon()}</defs>${out.join(
    ''
  )}</svg>`;
}

/* ---------------- 自动适配字号 ---------------- */
const fit = pages.map((p) => {
  let k = 1;
  let r = renderPage(p, k);
  let guard = 0;
  while ((r.contentH > r.availH || r.panelH > 380) && k > 0.72 && guard++ < 40) {
    k = Math.round((k - 0.01) * 100) / 100;
    r = renderPage(p, k);
  }
  return { pageNo: p.pageNo, box: p.box, k, contentH: r.contentH, availH: r.availH, panelH: r.panelH };
});
const K = Math.min(...fit.map((f) => f.k), 1);

const svgs = [coverSvg(), tocSvg(), ...pages.map((p) => renderPage(p, K).svg)];
const names = [
  '01-封面',
  '02-目录',
  ...pages.map((p) => `P${p.pageNo}-必修${p.book.includes('必修1') ? 1 : 2}-${p.lesson}-${p.box}-${p.title}`),
];

/* ---------------- 写 HTML ---------------- */
fs.mkdirSync(PAGES_DIR, { recursive: true });
fs.mkdirSync(PNG_DIR, { recursive: true });

const htmlFor = (svg) =>
  '<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;padding:0;background:#FDFBF7;overflow:hidden}svg{display:block}</style></head><body>' +
  svg +
  '</body></html>';

const pageFiles = svgs.map((svg, i) => {
  const f = path.join(PAGES_DIR, `page${String(i + 1).padStart(2, '0')}.html`);
  fs.writeFileSync(f, htmlFor(svg), 'utf8');
  return f;
});

const printHtml =
  [
    '<!doctype html><html><head><meta charset="utf-8"><style>',
    '@page{size:210mm 297mm;margin:0}',
    'html,body{margin:0;padding:0;background:#fff}',
    '.page{width:210mm;height:296.6mm;overflow:hidden}',
    '.page + .page{page-break-before:always}',
    '.page svg{width:210mm;height:297mm;display:block}',
    '</style></head><body>',
    ...svgs.map((s) => `<div class="page">${s}</div>`),
    '</body></html>',
  ].join('\n');
const printPath = path.join(WORK, 'print-all.html');
fs.writeFileSync(printPath, printHtml, 'utf8');

function printSubset(list, name) {
  const h = printHtml.replace(
    /<body>[\s\S]*<\/body>/,
    '<body>' + list.map((s) => `<div class="page">${s}</div>`).join('') + '</body>'
  );
  const f = path.join(WORK, name);
  fs.writeFileSync(f, h, 'utf8');
  return f;
}
const printB1 = printSubset(svgs.slice(2, 10), 'print-b1.html');
const printB2 = printSubset(svgs.slice(10, 18), 'print-b2.html');

/* ---------------- 调 Edge 渲染 ---------------- */
function runEdge(args) {
  const r = spawnSync(EDGE, args, { stdio: 'ignore', timeout: 120000 });
  if (r.error) throw r.error;
}
const URL = (f) => 'file:///' + f.replace(/\\/g, '/').replace(/#/g, '%23');

async function main() {
  const only = process.argv.includes('--fit');
  console.log(
    'FIT ' +
      JSON.stringify(
        { K, fit: fit.map((f) => ({ box: f.box, k: f.k, h: Math.round(f.contentH), avail: Math.round(f.availH) })) },
        null,
        0
      )
  );
  if (only) return;

  const pngs = [];
  svgs.forEach((_, i) => {
    const out = path.join(PNG_DIR, `${names[i]}.png`);
    runEdge([
      '--headless=new',
      '--disable-gpu',
      '--no-first-run',
      '--no-default-browser-check',
      `--user-data-dir=${PROFILE}`,
      '--hide-scrollbars',
      '--force-device-scale-factor=1',
      '--window-size=2480,3508',
      `--screenshot=${out}`,
      URL(pageFiles[i]),
    ]);
    if (!fs.existsSync(out)) throw new Error('截图失败: ' + out);
    pngs.push(out);
    console.log(`PNG ${i + 1}/${svgs.length} ${path.basename(out)}`);
  });

  const pdfs = [];
  const pdfJobs = [
    [printPath, '政治必修1-2思维导图-一框一页-A4.pdf'],
    [printB1, '政治必修1-思维导图-一框一页-A4.pdf'],
    [printB2, '政治必修2-思维导图-一框一页-A4.pdf'],
  ];
  for (const [html, name] of pdfJobs) {
    const out = path.join(OUT_DIR, name);
    runEdge([
      '--headless=new',
      '--disable-gpu',
      '--no-first-run',
      '--no-default-browser-check',
      `--user-data-dir=${PROFILE}`,
      '--no-pdf-header-footer',
      `--print-to-pdf=${out}`,
      URL(html),
    ]);
    if (!fs.existsSync(out)) throw new Error('PDF 失败: ' + out);
    pdfs.push(out);
    console.log('PDF ' + path.basename(out));
  }

  fs.writeFileSync(
    path.join(OUT_DIR, '文件说明.txt'),
    [
      '高中思想政治 必修1-2 思维导图（一框一页 A4）',
      '',
      '1. 政治必修1-2思维导图-一框一页-A4.pdf —— 全册 18 页（封面 + 目录 + 16 框）',
      '2. 政治必修1-思维导图-一框一页-A4.pdf —— 必修1 8 框',
      '3. 政治必修2-思维导图-一框一页-A4.pdf —— 必修2 8 框',
      '4. png/ —— 18 张 2480×3508（300dpi）单页图片',
      '',
      '版式：米色纸面、左根节点、中间分支、右侧细节、底部本框结论；',
      '“★”为高频考点，粉底“※”为易错提醒。',
      '',
      `生成时间：${new Date().toLocaleString('zh-CN')}`,
    ].join('\r\n'),
    'utf8'
  );

  console.log('DONE ' + JSON.stringify({ pdfs, pngs: pngs.length }, null, 0));
}

main().catch((e) => {
  console.error('FAIL ' + e.message);
  process.exit(1);
});
