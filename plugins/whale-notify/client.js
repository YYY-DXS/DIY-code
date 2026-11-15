/**
 * Whale alerts — browser half.
 *
 * Listens to the one status snapshot the Web UI already keeps per Session
 * (`ctx.uiSession.sessionStatus`): a running turn that stops, and a pending
 * interaction (a question, a plan review, or an approval) that appears. On
 * either edge it plays a short synthesized chime and shows a whale card in the
 * frame-wide `shell.overlay` layer. A row in Settings > General toggles the
 * chime and the card independently; both choices persist in localStorage.
 *
 * Nothing here reads the DOM outside its own elements, neither notification
 * path is a Session log write, and the Host half stays empty.
 */
window.__ModuleLoader__.load({
  id: '@local/whale-notify',
  factory(require) {
    const React = require('react')
    const h = React.createElement

    /** Locale namespace owning this plugin's visible copy. */
    const NS = 'whaleNotify'
    /** Browser preference key; one JSON object. */
    const PREF_KEY = 'dsh.whale-notify.prefs.v1'
    /** How long an unattended card stays. */
    const CARD_LIFETIME_MS = 7000
    /** Simultaneous cards kept on screen. */
    const MAX_CARDS = 2

    /** Built-in dictionaries: the locale service copy and the fallback when it is absent. */
    const TEXTS = {
      zh: {
        'done.title': '搞定啦',
        'done.sub': '「{title}」任务完成',
        'ask.title': '等你回复',
        'ask.sub': '「{title}」有事问你',
        'approval.title': '等你确认',
        'approval.sub': '「{title}」在等你确认',
        'open': '打开这个会话',
        'dismiss': '关闭提醒',
        'session.unknown': '当前会话',
        'settings.title': '鲸鱼提示',
        'settings.desc': '任务完成或等你回复时，播放提示音并弹出鲸鱼卡片。',
        'settings.sound': '提示音',
        'settings.visual': '鲸鱼卡片',
        'settings.preview': '试一下',
        'settings.previewHint': '立即播放一次提示音并显示鲸鱼卡片（两种卡片轮流出现）',
      },
      en: {
        'done.title': 'All done',
        'done.sub': '“{title}” finished',
        'ask.title': 'Your turn',
        'ask.sub': '“{title}” has a question',
        'approval.title': 'Approval needed',
        'approval.sub': '“{title}” is waiting on you',
        'open': 'Open this session',
        'dismiss': 'Dismiss alert',
        'session.unknown': 'this session',
        'settings.title': 'Whale alerts',
        'settings.desc': 'Play a chime and show a whale card when a turn finishes or waits for your reply.',
        'settings.sound': 'Chime',
        'settings.visual': 'Whale card',
        'settings.preview': 'Try it',
        'settings.previewHint': 'Play the chime and show the card now (the two card kinds alternate)',
      },
    }

    /** Chime notes per alert kind; `at`/`dur` are seconds from the same start. */
    const NOTES = {
      done: [
        { f: 523.25, at: 0, dur: 0.22, gain: 0.14, slide: 0.92 },
        { f: 783.99, at: 0.1, dur: 0.3, gain: 0.11, slide: 0.9 },
        { f: 1046.5, at: 0.18, dur: 0.28, gain: 0.05, slide: 0.94, type: 'triangle' },
        { f: 196, at: 0.02, dur: 0.45, gain: 0.05, slide: 0.8 },
      ],
      ask: [
        { f: 659.25, at: 0, dur: 0.15, gain: 0.12 },
        { f: 880, at: 0.085, dur: 0.16, gain: 0.12 },
        { f: 1174.66, at: 0.17, dur: 0.3, gain: 0.09, slide: 0.96 },
      ],
      approval: [
        { f: 587.33, at: 0, dur: 0.16, gain: 0.12 },
        { f: 880, at: 0.1, dur: 0.34, gain: 0.1, slide: 0.93, type: 'triangle' },
      ],
    }

    /**
     * Whether the page is most likely Chinese; only the fallback copy needs it.
     * @returns true for a `zh`-prefixed document or browser language.
     */
    function prefersChinese() {
      try {
        const lang = String(document.documentElement.lang || navigator.language || 'en').toLowerCase()
        return lang.indexOf('zh') === 0
      } catch (error) {
        return false
      }
    }

    /**
     * Resolve copy through the standard locale seat, falling back to the built-in
     * dictionary when the seat is missing or returns a bare key.
     * @param t - the slot's `t`, when the locale entry supplied one.
     * @returns a key-to-text function.
     */
    function makeT(t) {
      const fallback = prefersChinese() ? TEXTS.zh : TEXTS.en
      return (key) => {
        if (typeof t === 'function') {
          try {
            const text = t(key)
            if (typeof text === 'string' && text !== '' && text !== key) return text
          } catch (error) {
            // A locale seat that cannot answer falls through to the local copy.
          }
        }
        return fallback[key] === undefined ? key : fallback[key]
      }
    }

    /**
     * Small observable store: `useSyncExternalStore` reads `get`, writes replace
     * the snapshot so component state stays immutable.
     * @param initial - first snapshot.
     * @returns the store.
     */
    function createStore(initial) {
      let value = initial
      const listeners = new Set()
      return {
        get: () => value,
        set: (next) => {
          if (next === value) return
          value = next
          for (const listener of Array.from(listeners)) {
            try {
              listener()
            } catch (error) {
              console.error('[whale-notify] store listener failed', error)
            }
          }
        },
        subscribe: (listener) => {
          listeners.add(listener)
          return () => {
            listeners.delete(listener)
          }
        },
      }
    }

    /**
     * Read the persisted preferences, repairing anything unusable.
     * @returns `{ sound, visual }`.
     */
    function readPrefs() {
      try {
        const raw = window.localStorage.getItem(PREF_KEY)
        if (raw !== null && raw !== '') {
          const parsed = JSON.parse(raw)
          if (parsed !== null && typeof parsed === 'object') {
            return { sound: parsed.sound !== false, visual: parsed.visual !== false }
          }
        }
      } catch (error) {
        // Private mode or corrupted JSON: defaults still apply.
      }
      return { sound: true, visual: true }
    }

    /**
     * Persist the preferences, ignoring storage failures.
     * @param prefs - the new choice.
     */
    function writePrefs(prefs) {
      try {
        window.localStorage.setItem(PREF_KEY, JSON.stringify(prefs))
      } catch (error) {
        // Storage refusal must never break the alert itself.
      }
    }

    /**
     * Build the chibi whale-girl drawing for one alert.
     *
     * The character is the community `鲸鱼娘` (DeepSeek whale girl): blue gradient
     * hair, the loop cowlick, whale-fin ears, a white ruffled maid headdress, the
     * navy dress with a white apron, and the big whale tail. This is an original
     * flat-vector rendering of those shared design traits — no artwork from any
     * fan source is embedded or traced.
     * @param kind - `done` (holding the rice bowl), `ask`, or `approval` (speech bubble).
     * @returns the SVG element.
     */
    function whaleGirl(kind) {
      const HAIR = '#3559b8'
      const HAIR_LIGHT = '#4fa8e8'
      const NAVY = '#24346b'
      const FIN_INNER = '#3d5a9e'
      const SKIN = '#ffe6d8'
      const SKIN_SHADE = '#f2cdb9'
      const BLUSH = '#ffb3c0'
      const EYE = '#2e7fd0'
      const EYE_DARK = '#16305e'
      const LASH = '#1e2f66'
      const GOLD = '#c9a24b'

      const eye = (cx, key) => [
        h('ellipse', { key: key + '-white', cx, cy: 48.5, rx: 5.6, ry: 6.6, fill: '#ffffff' }),
        h('ellipse', { key: key + '-iris', cx, cy: 49, rx: 4.3, ry: 5.3, fill: EYE }),
        h('ellipse', { key: key + '-pupil', cx, cy: 49.4, rx: 2.1, ry: 3.1, fill: EYE_DARK }),
        h('circle', { key: key + '-shine', cx: cx - 1.8, cy: 46.2, r: 1.8, fill: '#ffffff' }),
        h('circle', { key: key + '-spark', cx: cx + 1.7, cy: 52, r: 0.9, fill: '#bfe8ff' }),
      ]

      const parts = [
        // Long hair mass, the lighter ends, and the whale tail behind the body.
        h('ellipse', { key: 'hair', cx: 50, cy: 48, rx: 31, ry: 37, fill: HAIR }),
        h('ellipse', { key: 'hair-ends', cx: 50, cy: 70, rx: 26.5, ry: 14.5, fill: HAIR_LIGHT, opacity: 0.9 }),
        h('g', { key: 'tail', className: 'dsh-wg-tail' },
          h('path', {
            d: 'M30 85C23 81 18 74 17 66 23 68 28 73 31 79 35 73 40 68 46 66 45 74 40 81 33 85Z',
            fill: NAVY,
          }),
        ),
        // Whale-fin ears, then the face.
        h('g', { key: 'fin-l', className: 'dsh-wg-fin-l' },
          h('path', { d: 'M24 48C16 47 8 40 5 32 12 30 20 35 25 43Z', fill: NAVY }),
          h('path', { d: 'M21 45C16 43 12 39 9 34 14 34 19 37 22 42Z', fill: FIN_INNER }),
        ),
        h('g', { key: 'fin-r', className: 'dsh-wg-fin-r' },
          h('path', { d: 'M76 48C84 47 92 40 95 32 88 30 80 35 75 43Z', fill: NAVY }),
          h('path', { d: 'M79 45C84 43 88 39 91 34 86 34 81 37 78 42Z', fill: FIN_INNER }),
        ),
        h('ellipse', { key: 'face', cx: 50, cy: 46, rx: 20, ry: 18.5, fill: SKIN }),
        // Side-swept bangs over the forehead.
        h('path', {
          key: 'bangs',
          d: 'M28 45C27 27 36 19 50 19 64 19 73 27 72 45 69 38 65 34 61 36 57 38 54 41 50 39 46 37 43 38 39 36 35 34 31 38 28 45Z',
          fill: '#3e63c4',
        }),
        // White ruffled maid headdress.
        h('path', {
          key: 'headband',
          d: 'M30 35C29 23 38 15 50 15 62 15 71 23 70 35 68 27 60 21 50 21 40 21 32 27 30 35Z',
          fill: '#ffffff',
        }),
        h('g', { key: 'frill' }, [
          h('circle', { key: 'f1', cx: 35, cy: 28.5, r: 2.1, fill: '#ffffff' }),
          h('circle', { key: 'f2', cx: 42, cy: 24, r: 2.1, fill: '#ffffff' }),
          h('circle', { key: 'f3', cx: 50, cy: 22.5, r: 2.1, fill: '#ffffff' }),
          h('circle', { key: 'f4', cx: 58, cy: 24, r: 2.1, fill: '#ffffff' }),
          h('circle', { key: 'f5', cx: 65, cy: 28.5, r: 2.1, fill: '#ffffff' }),
        ]),
        h('g', { key: 'ahoge', className: 'dsh-wg-ahoge' },
          h('path', {
            d: 'M50 18C49 11 53 6 57 6 61 6 63 9 61 12 59 15 55 13 55 10',
            fill: 'none',
            stroke: HAIR,
            strokeWidth: 3,
            strokeLinecap: 'round',
          }),
        ),
        h('g', { key: 'eyes', className: 'dsh-wg-eye' },
          eye(40.5, 'eye-l'),
          eye(59.5, 'eye-r'),
          h('path', { key: 'lash-l', d: 'M35 42.4C37 40.6 41 40 44.6 41.2', fill: 'none', stroke: LASH, strokeWidth: 1.5, strokeLinecap: 'round' }),
          h('path', { key: 'lash-r', d: 'M65 42.4C63 40.6 59 40 55.4 41.2', fill: 'none', stroke: LASH, strokeWidth: 1.5, strokeLinecap: 'round' }),
        ),
        h('ellipse', { key: 'blush-l', cx: 36, cy: 54.5, rx: 3.2, ry: 1.9, fill: BLUSH, opacity: 0.8 }),
        h('ellipse', { key: 'blush-r', cx: 64, cy: 54.5, rx: 3.2, ry: 1.9, fill: BLUSH, opacity: 0.8 }),
        h('path', { key: 'mouth', d: 'M47.5 57.4Q50 60 52.5 57.4', fill: 'none', stroke: '#c4697b', strokeWidth: 1.4, strokeLinecap: 'round' }),
        // Neck, collar, sleeves, dress, apron and trim.
        h('rect', { key: 'neck', x: 48, y: 60.5, width: 4, height: 5, rx: 2, fill: SKIN_SHADE }),
        h('ellipse', { key: 'sleeve-l', cx: 35.5, cy: 70, rx: 3.4, ry: 5, fill: NAVY }),
        h('ellipse', { key: 'sleeve-r', cx: 64.5, cy: 70, rx: 3.4, ry: 5, fill: NAVY }),
        h('path', { key: 'bodice', d: 'M41 65C45 63.2 55 63.2 59 65L61 73C54 76 46 76 39 73Z', fill: NAVY }),
        h('path', { key: 'skirt', d: 'M39 73C46 76 54 76 61 73L67 85C58 89 42 89 33 85Z', fill: NAVY }),
        h('path', { key: 'hem', d: 'M33 85C42 89 58 89 67 85L68.5 87.2C58 91.4 42 91.4 31.5 87.2Z', fill: '#ffffff' }),
        h('path', { key: 'collar', d: 'M42 65C44 62.6 46.4 62 50 64.2 53.6 62 56 62.6 58 65 55 67.2 45 67.2 42 65Z', fill: '#ffffff' }),
        h('path', { key: 'apron', d: 'M44.5 67C46.5 66 53.5 66 55.5 67L57 82C54 84 46 84 43 82Z', fill: '#ffffff' }),
        h('path', { key: 'trim', d: 'M34.5 84C43 87.6 57 87.6 65.5 84', fill: 'none', stroke: GOLD, strokeWidth: 1, opacity: 0.9 }),
      ]

      if (kind === 'done') {
        parts.push(
          h('circle', { key: 'hand-l', cx: 39, cy: 83.5, r: 2.6, fill: SKIN }),
          h('circle', { key: 'hand-r', cx: 61, cy: 83.5, r: 2.6, fill: SKIN }),
          h('path', { key: 'bowl', d: 'M38 82.5C38 92 62 92 62 82.5Z', fill: '#dfeaf4', stroke: '#c9d8e6', strokeWidth: 0.8 }),
          h('ellipse', { key: 'rice', cx: 50, cy: 81, rx: 9.4, ry: 3.4, fill: '#ffffff' }),
          h('g', { key: 'grains' }, [
            h('circle', { key: 'g1', cx: 45.5, cy: 79.8, r: 1.3, fill: '#ffffff' }),
            h('circle', { key: 'g2', cx: 50, cy: 79, r: 1.4, fill: '#ffffff' }),
            h('circle', { key: 'g3', cx: 54.5, cy: 80, r: 1.2, fill: '#ffffff' }),
          ]),
          h('path', { key: 'steam-1', className: 'dsh-wg-steam', d: 'M44 78C42.6 76.4 45.4 75 44 73.4', fill: 'none', stroke: '#a9d4ee', strokeWidth: 1.6, strokeLinecap: 'round' }),
          h('path', { key: 'steam-2', className: 'dsh-wg-steam dsh-wg-steam-2', d: 'M50 78C48.6 76.2 51.4 74.8 50 73', fill: 'none', stroke: '#a9d4ee', strokeWidth: 1.6, strokeLinecap: 'round' }),
        )
      } else {
        parts.push(
          h('rect', { key: 'bubble', className: 'dsh-wg-bubble', x: 70, y: 8, width: 24, height: 17, rx: 5.5, fill: '#eef8ff', stroke: '#9fd0ef', strokeWidth: 1.2 }),
          h('g', { key: 'dots', className: 'dsh-wg-bubble' }, [
            h('circle', { key: 'd1', className: 'dsh-wg-dot', cx: 77.5, cy: 16.5, r: 1.7, fill: EYE }),
            h('circle', { key: 'd2', className: 'dsh-wg-dot dsh-wg-dot-2', cx: 82, cy: 16.5, r: 1.7, fill: EYE }),
            h('circle', { key: 'd3', className: 'dsh-wg-dot dsh-wg-dot-3', cx: 86.5, cy: 16.5, r: 1.7, fill: EYE }),
          ]),
        )
      }

      return h('svg', {
        className: 'dsh-whale-art',
        viewBox: '0 0 100 100',
        'aria-hidden': 'true',
        focusable: 'false',
      }, parts)
    }

    /** Everything the two entries and the status listener share, styled with host tokens. */
    const CSS = [
      '.dsh-whale-stack{position:fixed;right:18px;bottom:18px;z-index:60;display:flex;flex-direction:column;align-items:flex-end;gap:8px;max-width:min(340px,calc(100vw - 28px));pointer-events:none}',
      '.dsh-whale-card{pointer-events:auto;display:flex;align-items:center;gap:2px;padding:8px 8px 8px 10px;border:0.5px solid var(--dsw-alias-border-l1,rgba(0,0,0,.12));border-radius:14px;background:var(--dsw-alias-bg-overlay,#fff);box-shadow:0 10px 28px rgba(16,42,67,.16);animation:dsh-whale-in .26s cubic-bezier(.2,.9,.3,1.1) both}',
      '@keyframes dsh-whale-in{from{opacity:0;transform:translateY(10px) scale(.96)}to{opacity:1;transform:translateY(0) scale(1)}}',
      '.dsh-whale-open{display:flex;align-items:center;gap:8px;min-width:0;margin:0;padding:0;border:0;border-radius:10px;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer}',
      '.dsh-whale-open:focus-visible{outline:2px solid var(--dsw-alias-brand-primary,#4d6bfe);outline-offset:2px}',
      '.dsh-whale-art{display:block;flex:none;width:64px;height:64px;animation:dsh-whale-bob 3.4s ease-in-out infinite}',
      '@keyframes dsh-whale-bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-2.4px)}}',
      '.dsh-whale-text{display:flex;flex-direction:column;min-width:0;gap:1px}',
      '.dsh-whale-title{max-width:196px;overflow:hidden;font-size:13px;font-weight:600;line-height:18px;color:var(--dsw-alias-label-primary,#1c1c1c);text-overflow:ellipsis;white-space:nowrap}',
      '.dsh-whale-sub{max-width:196px;overflow:hidden;font-size:12px;line-height:17px;color:var(--dsw-alias-label-secondary,#6b6b6b);text-overflow:ellipsis;white-space:nowrap}',
      '.dsh-whale-close{display:grid;flex:none;place-items:center;width:24px;height:24px;margin-left:4px;padding:0;border:0;border-radius:999px;background:transparent;color:var(--dsw-alias-label-secondary,#6b6b6b);font:inherit;font-size:15px;line-height:1;cursor:pointer}',
      '.dsh-whale-close:hover{background:var(--dsw-alias-bg-layer-2,rgba(0,0,0,.06))}',
      '.dsh-whale-close:focus-visible{outline:2px solid var(--dsw-alias-brand-primary,#4d6bfe);outline-offset:1px}',
      '.dsh-wg-ahoge{transform-box:view-box;transform-origin:52px 16px;animation:dsh-wg-ahoge 2.8s ease-in-out infinite}',
      '@keyframes dsh-wg-ahoge{0%,100%{transform:rotate(-5deg)}50%{transform:rotate(7deg)}}',
      '.dsh-wg-fin-l{transform-box:view-box;transform-origin:24px 44px;animation:dsh-wg-fin 3.8s ease-in-out infinite}',
      '.dsh-wg-fin-r{transform-box:view-box;transform-origin:76px 44px;animation:dsh-wg-fin 3.8s ease-in-out infinite reverse}',
      '@keyframes dsh-wg-fin{0%,100%{transform:rotate(-4deg)}50%{transform:rotate(5deg)}}',
      '.dsh-wg-tail{transform-box:view-box;transform-origin:34px 84px;animation:dsh-wg-tail 3.2s ease-in-out infinite}',
      '@keyframes dsh-wg-tail{0%,100%{transform:rotate(-5deg)}50%{transform:rotate(7deg)}}',
      '.dsh-wg-eye{transform-box:view-box;transform-origin:50px 48px;animation:dsh-wg-blink 4.6s infinite}',
      '@keyframes dsh-wg-blink{0%,90%,100%{transform:scaleY(1)}93%{transform:scaleY(.08)}96%{transform:scaleY(1)}}',
      '.dsh-wg-bubble{animation:dsh-wg-pop .34s cubic-bezier(.2,.9,.3,1.2) both}',
      '@keyframes dsh-wg-pop{0%{opacity:0;transform:translateY(4px) scale(.7)}100%{opacity:1;transform:none}}',
      '.dsh-wg-dot{animation:dsh-wg-dot 1.5s ease-in-out infinite}',
      '.dsh-wg-dot-2{animation-delay:.2s}',
      '.dsh-wg-dot-3{animation-delay:.4s}',
      '@keyframes dsh-wg-dot{0%,60%,100%{opacity:.35}25%{opacity:1}}',
      '.dsh-wg-steam{opacity:0;animation:dsh-wg-steam 2.6s ease-in-out infinite}',
      '.dsh-wg-steam-2{animation-delay:.7s}',
      '@keyframes dsh-wg-steam{0%{opacity:0;transform:translateY(3px)}35%{opacity:.9}100%{opacity:0;transform:translateY(-7px)}}',
      '.dsh-whale-row{display:flex;align-items:center;gap:12px;padding:16px 0;border-bottom:0.5px solid var(--dsw-alias-border-l2,rgba(0,0,0,.12))}',
      '.dsh-whale-rowText{display:flex;flex:1;flex-direction:column;min-width:0;gap:4px;padding-right:16px}',
      '.dsh-whale-rowTitle{font-size:14px;font-weight:400;line-height:22px;color:var(--dsw-alias-label-primary,#1c1c1c)}',
      '.dsh-whale-rowDesc{font-size:12px;line-height:18px;color:var(--dsw-alias-label-secondary,#6b6b6b)}',
      '.dsh-whale-switches{display:flex;flex:none;flex-wrap:wrap;gap:8px;justify-content:flex-end}',
      '.dsh-whale-preview{height:36px;padding:0 14px;border:0.5px solid var(--dsw-alias-border-l2,rgba(0,0,0,.12));border-radius:var(--dsw-radius-md,10px);background:transparent;color:var(--dsw-alias-label-primary,#1c1c1c);font:inherit;font-size:14px;line-height:22px;cursor:pointer}',
      '.dsh-whale-preview:hover{background:var(--dsw-alias-bg-layer-2,rgba(0,0,0,.06))}',
      '.dsh-whale-preview:focus-visible{outline:2px solid var(--dsw-alias-brand-primary,#4d6bfe);outline-offset:2px}',
      '.dsh-whale-switch{display:inline-flex;align-items:center;gap:8px;height:36px;padding:0 14px;border:0;border-radius:var(--dsw-radius-md,10px);background:var(--dsw-alias-bg-layer-2,rgba(0,0,0,.06));color:var(--dsw-alias-label-primary,#1c1c1c);font:inherit;font-size:14px;line-height:22px;cursor:pointer}',
      '.dsh-whale-switch:hover{background:var(--dsw-alias-bg-layer-1,rgba(0,0,0,.03))}',
      '.dsh-whale-switch:focus-visible{outline:2px solid var(--dsw-alias-brand-primary,#4d6bfe);outline-offset:2px}',
      '.dsh-whale-track{position:relative;display:block;flex:none;width:30px;height:18px;border-radius:999px;background:var(--dsw-alias-state-idle-primary,#c9ccd1);transition:background .18s ease}',
      ".dsh-whale-switch[aria-checked='true'] .dsh-whale-track{background:var(--dsw-alias-brand-primary,#4d6bfe)}",
      '.dsh-whale-knob{position:absolute;top:2px;left:2px;display:block;width:14px;height:14px;border-radius:50%;background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .18s ease}',
      ".dsh-whale-switch[aria-checked='true'] .dsh-whale-knob{transform:translateX(12px)}",
      '@media (max-width:520px){.dsh-whale-row{flex-wrap:wrap}.dsh-whale-switches{width:100%;justify-content:flex-end}}',
      '@media (prefers-reduced-motion:reduce){.dsh-whale-card,.dsh-whale-art,.dsh-wg-ahoge,.dsh-wg-fin-l,.dsh-wg-fin-r,.dsh-wg-tail,.dsh-wg-eye,.dsh-wg-bubble,.dsh-wg-dot,.dsh-wg-steam,.dsh-whale-knob,.dsh-whale-track{animation:none!important;transition:none!important}}',
    ].join('\n')

    return {
      /** `uiSession` carries the status snapshot; `slots` renders both entries; `locale` holds the copy. */
      inject: ['uiSession', 'slots', 'locale'],

      /**
       * Install the alert pipeline and its two entries.
       * @param ctx - the browser plugin context.
       */
      apply(ctx) {
        /** Current preferences, read on every alert. */
        let prefs = readPrefs()
        /** Rendered state of the settings row. */
        const prefStore = createStore(prefs)
        /** Cards currently on screen. */
        const cardStore = createStore({ items: [] })
        /** Monotonic card identity. */
        let sequence = 0
        /** Last announced `kind:session` pair and when, to absorb duplicate frames. */
        let lastKey = ''
        let lastAt = 0
        /** Lazily created Web Audio context. */
        let audio = null
        /** Optional services, resolved once. */
        const sessions = soft(ctx, 'sessions')
        const workspace = soft(ctx, 'uiWorkspace')

        /** Publish this plugin's dictionaries for both baseline locales. */
        ctx.effect(() => ctx.locale.register(NS, 'zh', TEXTS.zh))
        ctx.effect(() => ctx.locale.register(NS, 'en', TEXTS.en))

        /**
         * The channel for one alert.
         * @returns a Web Audio context, or null when the browser refuses one.
         */
        const audioContext = () => {
          if (audio !== null) return audio
          const Ctor = window.AudioContext || window.webkitAudioContext
          if (typeof Ctor !== 'function') return null
          try {
            audio = new Ctor()
          } catch (error) {
            audio = null
          }
          return audio
        }

        /** Resume the context on the first user gesture, which browsers require. */
        const unlockAudio = () => {
          const context = audioContext()
          if (context === null) return
          if (context.state === 'suspended') {
            try {
              void context.resume()
            } catch (error) {
              // A refused resume leaves the card as the only feedback.
            }
          }
        }
        document.addEventListener('pointerdown', unlockAudio, true)
        document.addEventListener('keydown', unlockAudio, true)
        ctx.effect(() => () => {
          document.removeEventListener('pointerdown', unlockAudio, true)
          document.removeEventListener('keydown', unlockAudio, true)
          const context = audio
          audio = null
          if (context !== null) {
            try {
              void context.close()
            } catch (error) {
              // Already closed.
            }
          }
        })

        /**
         * Play one shaped note.
         * @param context - the audio context.
         * @param base - start of the pattern.
         * @param note - frequency, offset, length, level, optional glide and waveform.
         */
        const playNote = (context, base, note) => {
          try {
            const start = base + note.at
            const end = start + note.dur
            const oscillator = context.createOscillator()
            const gain = context.createGain()
            oscillator.type = note.type || 'sine'
            oscillator.frequency.setValueAtTime(note.f, start)
            if (note.slide !== undefined) {
              oscillator.frequency.exponentialRampToValueAtTime(Math.max(30, note.f * note.slide), end - 0.01)
            }
            gain.gain.setValueAtTime(0.0001, start)
            gain.gain.exponentialRampToValueAtTime(note.gain, start + 0.018)
            gain.gain.exponentialRampToValueAtTime(0.0001, end)
            oscillator.connect(gain)
            gain.connect(context.destination)
            oscillator.start(start)
            oscillator.stop(end + 0.03)
            oscillator.onended = () => {
              try {
                gain.disconnect()
              } catch (error) {
                // The graph is already gone.
              }
            }
          } catch (error) {
            console.error('[whale-notify] chime note failed', error)
          }
        }

        /**
         * Play the alert's chime.
         * @param kind - `done`, `ask`, or `approval`.
         */
        const chime = (kind) => {
          if (!prefs.sound) return
          const context = audioContext()
          if (context === null) return
          if (context.state === 'suspended') {
            try {
              void context.resume()
            } catch (error) {
              return
            }
          }
          const pattern = NOTES[kind] === undefined ? NOTES.done : NOTES[kind]
          const base = context.currentTime + 0.02
          for (const note of pattern) playNote(context, base, note)
        }

        /**
         * The display title of one Session.
         * @param sessionId - Session identity.
         * @returns the title, or undefined for a Session this plugin should stay quiet about.
         */
        const titleOf = (sessionId) => {
          if (sessions === undefined) return ''
          try {
            const row = sessions.list.getSnapshot().byId[sessionId]
            if (row === undefined || row === null) return undefined
            // Inner agent work reports through its parent's turn; announcing it would double the chime.
            if (row.origin === 'subagent') return undefined
            return typeof row.displayTitle === 'string' ? row.displayTitle : ''
          } catch (error) {
            return ''
          }
        }

        /**
         * Show one card, keeping only the newest few.
         * @param kind - `done`, `ask`, or `approval`.
         * @param sessionId - Session the card opens; empty for a preview card.
         * @param title - Session display title, possibly empty.
         */
        const pushCard = (kind, sessionId, title) => {
          const item = { id: sequence + 1, kind, sessionId, title, at: Date.now() }
          sequence = item.id
          const items = cardStore.get().items.concat(item)
          cardStore.set({ items: items.slice(-MAX_CARDS) })
        }

        /**
         * The Session the user is looking at, for the preview card's title.
         * @returns its identity and title, or undefined when no row is known.
         */
        const currentSession = () => {
          if (sessions === undefined) return undefined
          try {
            const rows = Object.values(sessions.list.getSnapshot().byId)
            const row = rows.find(candidate => (candidate.retainedBy.mainView ?? 0) > 0)
              ?? rows.find(candidate => candidate.origin !== 'subagent')
            if (row === undefined) return undefined
            return { id: row.id, title: typeof row.displayTitle === 'string' ? row.displayTitle : '' }
          } catch (error) {
            return undefined
          }
        }

        /**
         * Announce one edge: chime now, card when enabled.
         * @param kind - `done`, `ask`, or `approval`.
         * @param sessionId - the Session the alert belongs to.
         */
        const announce = (kind, sessionId) => {
          const title = titleOf(sessionId)
          if (title === undefined) return
          if (!prefs.sound && !prefs.visual) return
          const now = Date.now()
          const key = kind + ':' + sessionId
          if (key === lastKey && now - lastAt < 1200) return
          lastKey = key
          lastAt = now
          chime(kind)
          if (!prefs.visual) return
          pushCard(kind, sessionId, title)
        }

        /**
         * Drop one card.
         * @param id - card identity.
         */
        const dismiss = (id) => {
          const items = cardStore.get().items.filter(item => item.id !== id)
          if (items.length === cardStore.get().items.length) return
          cardStore.set({ items })
        }

        /**
         * Open the Session a card belongs to, then drop it.
         * @param item - the card.
         */
        const openItem = (item) => {
          dismiss(item.id)
          if (item.sessionId === '') return
          if (workspace === undefined || typeof workspace.openSession !== 'function') return
          try {
            workspace.openSession(item.sessionId)
          } catch (error) {
            console.error('[whale-notify] could not open the session', error)
          }
        }

        /**
         * Persist one preference from the settings row.
         * @param key - `sound` or `visual`.
         * @param value - the new choice.
         */
        const setPref = (key, value) => {
          prefs = { sound: prefs.sound, visual: prefs.visual, [key]: value }
          writePrefs(prefs)
          prefStore.set(prefs)
        }

        /** Alternate the preview between the two cards the plugin shows on its own. */
        let previewFlip = false

        /**
         * Show one alert on demand, ignoring the two switches: this is an explicit
         * test, so it must be visible and audible whatever the saved choices are.
         */
        const preview = () => {
          previewFlip = !previewFlip
          const kind = previewFlip ? 'ask' : 'done'
          const current = currentSession()
          chime(kind)
          pushCard(kind, current === undefined ? '' : current.id, current === undefined ? '' : current.title)
        }


        /** The alert kind one pending interaction deserves. */
        const askKindOf = (interaction) => {
          const kind = interaction === null || interaction === undefined ? undefined : interaction.kind
          return kind === 'approval' || kind === 'plan-review' ? 'approval' : 'ask'
        }

        // One subscription drives both edges; the first snapshot is a baseline,
        // not a notification, so reopening the page does not replay old state.
        const status = ctx.uiSession.sessionStatus
        let previous = new Map()
        const readStatus = () => {
          const current = new Map()
          status.getSnapshot().forEach((value, key) => current.set(key, value))
          return current
        }
        const evaluate = () => {
          const current = readStatus()
          for (const entry of current) {
            const sessionId = entry[0]
            const next = entry[1]
            const before = previous.get(sessionId)
            if (before === undefined) continue
            try {
              if (before.running === true && next.running === false) announce('done', sessionId)
              const wasAsking = before.pendingInteraction === undefined || before.pendingInteraction === null
              const isAsking = next.pendingInteraction !== undefined && next.pendingInteraction !== null
              if (isAsking && (wasAsking || before.pendingInteraction.key !== next.pendingInteraction.key)) {
                announce(askKindOf(next.pendingInteraction), sessionId)
              }
            } catch (error) {
              console.error('[whale-notify] status handling failed', error)
            }
          }
          previous = current
        }
        ctx.effect(() => {
          previous = readStatus()
          return status.subscribe(evaluate)
        })

        /** The whale card stack above every column. */
        function WhaleOverlay(props) {
          const state = React.useSyncExternalStore(cardStore.subscribe, cardStore.get)
          const t = makeT(props !== null && props !== undefined ? props.t : undefined)
          const items = state.items
          const children = [h('style', { key: 'whale-css' }, CSS)]
          if (items.length !== 0) {
            children.push(h('div', {
              key: 'whale-stack',
              className: 'dsh-whale-stack',
              'aria-live': 'polite',
              'aria-atomic': 'false',
            }, items.map(item => h(WhaleCard, { key: item.id, item, t }))))
          }
          return h(React.Fragment, null, children)
        }

        /** One card: whale, copy, and a dismissal beside the open action. */
        function WhaleCard(props) {
          const item = props.item
          const t = props.t
          const pausedState = React.useState(false)
          const paused = pausedState[0]
          const setPaused = pausedState[1]
          React.useEffect(() => {
            if (paused) return undefined
            const timer = window.setTimeout(() => { dismiss(item.id) }, CARD_LIFETIME_MS)
            return () => { window.clearTimeout(timer) }
          }, [item.id, paused])
          const kind = item.kind === 'ask' ? 'ask' : item.kind === 'approval' ? 'approval' : 'done'
          const title = t(kind + '.title')
          const sub = t(kind + '.sub').replace('{title}', item.title === '' ? t('session.unknown') : item.title)
          return h('div', {
            className: 'dsh-whale-card',
            onMouseEnter: () => { setPaused(true) },
            onMouseLeave: () => { setPaused(false) },
            onFocus: () => { setPaused(true) },
            onBlur: () => { setPaused(false) },
          },
            h('button', {
              type: 'button',
              className: 'dsh-whale-open',
              title: t('open'),
              onClick: () => { openItem(item) },
            },
              whaleGirl(kind),
              h('span', { className: 'dsh-whale-text' },
                h('span', { className: 'dsh-whale-title' }, title),
                h('span', { className: 'dsh-whale-sub' }, sub),
              ),
            ),
            h('button', {
              type: 'button',
              className: 'dsh-whale-close',
              'aria-label': t('dismiss'),
              onClick: () => { dismiss(item.id) },
            }, h('span', { 'aria-hidden': 'true' }, '×')),
          )
        }

        /** The Settings > General row owning both preferences. */
        function WhaleSettingsRow(props) {
          const current = React.useSyncExternalStore(prefStore.subscribe, prefStore.get)
          const t = makeT(props !== null && props !== undefined ? props.t : undefined)
          const rows = [
            { key: 'sound', label: t('settings.sound') },
            { key: 'visual', label: t('settings.visual') },
          ]
          return h(React.Fragment, null,
            h('style', { key: 'whale-css' }, CSS),
            h('div', { className: 'dsh-whale-row' },
              h('div', { className: 'dsh-whale-rowText' },
                h('div', { className: 'dsh-whale-rowTitle' }, t('settings.title')),
                h('div', { className: 'dsh-whale-rowDesc' }, t('settings.desc')),
              ),
              h('div', { className: 'dsh-whale-switches' },
                h('button', {
                  type: 'button',
                  className: 'dsh-whale-preview',
                  title: t('settings.previewHint'),
                  onClick: () => { preview() },
                }, t('settings.preview')),
                rows.map(row => h('button', {
                key: row.key,
                type: 'button',
                role: 'switch',
                'aria-checked': current[row.key] ? 'true' : 'false',
                className: 'dsh-whale-switch',
                onClick: () => { setPref(row.key, !current[row.key]) },
              },
                h('span', { className: 'dsh-whale-track', 'aria-hidden': 'true' },
                  h('span', { className: 'dsh-whale-knob' })),
                h('span', { className: 'dsh-whale-switchLabel' }, row.label),
              ))),
            ),
          )
        }

        ctx.slots.inject('shell.overlay', () => ctx.slots.register({
          name: 'shell.overlay',
          id: 'whale-notify.toast',
          order: 40,
          locale: NS,
        }, WhaleOverlay))

        ctx.slots.inject('settings.general.item', () => ctx.slots.register({
          name: 'settings.general.item',
          id: 'whale-notify',
          order: 40,
          locale: NS,
        }, WhaleSettingsRow))
      },
    }

    /**
     * Resolve an optional service without failing activation.
     * @param ctx - the browser plugin context.
     * @param name - service name.
     * @returns the service, or undefined when unavailable.
     */
    function soft(ctx, name) {
      try {
        return ctx.get(name)
      } catch (error) {
        return undefined
      }
    }
  },
})
