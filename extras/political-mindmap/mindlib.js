'use strict';
/* 高中思想政治 必修1-2 思维导图 —— 一框一页 A4 渲染内核
   设计坐标 2480×3508（A4 / 300dpi），沿用 Codex 版式：
   左侧根节点 → 中间分支 → 右侧细节 → 底部本框结论 */

const NO_START = '，。、；：！？）》」』”’…％·';
function charW(ch) {
  const c = ch.codePointAt(0);
  if (c >= 0x2e80 && c <= 0x9fff) return 1.0;
  if (c >= 0xf900 && c <= 0xfaff) return 1.0;
  if (c >= 0xfe30 && c <= 0xfe4f) return 1.0;
  if (c >= 0xff00 && c <= 0xffef) return 1.0;
  if (c >= 0x2000 && c <= 0x2bff) return 1.0;
  if (c >= 0x1f300) return 1.25;
  if (ch === ' ') return 0.34;
  if (ch >= 'A' && ch <= 'Z') return 0.68;
  if (ch >= 'a' && ch <= 'z') return 0.56;
  if (ch >= '0' && ch <= '9') return 0.56;
  return 0.45;
}
function wrapLine(text, maxW, fs) {
  const chars = Array.from(text);
  const out = [];
  let cur = '';
  let w = 0;
  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i];
    const cw = charW(ch) * fs;
    if (cur !== '' && w + cw > maxW) {
      let k = i;
      let extra = '';
      while (
        k < chars.length &&
        NO_START.includes(chars[k]) &&
        w + charW(chars[k]) * fs <= maxW + fs * 2
      ) {
        extra += chars[k];
        k++;
      }
      out.push(cur + extra);
      cur = '';
      w = 0;
      i = k - 1;
      continue;
    }
    cur += ch;
    w += cw;
  }
  if (cur !== '') out.push(cur);
  return out.length ? out : [''];
}
function measure(text, maxW, fs) {
  const lines = [];
  for (const seg of String(text).split('\n')) {
    if (seg.trim() === '') {
      lines.push('');
      continue;
    }
    lines.push(...wrapLine(seg, maxW, fs));
  }
  return lines;
}
const esc = (s) =>
  String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function textWidth(str, fs) {
  let w = 0;
  for (const ch of String(str)) w += charW(ch) * fs;
  return w;
}

function hex2rgb(h) {
  const s = h.replace('#', '');
  return [
    parseInt(s.slice(0, 2), 16),
    parseInt(s.slice(2, 4), 16),
    parseInt(s.slice(4, 6), 16),
  ];
}
function mix(a, b, t) {
  const A = hex2rgb(a);
  const B = hex2rgb(b);
  const c = A.map((v, i) => Math.round(v + (B[i] - v) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}
const tint = (c, t) => mix('#FFFFFF', c, t);
const shade = (c, t) => mix('#000000', c, t);

const PW = 2480;
const PH = 3508;
const MX = 110;
const MAP_TOP = 302;
const MAP_BOTTOM = 3206;
const PANEL_BOTTOM = 3208;
const P_LEFT_W = 1180;
const P_RIGHT_W = 1040;
const P_GAP = 40;
const CONCL_Y = 3240;
const CONCL_H = 86;

const FONT = "'Microsoft YaHei UI','Microsoft YaHei','PingFang SC',sans-serif";
const BG = '#FDFBF7';
const INK = '#2B2420';
const INK_SOFT = '#7A6F64';
const LINE = '#E3D9CB';
const GOLD = '#C9A227';

const COL = { rootW: 300, gap: 52, groupW: 300 };
const X_ROOT = MX;
const X_GROUP = X_ROOT + COL.rootW + COL.gap;
const X_LEAF = X_GROUP + COL.groupW + COL.gap;
const LEAF_W = PW - MX - X_LEAF;

function specs(k) {
  return {
    root: { fs: 32 * k, lh: 44 * k, padX: 20 },
    group: {
      fs: 26 * k,
      lh: 35 * k,
      padX: 16,
      padY: 14 * k,
      minH: 62 * k,
      r: 14,
    },
    leaf: {
      fs: 32 * k,
      lh: 40 * k,
      padX: 22,
      padY: 13 * k,
      minH: 66 * k,
      bullet: 16,
      r: 11,
    },
    leafGap: 9 * k,
    groupGap: 26 * k,
  };
}

function makeLeaf(text, color, S) {
  const s = S.leaf;
  const lines = measure(text, LEAF_W - s.padX * 2 - s.bullet, s.fs);
  return {
    kind: 'leaf',
    text,
    lines,
    w: LEAF_W,
    h: Math.max(s.minH, lines.length * s.lh + s.padY * 2),
    color,
    warn: /^\s*※/.test(String(text)),
  };
}
function makeGroup(g, S) {
  const s = S.group;
  const lines = measure(g.label, COL.groupW - s.padX * 2, s.fs);
  const node = {
    kind: 'group',
    text: g.label,
    lines,
    w: COL.groupW,
    h: Math.max(s.minH, lines.length * s.lh + s.padY * 2),
    color: g.color,
    timeline: !!g.timeline,
    star: !!g.star,
  };
  node.children = g.items.map((t) => makeLeaf(t, g.color, S));
  return node;
}
function place(node, cursor, S) {
  if (!node.children || !node.children.length) {
    node.cy = cursor.v + node.h / 2;
    cursor.v += node.h + S.leafGap;
    return;
  }
  node.children.forEach((c) => place(c, cursor, S));
  node.cy =
    (node.children[0].cy + node.children[node.children.length - 1].cy) / 2;
}
function walk(node, fn) {
  fn(node);
  if (node.children) node.children.forEach((c) => walk(c, fn));
}

function renderPage(cfg, k) {
  const S = specs(k);
  const rootH = 64 + cfg.root.lines.length * S.root.lh + 52;
  const groups = cfg.groups.map((g) => makeGroup(g, S));

  /* ---------- 底部易错 / 答题面板 ---------- */
  const pFs = 23 * k;
  const pLh = 32 * k;
  const pLeftX = MX;
  const pRightX = MX + P_LEFT_W + P_GAP;
  function buildPanel(title, items, w, color) {
    const padX = 28;
    const textW = w - padX * 2 - 18;
    const itemLines = (items || []).map((t, i) => {
      const prefix = '①②③④⑤'[i] || `${i + 1}.`;
      return measure(prefix + ' ' + t, textW, pFs);
    });
    const bodyH =
      itemLines.reduce((a, l) => a + l.length * pLh, 0) +
      Math.max(0, itemLines.length - 1) * 7 * k;
    return { title, itemLines, w, color, h: 100 * k + bodyH, padX };
  }
  const panelL = buildPanel('易混易错', cfg.pitfalls, P_LEFT_W, '#B2352C');
  const panelR = buildPanel('答题模板', cfg.answers, P_RIGHT_W, cfg.accent);
  const panelH = Math.max(panelL.h, panelR.h, 190 * k);
  const panelTop = PANEL_BOTTOM - panelH;
  const mapBottom = panelTop - 22;
  const mapH = mapBottom - MAP_TOP;

  const cursor = { v: 0 };
  groups.forEach((g, i) => {
    if (i > 0) cursor.v += S.groupGap * (cfg.groups[i].divider ? 1.9 : 1);
    place(g, cursor, S);
  });
  const contentH = cursor.v - S.leafGap;
  const y0 = MAP_TOP + Math.max(0, (mapH - contentH) / 2);
  groups.forEach((g) => walk(g, (n) => (n.cy += y0)));
  const bodyCY = y0 + contentH / 2;

  const out = [];
  const defs = [];
  const colors = new Set([GOLD, cfg.accent]);
  cfg.groups.forEach((g) => colors.add(g.color));
  colors.forEach((c) => {
    const id = 'g' + c.replace('#', '');
    defs.push(
      `<linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1">` +
        `<stop offset="0" stop-color="${mix(c, '#FFFFFF', 0.12)}"/>` +
        `<stop offset="1" stop-color="${shade(c, 0.24)}"/></linearGradient>`
    );
  });
  defs.push(
    `<filter id="sh" x="-25%" y="-25%" width="150%" height="160%">` +
      `<feDropShadow dx="0" dy="3" stdDeviation="5" flood-color="#7A5C3E" flood-opacity="0.13"/></filter>`,
    `<filter id="shR" x="-25%" y="-25%" width="150%" height="170%">` +
      `<feDropShadow dx="0" dy="6" stdDeviation="11" flood-color="#5C2B18" flood-opacity="0.28"/></filter>`
  );

  /* ---------- 页眉 ---------- */
  const chipW = 152;
  out.push(
    `<rect x="${MX}" y="88" width="${chipW}" height="62" rx="15" fill="${cfg.accent}"/>`,
    `<text x="${MX + chipW / 2}" y="132" font-family="${FONT}" font-size="32" font-weight="700" fill="#FFFFFF" text-anchor="middle">${esc(
      cfg.lesson
    )}</text>`,
    `<text x="${MX + chipW + 30}" y="137" font-family="${FONT}" font-size="45" font-weight="700" fill="${INK}">${esc(
      cfg.lessonTitle
    )}</text>`,
    `<text x="${MX + 2}" y="192" font-family="${FONT}" font-size="22" fill="${INK_SOFT}">${esc(
      cfg.book
    )} · 一框一页知识详解</text>`,
    `<text x="${MX + 2}" y="252" font-family="${FONT}" font-size="33" font-weight="700" fill="${shade(
      cfg.accent,
      0.06
    )}">${esc(cfg.box)}　${esc(cfg.title)}</text>`
  );
  if (cfg.focus) {
    const fLines = measure(cfg.focus, 640, 22);
    const fw = Math.min(
      980,
      Math.max(...fLines.map((l) => textWidth(l, 22))) + 74
    );
    const fx = PW - MX - fw;
    out.push(
      `<rect x="${fx}" y="206" width="${fw}" height="48" rx="24" fill="${tint(
        cfg.accent,
        0.1
      )}" stroke="${mix(cfg.accent, '#FFFFFF', 0.55)}" stroke-width="1.6"/>`,
      `<circle cx="${fx + 26}" cy="230" r="5" fill="${cfg.accent}"/>`,
      `<text x="${fx + 44}" y="238" font-family="${FONT}" font-size="22" fill="${shade(
        cfg.accent,
        0.25
      )}">${esc(cfg.focus)}</text>`
    );
  }
  out.push(
    `<line x1="${MX}" y1="282" x2="${PW - MX}" y2="282" stroke="${LINE}" stroke-width="2.4"/>`
  );

  /* ---------- 连线 ---------- */
  const curve = (x1, y1, x2, y2, color, w) => {
    const dx = (x2 - x1) * 0.55;
    return `<path d="M${x1.toFixed(1)},${y1.toFixed(1)} C${(x1 + dx).toFixed(
      1
    )},${y1.toFixed(1)} ${(x2 - dx).toFixed(1)},${y2.toFixed(1)} ${x2.toFixed(
      1
    )},${y2.toFixed(1)}" fill="none" stroke="${color}" stroke-width="${w}" stroke-linecap="round" opacity="0.5"/>`;
  };
  function edges(node, x) {
    if (!node.children) return;
    const childX = x === X_ROOT ? X_GROUP : X_LEAF;
    node.children.forEach((c) => {
      const px = x + node.w;
      if (node.timeline) {
        const railX = childX - 22;
        const first = node.children[0];
        const last = node.children[node.children.length - 1];
        out.push(
          `<path d="M${railX},${first.cy.toFixed(1)} L${railX},${last.cy.toFixed(
            1
          )}" stroke="${node.color}" stroke-width="3" opacity="0.45" stroke-linecap="round"/>`,
          curve(px, node.cy, railX, (first.cy + last.cy) / 2, node.color, 3)
        );
        node.children.forEach((n) =>
          out.push(
            `<path d="M${railX},${n.cy.toFixed(1)} L${childX},${n.cy.toFixed(
              1
            )}" stroke="${node.color}" stroke-width="2.4" opacity="0.45"/>`,
            `<circle cx="${railX}" cy="${n.cy.toFixed(
              1
            )}" r="6" fill="${node.color}"/>`,
            `<circle cx="${railX}" cy="${n.cy.toFixed(
              1
            )}" r="12" fill="none" stroke="${node.color}" stroke-width="1.8" opacity="0.28"/>`
          )
        );
      } else {
        out.push(curve(px, node.cy, childX, c.cy, node.color, 2.6));
      }
      edges(c, childX);
    });
  }

  /* ---------- 节点 ---------- */
  function renderLines(node, s, x, y, fill, weight, anchor) {
    const total = node.lines.length * s.lh;
    const top = y - total / 2;
    return node.lines
      .map((ln, i) => {
        if (ln === '') return '';
        const by = top + s.lh * (i + 0.5) + s.fs * 0.355;
        return `<text x="${x}" y="${by.toFixed(
          1
        )}" font-family="${FONT}" font-size="${s.fs.toFixed(
          2
        )}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}" xml:space="preserve">${esc(
          ln
        )}</text>`;
      })
      .join('');
  }
  function nodes(node, x) {
    const y = node.cy - node.h / 2;
    if (node.kind === 'root') {
      const top = node.cy - rootH / 2;
      out.push(
        `<rect x="${x}" y="${top}" width="${COL.rootW}" height="${rootH}" rx="22" fill="url(#g${cfg.accent.replace(
          '#',
          ''
        )})" stroke="${GOLD}" stroke-width="2.6" filter="url(#shR)"/>`,
        `<text x="${x + COL.rootW / 2}" y="${(
          top + 46
        ).toFixed(1)}" font-family="${FONT}" font-size="${(
          22 * k
        ).toFixed(1)}" font-weight="700" fill="${mix(
          GOLD,
          '#FFFFFF',
          0.4
        )}" text-anchor="middle" letter-spacing="6">${esc(cfg.root.tag)}</text>`,
        `<line x1="${x + 44}" y1="${(top + 66).toFixed(1)}" x2="${
          x + COL.rootW - 44
        }" y2="${(top + 66).toFixed(1)}" stroke="${mix(
          GOLD,
          '#FFFFFF',
          0.15
        )}" stroke-width="1.8" opacity="0.8"/>`
      );
      const startY = top + 66 + S.root.lh * 0.9;
      cfg.root.lines.forEach((ln, i) =>
        out.push(
          `<text x="${x + COL.rootW / 2}" y="${(
            startY +
            i * S.root.lh
          ).toFixed(1)}" font-family="${FONT}" font-size="${S.root.fs.toFixed(
            1
          )}" font-weight="700" fill="#FFFFFF" text-anchor="middle">${esc(ln)}</text>`
        )
      );
      out.push(
        `<text x="${x + COL.rootW / 2}" y="${(
          top + rootH - 26
        ).toFixed(1)}" font-family="${FONT}" font-size="${(
          18 * k
        ).toFixed(1)}" fill="${mix(
          GOLD,
          '#FFFFFF',
          0.52
        )}" text-anchor="middle" letter-spacing="1.5">${esc(cfg.root.note)}</text>`
      );
    } else if (node.kind === 'group') {
      out.push(
        `<rect x="${x}" y="${y}" width="${node.w}" height="${
          node.h
        }" rx="${S.group.r}" fill="${tint(
          node.color,
          0.14
        )}" stroke="${node.color}" stroke-width="2.2"/>`,
        `<rect x="${x}" y="${y + 9}" width="6.5" height="${
          node.h - 18
        }" rx="3.25" fill="${node.color}"/>`,
        renderLines(
          node,
          S.group,
          x + S.group.padX + 5,
          node.cy,
          shade(node.color, 0.3),
          700,
          'start'
        )
      );
      if (node.star)
        out.push(
          `<text x="${x + node.w - 18}" y="${(y + 26).toFixed(
            1
          )}" font-family="${FONT}" font-size="${(19 * k).toFixed(
            1
          )}" fill="${shade(node.color, 0.1)}" text-anchor="middle">★</text>`
        );
    } else {
      out.push(
        `<rect x="${x}" y="${y}" width="${node.w}" height="${
          node.h
        }" rx="${S.leaf.r}" fill="${
          node.warn ? '#FFF1EE' : tint(node.color, 0.045)
        }" stroke="${
          node.warn ? '#E2A79C' : LINE
        }" stroke-width="1.4" filter="url(#sh)"/>`,
        `<rect x="${x}" y="${y + 8}" width="5.5" height="${
          node.h - 16
        }" rx="2.75" fill="${node.warn ? '#C0392B' : node.color}"/>`,
        renderLines(
          node,
          S.leaf,
          x + S.leaf.padX,
          node.cy,
          node.warn ? '#B3261E' : INK,
          node.warn ? 500 : 400,
          'start'
        )
      );
    }
  }
  function walkNodes(node, x) {
    nodes(node, x);
    if (node.children)
      node.children.forEach((c) =>
        walkNodes(c, x === X_ROOT ? X_GROUP : X_LEAF)
      );
  }

  const rootNode = {
    kind: 'root',
    w: COL.rootW,
    h: rootH,
    cy: bodyCY,
    color: cfg.accent,
  };
  edges(rootNode, X_ROOT);
  groups.forEach((g) => edges(g, X_GROUP));
  walkNodes(rootNode, X_ROOT);
  groups.forEach((g) => walkNodes(g, X_GROUP));

  /* ---------- 易混易错 / 答题模板 ---------- */
  [
    [panelL, pLeftX],
    [panelR, pRightX],
  ].forEach(([p, x]) => {
    out.push(
      `<rect x="${x}" y="${panelTop.toFixed(1)}" width="${
        p.w
      }" height="${panelH.toFixed(1)}" rx="16" fill="#FFFFFF" stroke="${LINE}" stroke-width="1.5"/>`,
      `<rect x="${x}" y="${panelTop.toFixed(1)}" width="7" height="${panelH.toFixed(
        1
      )}" rx="3.5" fill="${p.color}"/>`,
      `<text x="${x + 30}" y="${(panelTop + 38 * k).toFixed(
        1
      )}" font-family="${FONT}" font-size="${(22 * k).toFixed(
        1
      )}" font-weight="700" fill="${shade(
        p.color,
        0.1
      )}" letter-spacing="2">${p.title}</text>`,
      `<line x1="${x + 30}" y1="${(panelTop + 54 * k).toFixed(1)}" x2="${
        x + p.w - 30
      }" y2="${(panelTop + 54 * k).toFixed(1)}" stroke="${LINE}" stroke-width="1.4"/>`
    );
    let yy = panelTop + 54 * k + 26 * k;
    p.itemLines.forEach((lines) => {
      lines.forEach((ln, li) => {
        out.push(
          `<text x="${(x + 30 + (li === 0 ? 0 : 26 * k)).toFixed(
            1
          )}" y="${(yy + li * pLh).toFixed(
            1
          )}" font-family="${FONT}" font-size="${pFs.toFixed(
            1
          )}" fill="${INK}" xml:space="preserve">${esc(ln)}</text>`
        );
      });
      yy += lines.length * pLh + 7 * k;
    });
  });

  /* ---------- 结论条 ---------- */
  const conclLines = measure(cfg.conclusion, PW - MX * 2 - 210, 26 * k);
  out.push(
    `<rect x="${MX}" y="${CONCL_Y}" width="${PW - MX * 2}" height="${
      CONCL_H
    }" rx="18" fill="${tint(cfg.accent, 0.09)}" stroke="${mix(
      cfg.accent,
      '#FFFFFF',
      0.55
    )}" stroke-width="1.8"/>`,
    `<rect x="${MX}" y="${CONCL_Y}" width="9" height="${CONCL_H}" rx="4.5" fill="${cfg.accent}"/>`,
    `<text x="${MX + 30}" y="${
      CONCL_Y + 40
    }" font-family="${FONT}" font-size="${(21 * k).toFixed(
      1
    )}" font-weight="700" fill="${shade(
      cfg.accent,
      0.2
    )}" letter-spacing="2">本框结论</text>`
  );
  conclLines.forEach((ln, i) =>
    out.push(
      `<text x="${MX + 150}" y="${(
        CONCL_Y +
        40 +
        i * 30 * k
      ).toFixed(1)}" font-family="${FONT}" font-size="${(26 * k).toFixed(
        1
      )}" fill="${INK}">${esc(ln)}</text>`
    )
  );

  /* ---------- 页脚 ---------- */
  out.push(
    `<line x1="${MX}" y1="3382" x2="${PW - MX}" y2="3382" stroke="${LINE}" stroke-width="2"/>`,
    `<text x="${MX}" y="3428" font-family="${FONT}" font-size="21" fill="${INK_SOFT}">高中思想政治 ${esc(
      cfg.book
    )} · 一框一页思维导图（详解）</text>`,
    `<text x="${PW - MX}" y="3428" font-family="${FONT}" font-size="21" fill="${INK_SOFT}" text-anchor="end">${esc(
      cfg.box
    )} · 第 ${cfg.pageNo} / ${cfg.totalPages} 页</text>`
  );

  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${PW}" height="${PH}" viewBox="0 0 ${PW} ${PH}">` +
    `<defs>${defs.join('')}</defs>` +
    `<rect x="0" y="0" width="${PW}" height="${PH}" fill="${BG}"/>` +
    out.join('') +
    `</svg>`;
  return { svg, contentH, availH: mapH, panelH };
}

module.exports = { renderPage, PW, PH, MAP_BOTTOM, MAP_TOP, texts: { textWidth } };
