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

## The character

Blue gradient hair, the loop cowlick, whale-fin ears, the white ruffled maid
headdress and apron, the navy dress and the big whale tail — the card draws the
community **鲸鱼娘 / 蓝色大肥鱼**, DeepSeek's fan-made personification.

The design traits are documented by the community spec
[deepseek-whalechan](https://github.com/Neko3000/deepseek-whalechan); the character
itself traces back to Bilibili creators
[上善无形](https://space.bilibili.com/4456176) (the original character 溟月) and
[ZipZipPipe](https://space.bilibili.com/4168597) (who merged in the whale and maid
elements).

The drawing here is an **original flat-vector chibi** built from those traits:
plain SVG paths inside `client.js`, no fan artwork copied, traced, or bundled.
It is an unofficial fan work with no affiliation or endorsement from DeepSeek.
The character chain is released under CC BY-NC-SA 4.0, and this rendering follows
it; see [ART_LICENSE.md](ART_LICENSE.md) for the exact attribution line, the code
license (MIT), and the non-commercial term.

Animation is CSS-only on the SVG groups: idle bob, cowlick sway, fin flap, tail
wag, a blink every ~4.6 s, rising steam, and pulsing bubble dots. `prefers-reduced-motion`
turns all of it off.


## Use it

Nothing to open: the chime and the card appear on their own. Both live below
every column in the frame-wide overlay layer, so they do not move the layout.

To turn either half off, open **Settings** (sidebar foot) > **General** >
**Whale alerts**, and use the **Chime** and **Whale card** switches. The choices
persist in this browser (`localStorage`) and apply immediately.

**Try it** beside those switches shows one alert on demand: the first click shows
the finished-turn card with its chime, the next click shows the waiting-for-you
card, and so on. It ignores the two switches on purpose, so the test always plays.

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
