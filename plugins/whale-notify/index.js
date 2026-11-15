/**
 * Host half of the whale-alert bundle.
 *
 * All behavior lives in the browser half: `dsh-client-ui-session` already
 * publishes one status snapshot per Session (running, the pending interaction
 * awaiting the user, and unread completions), which the Web UI is subscribed to
 * anyway. The Host therefore registers nothing and loads no model-facing code;
 * it exists only so the bundle has a Host row.
 */
export function apply() {}
