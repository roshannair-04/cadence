import { get, post, track } from "./api.js";
import { state } from "./state.js";
import { esc, icon, bin, pct, announce, toast, $, $$ } from "./util.js";
import { shortModule } from "./dashboard.js";

// ---- dwell-time tracking: counts only time the tab is visible -------------
const sess = { id: null, since: 0, acc: 0 };
function pause() { if (sess.since) { sess.acc += performance.now() - sess.since; sess.since = 0; } }
function resume() { if (sess.id && !sess.since) sess.since = performance.now(); }
export function closeSession() {
  if (!sess.id) return;
  pause();
  if (sess.acc > 1500) track("section_close", sess.id, Math.round(sess.acc));
  sess.id = null; sess.acc = 0;
  if ("speechSynthesis" in window) speechSynthesis.cancel();
}
document.addEventListener("visibilitychange", () => (document.hidden ? pause() : resume()));
addEventListener("pagehide", closeSession);

const highlight = (text, terms) => {
  let out = esc(text);
  for (const t of terms) {
    const re = new RegExp(`(?<![\\w])(${esc(t.term).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})(?![\\w])`, "i");
    out = out.replace(re, (m) => `<mark class="term" data-term="${esc(t.term)}">${m}</mark>`);
  }
  return out;
};

function blocksHtml(blocks, terms, missed) {
  const isMissed = (b) => missed.some((m) => m && ((b.label || "").toLowerCase().includes(m.toLowerCase()) || (b.text || "").toLowerCase().includes(m.toLowerCase().slice(0, 36))));
  const flag = (inner, b) => (isMissed(b) ? `<div class="flag"><span class="flag-note">From a question you missed</span><br>${inner}</div>` : inner);
  let html = "", list = [], facts = [], rows = [], head = null;
  const flush = () => {
    if (list.length) { html += `<ul class="points">${list.join("")}</ul>`; list = []; }
    if (facts.length) { html += `<dl>${facts.join("")}</dl>`; facts = []; }
    if (rows.length || head) {
      html += `<table class="data">${head ? `<thead><tr>${head.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>` : ""}<tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${highlight(c, terms)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
      rows = []; head = null;
    }
  };
  for (const b of blocks) {
    if (b.type === "table_head") { flush(); head = b.cells; continue; }
    if (b.type === "table_row") { if (list.length || facts.length) flush(); rows.push(b.cells); continue; }
    if (rows.length || head) flush();
    if (b.type === "point") { if (facts.length) flush(); list.push(`<li>${flag(highlight(b.text, terms), b)}</li>`); }
    else if (b.type === "fact") { if (list.length) flush(); facts.push(`<div class="fact"><dt>${highlight(b.label, terms)}</dt><dd>${flag(highlight(b.text, terms), b)}</dd></div>`); }
    else if (b.type === "heading") { flush(); html += `<h3 class="sub">${highlight(b.text, terms)}</h3>`; }
    else { flush(); html += `<p class="blk">${flag(highlight(b.text, terms), b)}</p>`; }
  }
  flush();
  return html;
}

function simpleHtml(s, source, model) {
  if (!s || !s.lead) return `<p>No simpler version is available for this section yet.</p>`;
  return `<div class="simple">
    <p class="lead">${esc(s.lead)}</p>
    ${s.steps?.length ? `<ol>${s.steps.map((x) => `<li>${x.label ? `<b>${esc(x.label)}</b>: ` : ""}${esc(x.text)}</li>`).join("")}</ol>` : ""}
    ${s.analogy ? `<div class="analogy"><b>Think of it like this:</b> ${esc(s.analogy)}</div>` : ""}
    ${s.hook ? `<p class="hook">${esc(s.hook)}</p>` : ""}
    <p class="src-note">${source === "llm" ? `Rewritten by the local model${model ? ` (${esc(model)})` : ""} from your course notes.` : "Condensed automatically from your course notes. Start Ollama for plain-language rewrites with analogies."}</p></div>`;
}

export async function render(root, params, secId) {
  closeSession();
  if (!secId) {
    const d = await get(`/api/dashboard?user=${state.user.id}`);
    const t = d.next_up[0];
    location.replace(`#/study/${t ? t.section : d.map[0].sections[0].id}`);
    return;
  }
  const [s, dash] = await Promise.all([get(`/api/section/${secId}?user=${state.user.id}`), get(`/api/dashboard?user=${state.user.id}`)]);
  const adaptive = state.user.mode === "adaptive";
  let layer = s.layer, simple = s.simple, simpleSource = s.simple_source, bannerOn = !!s.banner, usedSimpler = false;
  const model = state.status?.llm?.model;
  const byId = Object.fromEntries(dash.map.flatMap((m) => m.sections.map((x) => [x.id, x])));
  const modCur = dash.map.find((m) => m.sections.some((x) => x.id === s.id));

  root.innerHTML = `
  <div class="study">
    <nav class="toc" aria-label="Sections">${dash.map.map((m) => `
      <details ${m === modCur ? "open" : ""}><summary>${esc(shortModule(m.title))}</summary><ul>${m.sections.map((x) =>
        `<li><a href="#/study/${x.id}" ${x.id === s.id ? 'aria-current="page"' : ""}><span class="pip" data-bin="${bin(x.p, x.seen)}"></span><span>${esc(x.title)}</span></a></li>`).join("")}</ul></details>`).join("")}</nav>

    <article class="reader" aria-labelledby="secTitle">
      <div class="crumb">${esc(s.module)}</div>
      <h1 id="secTitle">${esc(s.title)}</h1>
      <div class="reader-meta"><span>${s.minutes} min read</span><span aria-hidden="true">·</span><span>${esc(s.ref)}</span>
        ${s.state.due ? `<span class="chip warn">${icon("refresh")}Due for review</span>` : ""}</div>
      <div class="toolbar">
        <div class="seg" role="group" aria-label="Detail level">
          <button type="button" data-layer="glance">Key points</button><button type="button" data-layer="notes">Notes</button><button type="button" data-layer="deep">Deep dive</button>
        </div>
        <button class="btn sm" type="button" id="simplerBtn" aria-pressed="false">${icon("spark")} Explain it simpler</button>
        ${"speechSynthesis" in window ? `<button class="btn sm ghost" type="button" id="listenBtn" aria-pressed="false">${icon("ear")} Listen</button>` : ""}
      </div>
      <div id="banner"></div>
      <div class="prose" id="prose" tabindex="-1"></div>
      <div class="endcap" id="endcap">
        <a class="btn primary" href="#/quiz?scope=section:${s.id}">Test yourself · ${s.n_questions} questions</a>
        ${s.prev ? `<a class="btn ghost" href="#/study/${s.prev.id}">Previous</a>` : ""}${s.next ? `<a class="btn" href="#/study/${s.next.id}">Next: ${esc(s.next.title.length > 34 ? s.next.title.slice(0, 32) + "…" : s.next.title)}</a>` : ""}
      </div>
    </article>

    <aside class="margin" aria-label="Margin notes">
      <section><div class="state-box"><div class="ring-wrap"><div class="ring" style="--p:${Math.round(s.state.p * 100)}"></div><span style="position:absolute;font:800 .85rem var(--font-head)">${Math.round(s.state.p * 100)}%</span></div>
        <div><b>Your mastery</b><div class="small muted">${s.state.attempts ? `${s.state.attempts} answered · recall ${pct(s.state.r)}` : s.state.reads ? "Read, not tested yet" : "Not started"}</div></div></div></section>
      ${s.terms.length ? `<section><h3>Key terms</h3><ul class="terms">${s.terms.map((t, i) => `<li><button type="button" aria-expanded="false" aria-controls="def${i}" data-i="${i}">${esc(t.term)}</button><div class="def" id="def${i}" hidden>${esc(t.definition)}</div></li>`).join("")}</ul></section>` : ""}
      ${s.prompts.length ? `<section><h3>Check yourself</h3><ul class="related" style="color:var(--ink-2)">${s.prompts.map((p) => `<li>${esc(p)}</li>`).join("")}</ul></section>` : ""}
      ${s.related.length ? `<section><h3>Related sections</h3><ul class="related">${s.related.map((r) => `<li><a href="#/study/${r.id}">${esc(r.title)}</a></li>`).join("")}</ul></section>` : ""}
    </aside>
  </div>`;

  const prose = $("#prose"), bannerEl = $("#banner");
  const body = (l) => {
    if (l === "glance") return `<h3 class="sub">The short version</h3><ul class="glance points">${s.glance.map((g) => `<li>${highlight(g, s.terms)}</li>`).join("")}</ul><p class="muted small">Switch to Notes for the full detail.</p>`;
    if (l === "simple") return simpleHtml(simple, simpleSource, model);
    const base = blocksHtml(s.standard, s.terms, s.missed);
    if (l === "notes") return base;
    return base + (s.prompts.length ? `<h3 class="sub">Say it in your own words</h3><ul class="points">${s.prompts.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>` : "") +
      (s.related.length ? `<h3 class="sub">Connects to</h3><ul class="points">${s.related.map((r) => `<li><a href="#/study/${r.id}">${esc(r.title)}</a></li>`).join("")}</ul>` : "");
  };
  const paint = () => {
    prose.innerHTML = body(layer);
    $$("[data-layer]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.layer === layer)));
    $("#simplerBtn").setAttribute("aria-pressed", String(layer === "simple"));
    bannerEl.innerHTML = bannerOn && s.banner ? `<div class="banner" role="status">${icon("info")}<div><p>${esc(s.banner)}</p><button class="btn sm" type="button" id="bannerBtn">${layer === "simple" ? "Show the standard notes" : "Show the full notes"}</button></div></div>` : "";
    const bb = $("#bannerBtn");
    if (bb) bb.onclick = () => { bannerOn = false; setLayer("notes", "banner"); };
  };
  const setLayer = (l, why = "user") => { layer = l; paint(); track("layer", s.id, null, { layer: l, by: why }); announce(`Showing ${l === "simple" ? "the simpler version" : l}`); };
  paint();

  $$("[data-layer]").forEach((b) => (b.onclick = () => { bannerOn = false; setLayer(b.dataset.layer); }));
  $("#simplerBtn").onclick = async () => {
    bannerOn = false;
    if (layer === "simple") return setLayer("notes");
    if (!usedSimpler) { usedSimpler = true; track("simpler", s.id); }
    layer = "simple"; paint();
    if (simpleSource !== "llm" && state.status?.llm?.available) {
      prose.insertAdjacentHTML("afterbegin", `<p class="muted small" id="wait">Asking your local model for a plainer explanation…</p>`);
      try { const r = await post(`/api/simplify/${s.id}`); simple = r.simple; simpleSource = r.source; if (layer === "simple") paint(); } catch (e) { $("#wait")?.remove(); }
    }
  };
  $$(".terms button").forEach((b) => (b.onclick = () => {
    const open = b.getAttribute("aria-expanded") === "true", def = $(`#def${b.dataset.i}`);
    b.setAttribute("aria-expanded", String(!open)); def.hidden = open;
    if (!open) track("term", s.id, null, { term: s.terms[b.dataset.i].term });
  }));
  prose.addEventListener("click", (e) => {
    const m = e.target.closest("mark.term"); if (!m) return;
    const i = s.terms.findIndex((t) => t.term === m.dataset.term); const b = $$(".terms button")[i];
    if (b && b.getAttribute("aria-expanded") !== "true") b.click();
    b?.scrollIntoView({ block: "nearest" });
  });
  const lb = $("#listenBtn");
  if (lb) lb.onclick = () => {
    if (speechSynthesis.speaking) { speechSynthesis.cancel(); lb.setAttribute("aria-pressed", "false"); return; }
    const u = new SpeechSynthesisUtterance(`${s.title}. ${prose.innerText}`); u.onend = () => lb.setAttribute("aria-pressed", "false");
    speechSynthesis.speak(u); lb.setAttribute("aria-pressed", "true"); track("listen", s.id);
  };

  // telemetry for this visit
  sess.id = s.id; sess.acc = 0; sess.since = performance.now();
  track("section_open", s.id, null, { layer: s.layer, mode: state.user.mode });
  let done = false;
  const io = new IntersectionObserver((es) => {
    if (done || !es[0].isIntersecting) return;
    const check = () => {
      pause(); const ms = sess.acc; resume();
      if (ms >= 6000) { done = true; track("read_complete", s.id); io.disconnect(); } else setTimeout(check, 2000);
    };
    check();
  }, { threshold: 0.6 });
  io.observe($("#endcap"));
  window.scrollTo({ top: 0 });
}
