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
     * Build the whale drawing for one alert.
     * @param kind - `done`, `ask`, or `approval`.
     * @returns the SVG element.
     */
    function whaleArt(kind) {
      const parts = [
        h('circle', { key: 'spout-1', cx: 25, cy: 10, r: 2.6, fill: '#bfe4f8' }),
        h('circle', { key: 'spout-2', cx: 31, cy: 5.6, r: 2, fill: '#bfe4f8' }),
        h('circle', { key: 'spout-3', cx: 19.4, cy: 6.4, r: 1.8, fill: '#bfe4f8' }),
        h('path', {
          key: 'tail',
          d: 'M13 30C7 26 3.4 20 5.2 14.6 9.4 16.8 13.4 21 15.4 26.2 17.4 21 21.4 16.8 25.6 14.6 27.4 20 23.8 26 17.8 30Z',
          fill: '#5fa8d3',
        }),
        h('path', {
          key: 'body',
          d: 'M14 30C14 20.2 22.4 13 34.6 13 46.8 13 55.6 20.2 55.6 29.4 55.6 38.6 46.8 43.8 34.6 43.8 22.4 43.8 14 39 14 30Z',
          fill: '#7cc4ee',
        }),
        h('path', {
          key: 'belly',
          d: 'M20.4 33.4C20.4 39 26.2 43.8 34.6 43.8 43 43.8 48.8 39 48.8 33.4 45 37.4 24.2 37.4 20.4 33.4Z',
          fill: '#e9f7ff',
        }),
        h('path', {
          key: 'fin',
          d: 'M29.6 40.4C31 45.4 35.6 48 40 46.4 36.4 44.2 34.4 42.2 33.4 39.8Z',
          fill: '#5fa8d3',
        }),
        h('path', {
          key: 'eye',
          d: 'M42.6 25.4q3-3.4 6 0',
          fill: 'none',
          stroke: '#173a4e',
          strokeWidth: 2,
          strokeLinecap: 'round',
        }),
        h('ellipse', { key: 'blush', cx: 49.6, cy: 29.4, rx: 3.4, ry: 2.1, fill: '#ffb3c7', opacity: 0.85 }),
        h('path', {
          key: 'mouth',
          d: 'M44.6 33.6q4 3 7.8 0',
          fill: 'none',
          stroke: '#173a4e',
          strokeWidth: 1.6,
          strokeLinecap: 'round',
        }),
      ]
      if (kind === 'done') {
        parts.push(h('g', { key: 'snack', className: 'dsh-whale-snack' },
          h('ellipse', { cx: 60.5, cy: 33.5, rx: 4.4, ry: 2.9, fill: '#ffb15c' }),
          h('path', { d: 'M64.4 33.5 68.6 30.6 68.6 36.4Z', fill: '#ffb15c' }),
          h('circle', { cx: 58.4, cy: 32.6, r: 0.75, fill: '#6b3f12' }),
        ))
      } else {
        parts.push(h('g', { key: 'bubble', className: 'dsh-whale-bubble' },
          h('path', {
            d: 'M43 4h22a3.4 3.4 0 0 1 3.4 3.4v8.1A3.4 3.4 0 0 1 65 18.9H51.4L47 22.3v-3.4H43a3.4 3.4 0 0 1-3.4-3.4V7.4A3.4 3.4 0 0 1 43 4Z',
            fill: '#e9f7ff',
            stroke: '#9fd0ef',
            strokeWidth: 1.4,
          }),
          h('circle', { cx: 48, cy: 11.3, r: 1.5, fill: '#4f9bc9' }),
          h('circle', { cx: 55, cy: 11.3, r: 1.5, fill: '#4f9bc9' }),
          h('circle', { cx: 62, cy: 11.3, r: 1.5, fill: '#4f9bc9' }),
        ))
      }
      return h('svg', {
        className: 'dsh-whale-art',
        viewBox: '0 0 72 56',
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
      '.dsh-whale-art{display:block;flex:none;width:58px;height:45px;animation:dsh-whale-bob 2.8s ease-in-out infinite}',
      '@keyframes dsh-whale-bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-2.5px)}}',
      '.dsh-whale-text{display:flex;flex-direction:column;min-width:0;gap:1px}',
      '.dsh-whale-title{max-width:214px;overflow:hidden;font-size:13px;font-weight:600;line-height:18px;color:var(--dsw-alias-label-primary,#1c1c1c);text-overflow:ellipsis;white-space:nowrap}',
      '.dsh-whale-sub{max-width:214px;overflow:hidden;font-size:12px;line-height:17px;color:var(--dsw-alias-label-secondary,#6b6b6b);text-overflow:ellipsis;white-space:nowrap}',
      '.dsh-whale-close{display:grid;flex:none;place-items:center;width:24px;height:24px;margin-left:4px;padding:0;border:0;border-radius:999px;background:transparent;color:var(--dsw-alias-label-secondary,#6b6b6b);font:inherit;font-size:15px;line-height:1;cursor:pointer}',
      '.dsh-whale-close:hover{background:var(--dsw-alias-bg-layer-2,rgba(0,0,0,.06))}',
      '.dsh-whale-close:focus-visible{outline:2px solid var(--dsw-alias-brand-primary,#4d6bfe);outline-offset:1px}',
      '.dsh-whale-snack{transform-origin:62px 34px;animation:dsh-whale-snack .52s .08s cubic-bezier(.2,.9,.3,1.2) both}',
      '@keyframes dsh-whale-snack{0%{opacity:0;transform:translate(7px,7px) scale(.6)}55%{opacity:1}100%{opacity:1;transform:translate(0,0) scale(1)}}',
      '.dsh-whale-bubble{transform-origin:54px 18px;animation:dsh-whale-pop .38s .06s cubic-bezier(.2,.9,.3,1.2) both}',
      '@keyframes dsh-whale-pop{0%{opacity:0;transform:scale(.6)}100%{opacity:1;transform:scale(1)}}',
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
      '@media (prefers-reduced-motion:reduce){.dsh-whale-card,.dsh-whale-art,.dsh-whale-snack,.dsh-whale-bubble,.dsh-whale-knob,.dsh-whale-track{animation:none!important;transition:none!important}}',
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
              whaleArt(kind),
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
