# Whale alerts

A chime and a little whale for the two moments you are not looking at the page:
a turn just finished, or DSH is waiting for you to answer something.

## What it does

- **Turn finished** — a warm two-note "bloop" and a whale that catches a fish snack.
- **Waiting for you** — a brighter three-note chime and a whale with a "…" speech
  bubble. This covers `ask_user_question`, plan reviews, and approval requests.
- Each card names the Session it belongs to; click the card to open that Session.
  The card fades after seven seconds, pauses while you hover it, and dismisses
  from its × button.
- Inner subagent Sessions never alert, so one task cannot chime twice.

## Use it

Nothing to open: the chime and the card appear on their own. Both live below
every column in the frame-wide overlay layer, so they do not move the layout.

To turn either half off, open **Settings** (sidebar foot) > **General** >
**Whale alerts**, and use the **Chime** and **Whale card** switches. The choices
persist in this browser (`localStorage`) and apply immediately.

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
