import { state } from "./state.js";

async function j(method, url, body) {
  const r = await fetch(url, {
    method, headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return r.json();
}
export const get = (u) => j("GET", u);
export const post = (u, b) => j("POST", u, b || {});
export const patch = (u, b) => j("PATCH", u, b || {});

/** Interaction telemetry. This is what the HCI study analyses. Fire-and-forget. */
export function track(kind, section_id = null, value = null, meta = null) {
  if (!state.user) return;
  fetch("/api/events", {
    method: "POST", headers: { "Content-Type": "application/json" }, keepalive: true,
    body: JSON.stringify({ user_id: state.user.id, kind, section_id, value, meta }),
  }).catch(() => {});
}
