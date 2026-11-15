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
    /** Where the mascot was dropped; separate so it survives preference resets. */
    const PET_KEY = 'dsh.whale-notify.pet.v1'
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
        'settings.petTitle': '桌宠挂件',
        'settings.petDesc': '在窗口右下角常驻一只鲸鱼娘，随时看到运行状态；可以拖到任意位置。',
        'settings.pet': '显示桌宠',
        'pet.idle': '空闲',
        'pet.running': '运行中',
        'pet.waiting': '等你回复',
        'pet.done': '刚完成',
        'pet.hide': '隐藏桌宠',
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
        'settings.petTitle': 'Floating mascot',
        'settings.petDesc': 'Keep the whale girl in the corner of the window with the current status; drag her anywhere.',
        'settings.pet': 'Show mascot',
        'pet.idle': 'Idle',
        'pet.running': 'Running',
        'pet.waiting': 'Waiting for you',
        'pet.done': 'Finished',
        'pet.hide': 'Hide the mascot',
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
            return { sound: parsed.sound !== false, visual: parsed.visual !== false, pet: parsed.pet !== false }
          }
        }
      } catch (error) {
        // Private mode or corrupted JSON: defaults still apply.
      }
      return { sound: true, visual: true, pet: true }
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
     * Read the mascot's saved screen position.
     * @returns `{ x, y }`, or null when it was never dragged.
     */
    function readPetPos() {
      try {
        const raw = window.localStorage.getItem(PET_KEY)
        if (raw !== null && raw !== '') {
          const parsed = JSON.parse(raw)
          if (parsed !== null && typeof parsed === 'object'
            && typeof parsed.x === 'number' && typeof parsed.y === 'number') return parsed
        }
      } catch (error) {
        // A missing or corrupt position falls back to the default corner.
      }
      return null
    }

    /**
     * Persist the mascot's screen position.
     * @param pos - `{ x, y }` in client pixels.
     */
    function writePetPos(pos) {
      try {
        window.localStorage.setItem(PET_KEY, JSON.stringify(pos))
      } catch (error) {
        // The mascot simply returns to the default corner next time.
      }
    }

    /**
     * Character renders embedded as data URIs, so the card needs no extra request.
     *
     * Artwork: the community 鲸鱼娘 as rendered by metsh for `dsh-task-mascot`
     * (CC BY-NC-SA 4.0; attribution chain and terms in ART_LICENSE.md). Only a
     * downscale to 192 px was applied — nothing recoloured or retouched.
     */
    const ART = {
      done: 'data:image/webp;base64,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',
      ask: 'data:image/webp;base64,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',
      running: 'data:image/webp;base64,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',
      idle: 'data:image/webp;base64,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',
    }

    /** Everything the two entries and the status listener share, styled with host tokens. */
    const CSS = [
      '.dsh-whale-stack{position:fixed;right:18px;bottom:18px;z-index:60;display:flex;flex-direction:column;align-items:flex-end;gap:8px;max-width:min(340px,calc(100vw - 28px));pointer-events:none}',
      '.dsh-whale-card{pointer-events:auto;display:flex;align-items:center;gap:2px;padding:8px 8px 8px 10px;border:0.5px solid var(--dsw-alias-border-l1,rgba(0,0,0,.12));border-radius:14px;background:var(--dsw-alias-bg-overlay,#fff);box-shadow:0 10px 28px rgba(16,42,67,.16);animation:dsh-whale-in .26s cubic-bezier(.2,.9,.3,1.1) both}',
      '@keyframes dsh-whale-in{from{opacity:0;transform:translateY(10px) scale(.96)}to{opacity:1;transform:translateY(0) scale(1)}}',
      '.dsh-whale-open{display:flex;align-items:center;gap:8px;min-width:0;margin:0;padding:0;border:0;border-radius:10px;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer}',
      '.dsh-whale-open:focus-visible{outline:2px solid var(--dsw-alias-brand-primary,#4d6bfe);outline-offset:2px}',
      '.dsh-whale-art{display:block;flex:none;width:76px;height:76px;object-fit:contain;filter:drop-shadow(0 4px 9px rgba(20,50,90,.18));animation:dsh-whale-bob 3.6s ease-in-out infinite}',
      '@keyframes dsh-whale-bob{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-2.4px) scale(1.015)}}',
      '.dsh-whale-text{display:flex;flex-direction:column;min-width:0;gap:1px}',
      '.dsh-whale-title{max-width:196px;overflow:hidden;font-size:13px;font-weight:600;line-height:18px;color:var(--dsw-alias-label-primary,#1c1c1c);text-overflow:ellipsis;white-space:nowrap}',
      '.dsh-whale-sub{max-width:196px;overflow:hidden;font-size:12px;line-height:17px;color:var(--dsw-alias-label-secondary,#6b6b6b);text-overflow:ellipsis;white-space:nowrap}',
      '.dsh-whale-close{display:grid;flex:none;place-items:center;width:24px;height:24px;margin-left:4px;padding:0;border:0;border-radius:999px;background:transparent;color:var(--dsw-alias-label-secondary,#6b6b6b);font:inherit;font-size:15px;line-height:1;cursor:pointer}',
      '.dsh-whale-close:hover{background:var(--dsw-alias-bg-layer-2,rgba(0,0,0,.06))}',
      '.dsh-whale-close:focus-visible{outline:2px solid var(--dsw-alias-brand-primary,#4d6bfe);outline-offset:1px}',
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
      '.dsh-whale-pet{position:fixed;z-index:55;display:flex;flex-direction:column;align-items:center;gap:2px;padding:2px;cursor:grab;user-select:none;touch-action:none;pointer-events:auto}',
      '.dsh-whale-petArt{display:block;width:96px;height:96px;object-fit:contain;filter:drop-shadow(0 6px 12px rgba(20,50,90,.2));animation:dsh-whale-float 4.4s ease-in-out infinite}',
      '@keyframes dsh-whale-float{0%,100%{transform:translateY(0) rotate(-1deg)}50%{transform:translateY(-5px) rotate(1.5deg)}}',
      '.dsh-whale-petChip{display:inline-flex;align-items:center;gap:5px;padding:2px 8px;border-radius:999px;border:0.5px solid var(--dsw-alias-border-l1,rgba(0,0,0,.12));background:var(--dsw-alias-bg-overlay,#fff);box-shadow:0 3px 8px rgba(16,42,67,.12);font-size:11px;line-height:16px;color:var(--dsw-alias-label-secondary,#6b6b6b);pointer-events:none}',
      '.dsh-whale-petDot{display:block;width:6px;height:6px;border-radius:50%;background:var(--dsw-alias-state-idle-primary,#c9ccd1)}',
      '.dsh-whale-dot-running{background:var(--dsw-alias-brand-primary,#4d6bfe);animation:dsh-whale-pulse 1.2s ease-in-out infinite}',
      '.dsh-whale-dot-waiting{background:var(--dsw-alias-state-warn-primary,#e0a03a)}',
      '.dsh-whale-dot-done{background:var(--dsw-alias-state-success-primary,#2faa6b)}',
      '@keyframes dsh-whale-pulse{0%,100%{opacity:1}50%{opacity:.3}}',
      '.dsh-whale-petHide{position:absolute;top:0;right:0;display:none;place-items:center;width:20px;height:20px;padding:0;border:0;border-radius:50%;background:var(--dsw-alias-bg-overlay,#fff);color:var(--dsw-alias-label-secondary,#6b6b6b);font:inherit;font-size:13px;line-height:1;cursor:pointer}',
      '.dsh-whale-pet:hover .dsh-whale-petHide{display:grid}',
      '@media (prefers-reduced-motion:reduce){.dsh-whale-card,.dsh-whale-art,.dsh-whale-pet,.dsh-whale-petArt,.dsh-whale-petDot,.dsh-whale-knob,.dsh-whale-track{animation:none!important;transition:none!important}}',
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
        /** Floating mascot: which pose to draw and where it sits. */
        const savedPet = readPetPos()
        const petStore = createStore({ phase: 'idle', x: savedPet === null ? null : savedPet.x, y: savedPet === null ? null : savedPet.y })
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
          prefs = { ...prefs, [key]: value }
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
        /** How long the mascot keeps celebrating a finished run. */
        let doneUntil = 0
        /** Timer that returns the mascot to idle after the celebration. */
        let doneTimer = 0
        const evaluate = () => {
          const current = readStatus()
          let running = false
          let waiting = false
          let finished = false
          for (const entry of current) {
            const sessionId = entry[0]
            const next = entry[1]
            if (next.running === true) running = true
            if (next.pendingInteraction !== undefined && next.pendingInteraction !== null) waiting = true
            const before = previous.get(sessionId)
            if (before === undefined) continue
            try {
              if (before.running === true && next.running === false) {
                announce('done', sessionId)
                finished = true
              }
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
          if (finished) {
            doneUntil = Date.now() + 6000
            window.clearTimeout(doneTimer)
            doneTimer = window.setTimeout(evaluate, 6400)
          }
          const phase = waiting ? 'waiting' : running ? 'running' : Date.now() < doneUntil ? 'done' : 'idle'
          if (petStore.get().phase !== phase) petStore.set({ ...petStore.get(), phase })
        }
        ctx.effect(() => {
          previous = readStatus()
          return status.subscribe(evaluate)
        })
        ctx.effect(() => () => { window.clearTimeout(doneTimer) })

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
              h('img', {
                className: 'dsh-whale-art',
                src: ART[kind === 'done' ? 'done' : 'ask'],
                alt: '',
                draggable: 'false',
              }),
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

        /**
         * The draggable mascot: the current pose plus a phase chip.
         * @param props - standard slot props (only the locale seat is used).
         */
        function WhalePet(props) {
          const state = React.useSyncExternalStore(petStore.subscribe, petStore.get)
          const pref = React.useSyncExternalStore(prefStore.subscribe, prefStore.get)
          const t = makeT(props !== null && props !== undefined ? props.t : undefined)
          const held = React.useRef(null)
          if (!pref.pet) return null
          const phase = state.phase === 'done' || state.phase === 'running' || state.phase === 'waiting' ? state.phase : 'idle'
          const pose = phase === 'running' ? ART.running : phase === 'done' ? ART.done : phase === 'waiting' ? ART.ask : ART.idle
          const style = state.x === null || state.y === null
            ? { right: 18, bottom: 112 }
            : { left: state.x, top: state.y }
          const onDown = (event) => {
            if (event.button !== 0) return
            const rect = event.currentTarget.getBoundingClientRect()
            held.current = { dx: event.clientX - rect.left, dy: event.clientY - rect.top, moved: false }
            try {
              event.currentTarget.setPointerCapture(event.pointerId)
            } catch (error) {
              // Pointer capture is an optimization; dragging still works without it.
            }
          }
          const onMove = (event) => {
            const drag = held.current
            if (drag === null) return
            drag.moved = true
            petStore.set({
              ...petStore.get(),
              x: Math.max(0, Math.min(window.innerWidth - 108, event.clientX - drag.dx)),
              y: Math.max(0, Math.min(window.innerHeight - 136, event.clientY - drag.dy)),
            })
          }
          const onUp = () => {
            const drag = held.current
            held.current = null
            if (drag === null || !drag.moved) return
            const state2 = petStore.get()
            writePetPos({ x: state2.x, y: state2.y })
          }
          return h('div', {
            className: 'dsh-whale-pet',
            style,
            onPointerDown: onDown,
            onPointerMove: onMove,
            onPointerUp: onUp,
            onPointerCancel: onUp,
            title: t('pet.' + phase),
          },
            h('img', { className: 'dsh-whale-petArt', src: pose, alt: '', draggable: 'false' }),
            h('span', { className: 'dsh-whale-petChip' },
              h('span', { className: 'dsh-whale-petDot dsh-whale-dot-' + phase, 'aria-hidden': 'true' }),
              h('span', null, t('pet.' + phase)),
            ),
            h('button', {
              type: 'button',
              className: 'dsh-whale-petHide',
              'aria-label': t('pet.hide'),
              onClick: (event) => {
                event.stopPropagation()
                setPref('pet', false)
              },
            }, h('span', { 'aria-hidden': 'true' }, '×')),
          )
        }

        /** The Settings > General row that shows or hides the mascot. */
        function WhalePetRow(props) {
          const current = React.useSyncExternalStore(prefStore.subscribe, prefStore.get)
          const t = makeT(props !== null && props !== undefined ? props.t : undefined)
          return h(React.Fragment, null,
            h('style', { key: 'whale-css' }, CSS),
            h('div', { className: 'dsh-whale-row' },
              h('div', { className: 'dsh-whale-rowText' },
                h('div', { className: 'dsh-whale-rowTitle' }, t('settings.petTitle')),
                h('div', { className: 'dsh-whale-rowDesc' }, t('settings.petDesc')),
              ),
              h('div', { className: 'dsh-whale-switches' },
                h('button', {
                  type: 'button',
                  role: 'switch',
                  'aria-checked': current.pet ? 'true' : 'false',
                  className: 'dsh-whale-switch',
                  onClick: () => { setPref('pet', !current.pet) },
                },
                  h('span', { className: 'dsh-whale-track', 'aria-hidden': 'true' }, h('span', { className: 'dsh-whale-knob' })),
                  h('span', { className: 'dsh-whale-switchLabel' }, t('settings.pet')),
                ),
              ),
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

        ctx.slots.inject('shell.overlay', () => ctx.slots.register({
          name: 'shell.overlay',
          id: 'whale-notify.pet',
          order: 39,
          locale: NS,
        }, WhalePet))

        ctx.slots.inject('settings.general.item', () => ctx.slots.register({
          name: 'settings.general.item',
          id: 'whale-notify.pet',
          order: 41,
          locale: NS,
        }, WhalePetRow))
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
