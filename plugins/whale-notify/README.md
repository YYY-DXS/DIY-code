# Whale alerts

A chime and the community whale girl (鲸鱼娘) for the two moments you are not
looking at the page: a turn just finished, or DSH is waiting for you to answer
something.

## What it does

- **Turn finished** — a warm two-note "bloop"; the whale girl blinks and holds up
  a bowl of white rice with steam rising.
- **Waiting for you** — a brighter three-note chime; she stands beside a "…"
  speech bubble. This covers `ask_user_question`, plan reviews, and approval
  requests.
- Each card names the Session it belongs to; click the card to open that Session.
  The card fades after seven seconds, pauses while you hover it, and dismisses
  from its × button.
- Inner subagent Sessions never alert, so one task cannot chime twice.
- **Floating mascot** — the same whale girl stands in the corner of the window with
  the live status: **运行中 / 等你回复 / 刚完成 / 空闲** (Running / Waiting for you /
  Finished / Idle). Drag her anywhere and the position is remembered; the × in her
  corner hides her, and **Settings > General > Floating mascot** brings her back.

## The character

The card shows the community **鲸鱼娘 / 蓝色大肥鱼**, DeepSeek's fan-made
personification: blue gradient hair, loop cowlick, whale-fin ears, white ruffled
maid headdress and apron, navy dress, big whale tail. Two states are used — the
finished-turn card shows her **happy, arms up**, and the waiting-for-you card shows
her **holding a "?" sign**.

The artwork is **metsh's render** of that character from the open-source asset pack
[`dsh-task-mascot`](https://www.npmjs.com/package/dsh-task-mascot)
(`assets/packs/dafeiyu`), released under **CC BY-NC-SA 4.0**. This plugin only
crops, downscales (256 → 192 px) and re-encodes the frames to WebP, then embeds them
as data URIs so the card needs no extra request: no retouching, no recolouring.

The character traces back to Bilibili creators
[上善无形](https://space.bilibili.com/4456176) (the original character 溟月) and
[ZipZipPipe](https://space.bilibili.com/4168597) (whale elements plus the maid
outfit). Full attribution, the share-alike term and the non-commercial limit are in
[ART_LICENSE.md](ART_LICENSE.md): the artwork is CC BY-NC-SA 4.0, the code stays
MIT. It is an unofficial fan work — no affiliation with or endorsement from
DeepSeek.

Motion stays at the image level: a slow bob-with-breath every 3.6 s, plus the card's
slide-in. `prefers-reduced-motion` turns both off.



## Use it

Nothing to open: the chime and the card appear on their own. Both live below
every column in the frame-wide overlay layer, so they do not move the layout.

To turn either half off, open **Settings** (sidebar foot) > **General** >
**Whale alerts**, and use the **Chime** and **Whale card** switches. The choices
persist in this browser (`localStorage`) and apply immediately.

**Try it** beside those switches shows one alert on demand: the first click shows
the finished-turn card with its chime, the next click shows the waiting-for-you
card, and so on. It ignores the two switches on purpose, so the test always plays.

## Desktop widget (Windows)

`index.js` also spawns a separate **PowerShell + WPF** process: a borderless,
transparent, always-on-top window with the whale girl at the bottom-right corner
of the desktop. It reads `%TEMP%\dsh-whale-pet\state.json`, which the Host
rewrites on every transition, so the pose, the chip and the voice line follow the
run without touching DSH itself.

- **Drag** her anywhere; the position is remembered in `widget.json` next to the
  state file. The **×** closes her for this DSH session.
- **关** (power) arms the shutdown: with it lit, the next finished run shows a
  **60 秒后关机 · 点我取消** countdown and then schedules the OS shutdown
  (`shutdown /s /t 15`). Click the countdown to cancel. Armed state persists;
  it is **off by default** and disarms itself after firing.
- Voice: ten pre-synthesised lines (see `assets/voice`) — one short line per state
  change, plus a random line every ten minutes while idle or running.
- The Host half starts this process when the plugin activates, so a freshly
  installed or edited bundle needs **one DSH restart** to take over spawning.
  Disabling the plugin closes the window and cancels a pending shutdown.

The script requires Windows PowerShell (present on every Windows install) and
desktop WPF; no extra dependency, no DSH patching.

## How it knows

The Web client already keeps one status snapshot per Session for the sidebar:
whether the agent is running, which interaction is waiting for the user, and
which background stop is unread. This plugin subscribes to that snapshot and
announces only the two edges above; it writes no Session events, sends no
network requests, and adds no model-facing tools or prompt text.

The first snapshot after a page load is treated as a baseline, so reloading does
not replay alerts for work that was already waiting.

## Limitations

- Browser only: the chime uses Web Audio, so it obeys the browser's autoplay
  rule. Until you have clicked or typed in the page once, the card still appears
  but the sound may stay silent; a card is never suppressed by the audio state.
- The chime is synthesized in the page. It is muted when the browser tab is
  muted or the system volume is off.
- Alerts are not duplicated into the OS notification center.

## Install

The bundle is a local directory. In **Plugins**, choose **Add plugin** and pick
this directory, then keep its row enabled. The Host half registers nothing, so
the next page load (or the plugin's own HMR update) is enough — no restart.
