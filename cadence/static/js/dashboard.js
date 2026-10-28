import { get } from "./api.js";
import { state } from "./state.js";
import { esc, pct, icon, bin, attachTip } from "./util.js";
import { lineChart, barList, withTable } from "./charts.js";

const KIND = {
  fix: ["Fix what you missed", "wrench"], review: ["Due for review", "refresh"], check: ["Check what you read", "quiz"],
  practise: ["Keep practising", "spark"], learn: ["Next to read", "book"],
};
export const shortModule = (t) => {
  const m = t.match(/Module\s*(\d+)\s*[–—:-]*\s*(.*)/i);
  const s = m ? `M${m[1]}: ${m[2]}` : t;
  return s.length > 40 ? s.slice(0, 38).trimEnd() + "…" : s;
};

export async function render(root) {
  root.innerHTML = `<div class="empty">Loading your dashboard…</div>`;
  const d = await get(`/api/dashboard?user=${state.user.id}`);
  const o = d.overview, adaptive = state.user.mode === "adaptive";
  const top = d.next_up[0], rest = d.next_up.slice(1);
  const nextHtml = top ? `
    <div class="next-main">
      <span class="next-kind">${icon(KIND[top.kind][1])}${KIND[top.kind][0]}</span>
      <h2>${esc(top.title)}</h2>
      <p class="next-why">${esc(top.why)}</p>
      <div class="next-actions">
        <a class="btn mark" href="#/study/${top.section}">Read the notes, ${top.minutes} min</a>
        ${top.kind !== "learn" ? `<a class="btn ghost" href="#/quiz?scope=section:${top.section}">Quiz me on this</a>` : ""}
      </div>
      ${rest.length ? `<div class="next-queue" aria-label="After that">${rest.map((r) => `<a href="#/study/${r.section}"><span class="k">${KIND[r.kind][0].split(" ")[0]}</span><span class="t">${esc(r.title)}</span></a>`).join("")}</div>` : ""}
    </div>` : `<div class="next-main"><span class="next-kind">${icon("tick")}All caught up</span><h2>Nothing is due right now</h2><p class="next-why">Take the post-check from the Study protocol to see how much you have gained.</p><div class="next-actions"><a class="btn mark" href="#/evaluate">Open study protocol</a></div></div>`;

  root.innerHTML = `
    <header class="page-head">
      <div><h1>${state.user.name === "You" ? "Today" : esc(state.user.name)}</h1>
      <p>${adaptive ? "The plan below changes with your answers." : "Control version: a fixed syllabus order, no adaptation."}</p></div>
    </header>
    <div class="stack">
      <section class="next" aria-label="What to do next">${nextHtml}
        <dl class="vitals">
          <div><dt>Mastered</dt><dd class="tnum">${o.mastered}<small>of ${o.total}</small></dd></div>
          <div><dt>Due for review</dt><dd class="tnum">${o.due}</dd></div>
          <div><dt>Accuracy, last 20</dt><dd class="tnum">${o.accuracy_recent == null ? "n/a" : pct(o.accuracy_recent)}</dd></div>
          <div><dt>Time studying</dt><dd class="tnum">${Math.round(o.minutes)}<small>min</small></dd></div>
        </dl>
      </section>

      <section class="panel" aria-labelledby="mapH">
        <div class="panel-head"><div><h2 id="mapH">Mastery map</h2>
          <p>Every tile is one section of your course material. Darker means you know it better. Select a tile to open it.</p></div></div>
        <div class="map" id="map"></div>
        <div class="legend" aria-label="Legend">
          <span class="ramp" aria-hidden="true"><span class="small" style="margin-right:6px">Less</span>${[1,2,3,4,5,6,7].map((i) => `<i style="background:var(--m${i})"></i>`).join("")}<span class="small" style="margin-left:6px">More</span></span>
          <span><span class="sw" style="box-shadow:inset 0 0 0 1.5px var(--line-2);background-image:repeating-linear-gradient(135deg,transparent 0 4px,var(--line) 4px 5px)"></span>Not started</span>
          <span><span class="dot"></span>Due for review</span>
        </div>
      </section>

      <div class="grid-2">
        <section class="panel" aria-labelledby="fcH"><div class="panel-head"><div><h2 id="fcH">How fast you forget</h2><p>Estimated recall of what you have been quizzed on, if you do not review.</p></div></div><div id="fc"></div></section>
        <section class="panel" aria-labelledby="trH"><div class="panel-head"><div><h2 id="trH">Answers getting better?</h2><p>Share correct over each run of 5 answers.</p></div></div><div id="tr"></div></section>
      </div>
      <div class="grid-2">
        <section class="panel" aria-labelledby="tmH"><div class="panel-head"><div><h2 id="tmH">Where your time went</h2><p>Minutes spent reading, by module.</p></div></div><div id="tm"></div></section>
        <section class="panel" aria-labelledby="hsH"><div class="panel-head"><div><h2 id="hsH">Trouble spots</h2><p>Sections with missed answers, repeated re-reads, or requests for the simpler version.</p></div></div><div id="hs"></div></section>
      </div>
    </div>`;

  // mastery map
  const map = root.querySelector("#map");
  map.innerHTML = d.map.map((m) => {
    const started = m.sections.filter((s) => s.seen).length;
    return `<div class="map-row"><h3>${esc(shortModule(m.title))}<small>${m.sections.length} sections, ${started} started</small></h3><div class="tiles">${m.sections.map((s) =>
      `<a class="tile ${s.due ? "due" : ""}" data-bin="${bin(s.p, s.seen)}" href="#/study/${s.id}" data-id="${s.id}" aria-label="${esc(s.title)}: ${s.seen ? Math.round(s.p * 100) + "% mastery" : "not started"}${s.due ? ", due for review" : ""}"></a>`).join("")}</div></div>`;
  }).join("");
  const byId = Object.fromEntries(d.map.flatMap((m) => m.sections.map((s) => [s.id, s])));
  map.querySelectorAll(".tile").forEach((t) => {
    const s = byId[t.dataset.id];
    attachTip(t, () => `<b>${esc(s.title)}</b>${s.seen ? `Mastery ${Math.round(s.p * 100)}%${s.attempts ? `, recall ${Math.round(s.r * 100)}%` : ""}<br>${s.attempts} answered${s.due ? ", due for review" : ""}` : "Not started"}`);
  });

  // forgetting curve
  const fc = root.querySelector("#fc");
  if (d.forgetting.length) {
    withTable(fc, (el) => lineChart(el, d.forgetting, {
      x: "day", y: "recall", xTicks: [0, 1, 3, 7, 14], xFmt: (t) => (t === 0 ? "Now" : `${t}d`), threshold: d.threshold, thresholdLabel: `Review at ${Math.round(d.threshold * 100)}%`,
      ariaLabel: "Estimated recall over the next 14 days if you do not review",
      tipFn: (p) => `<b>${p.day === 0 ? "Right now" : `In ${p.day} day${p.day === 1 ? "" : "s"}`}</b>Estimated recall ${pct(p.recall)}`,
    }), { headers: ["Days from now", "Estimated recall"], rows: d.forgetting.map((p) => [p.day, pct(p.recall)]) });
  } else fc.innerHTML = `<div class="empty"><b>No curve yet</b>Answer a few questions and your recall estimate appears here.<a class="btn sm" href="#/quiz">Start a quiz</a></div>`;

  // accuracy trend
  const tr = root.querySelector("#tr");
  if (d.trend.length > 1) {
    const n0 = d.trend[0].n, n1 = d.trend[d.trend.length - 1].n;
    withTable(tr, (el) => lineChart(el, d.trend, {
      x: "n", y: "acc", xTicks: [...new Set([n0, Math.round((n0 + n1) / 2), n1])], xFmt: (t) => `#${t}`, xTitle: "Answer number",
      ariaLabel: "Accuracy over each run of five answers", tipFn: (p) => `<b>Answers ${p.n - 4}–${p.n}</b>${pct(p.acc)} correct`,
    }), { headers: ["Answers", "Correct"], rows: d.trend.map((p) => [`${p.n - 4}–${p.n}`, pct(p.acc)]) });
  } else tr.innerHTML = `<div class="empty"><b>Not enough answers yet</b>Answer at least 6 questions to see a trend.<a class="btn sm" href="#/quiz">Start a quiz</a></div>`;

  // time
  const tm = root.querySelector("#tm");
  const items = d.time.map((t) => ({ label: shortModule(t.title), value: t.minutes }));
  if (items.some((i) => i.value > 0)) withTable(tm, (el) => barList(el, items, { fmt: (v) => `${v.toFixed(1)} min`, ariaLabel: "Minutes spent per module" }), { headers: ["Module", "Minutes"], rows: items.map((i) => [i.label, i.value.toFixed(1)]) });
  else tm.innerHTML = `<div class="empty"><b>No reading time yet</b>Time is counted while a section is open.<a class="btn sm" href="#/study">Open the notes</a></div>`;

  // hotspots
  const hs = root.querySelector("#hs");
  hs.innerHTML = d.hotspots.length ? `<ul class="hot">${d.hotspots.map((h) => `<li>${icon("alert")}<div><a href="#/study/${h.id}">${esc(h.title)}</a><div class="w">${esc(h.why)}</div></div></li>`).join("")}</ul>`
    : `<div class="empty"><b>Nothing flagged</b>Sections show up here when answers or reading behaviour suggest the notes are not landing.</div>`;
}
