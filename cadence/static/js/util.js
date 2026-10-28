// Small helpers shared by every view.
import { ICONS } from "./icons.js";
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export const esc = (s) => String(s ?? "").replace(/\s[–—]\s/g, ", ").replace(/(\d)[–—](\d)/g, "$1-$2").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const pct = (x, d = 0) => (x == null ? "n/a" : `${(x * 100).toFixed(d)}%`);
export const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

export const icon = (name, cls = "") => `<svg class="ico ${cls}" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true">${ICONS[name] || ""}</svg>`;

/** Map mastery (0..1) to the 7-step ramp; 0 means "not started yet". */
export function bin(p, seen) {
  if (!seen) return 0;
  return clamp(1 + Math.floor(p / 0.15), 1, 7);
}

// --- tooltip -----------------------------------------------------------
const tip = () => document.getElementById("tip");
export function showTip(html, x, y) {
  const t = tip();
  t.innerHTML = html;
  t.hidden = false;
  const r = t.getBoundingClientRect();
  t.style.left = `${clamp(x + 14, 8, innerWidth - r.width - 8)}px`;
  t.style.top = `${y - r.height - 14 < 8 ? y + 18 : y - r.height - 14}px`;
}
export const hideTip = () => { tip().hidden = true; };
export function attachTip(el, htmlFn) {
  el.addEventListener("mousemove", (e) => showTip(htmlFn(), e.clientX, e.clientY));
  el.addEventListener("mouseleave", hideTip);
  el.addEventListener("focus", () => { const r = el.getBoundingClientRect(); showTip(htmlFn(), r.left + r.width / 2, r.top); });
  el.addEventListener("blur", hideTip);
}

export function announce(msg) {
  const l = document.getElementById("live");
  l.textContent = "";
  setTimeout(() => (l.textContent = msg), 30);
}
export function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast";
  t.setAttribute("role", "status");
  t.textContent = msg;
  document.body.append(t);
  setTimeout(() => t.remove(), 2600);
}
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** In-app replacement for window.confirm(). Resolves true when the destructive button is pressed. */
export function confirmBox(title, body, okLabel = "Remove") {
  return new Promise((resolve) => {
    const d = document.createElement("dialog");
    d.className = "confirm";
    d.setAttribute("aria-labelledby", "cfT");
    d.innerHTML = `<form method="dialog"><h2 id="cfT">${esc(title)}</h2><p class="muted">${esc(body)}</p>
      <div class="row-end"><button class="btn" value="cancel" autofocus>Keep it</button><button class="btn danger" value="ok">${esc(okLabel)}</button></div></form>`;
    d.addEventListener("close", () => { resolve(d.returnValue === "ok"); d.remove(); });
    document.body.append(d);
    d.showModal();
  });
}
