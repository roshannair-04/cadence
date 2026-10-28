import { get, post } from "./api.js";
import { state } from "./state.js";
import { esc, pct, icon, toast, $, $$ } from "./util.js";

const susWord = (s) => (s >= 85 ? "excellent" : s >= 73 ? "good" : s >= 68 ? "about average" : s >= 51 ? "below average" : "poor");
const dpct = (x) => (x == null ? "n/a" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(0)} pts`);

export async function render(root, tab) {
  const res = await get("/api/results");
  const me = res.participants.find((p) => p.user_id === state.user.id) || {};
  const tabs = [["protocol", "Study protocol"], ["survey", "Usability survey"], ["results", "Results"]];
  tab = tabs.some((t) => t[0] === tab) ? tab : "protocol";
  root.innerHTML = `<header class="page-head"><div><h1>Progress check</h1>
    <p>Measure what studying here did for you: a before-and-after knowledge check, then a short usability survey.</p></div>
    <div class="seg" role="tablist" aria-label="Evaluation sections">${tabs.map(([k, l]) => `<button role="tab" aria-selected="${k === tab}" data-tab="${k}" type="button">${l}</button>`).join("")}</div></header>
    <div id="pane"></div>`;
  $$("[data-tab]").forEach((b) => (b.onclick = () => (location.hash = `#/evaluate/${b.dataset.tab}`)));
  const pane = $("#pane");
  if (tab === "protocol") protocol(pane, me);
  else if (tab === "survey") await survey(pane, me);
  else results(pane, res);
}

function protocol(el, me) {
  const mins = Math.round(me.minutes || 0);
  const steps = [
    ["Pre-check", `12 questions on the whole course, no feedback. This sets the baseline.`, me.pre != null, `#/check?phase=pre`, me.pre != null ? `Done · ${pct(me.pre)}` : "Start", me.pre != null],
    ["Study for about 15 minutes", state.user.mode === "adaptive" ? "Read notes and take quizzes. The adaptive version reorders, simplifies and revisits based on what you get wrong." : "Read notes and take quizzes in fixed syllabus order. Nothing adapts.", mins >= 10, `#/`, mins ? `${mins} min so far` : "Open dashboard", false],
    ["Post-check", "The same 12 questions again. The change from the pre-check is the learning gain.", me.post != null, `#/check?phase=post`, me.post != null ? `Done · ${pct(me.post)}` : "Start", me.post != null],
    ["Usability survey", "Ten statements, about two minutes. Gives a System Usability Scale (SUS) score.", me.sus != null, `#/evaluate/survey`, me.sus != null ? `SUS ${me.sus.toFixed(0)}` : "Start", me.sus != null],
  ];
  el.innerHTML = `<div class="grid-2" style="grid-template-columns:minmax(0,1.5fr) minmax(0,1fr)">
    <section class="panel"><div class="panel-head"><div><h2>Your check</h2><p>${state.user.mode === "adaptive" ? "Adaptive version" : "Control version"}. Do these in order.</p></div></div>
      <ol class="steps">${steps.map((s) => `<li class="${s[2] ? "done" : ""}"><div><h3>${s[0]}</h3><p>${s[1]}</p></div><a class="btn ${s[5] ? "ghost" : "sm"}" href="${s[3]}">${s[4]}</a></li>`).join("")}</ol></section>
    <section class="panel"><h2>What this tells you</h2>
      <p class="muted">A before-and-after check shows whether studying here actually moved your score.</p>
      <ul style="padding-left:1.1em;margin:0 0 1em">
        <li>Take the pre-check once, before you start.</li>
        <li>Study for a while: read notes, take quizzes.</li>
        <li>Take the post-check. The change is your learning gain.</li>
        <li>The survey scores how easy Cadence was to use.</li></ul>
      <p class="small muted">Everything stays on this device: every answer, response time, answer change and re-read. Export it as CSV from the Results tab.</p></section></div>`;
}

async function survey(el, me) {
  const items = await get("/api/sus/items");
  if (me.sus != null) { el.innerHTML = `<section class="panel"><h2>Thanks, ${esc(state.user.name)}</h2><p class="score-big tnum">${me.sus.toFixed(1)}</p><p class="muted">SUS score of 100, which is ${susWord(me.sus)}. The usual benchmark is 68.</p><button class="btn" id="redo" type="button">Take it again</button></section>`; $("#redo").onclick = () => { me.sus = null; survey(el, me); }; return; }
  el.innerHTML = `<form class="panel" id="susForm" style="max-width:820px"><div class="panel-head"><div><h2>How was Cadence to use?</h2><p>Rate each statement from 1 (strongly disagree) to 5 (strongly agree).</p></div></div>
    ${items.map((t, i) => `<fieldset class="likert"><legend>${i + 1}. ${esc(t)}</legend><div class="scale">${[1, 2, 3, 4, 5].map((v) => `<label><input type="radio" name="q${i}" value="${v}" required><span class="pill">${v}</span></label>`).join("")}</div><div class="ends"><span>Disagree</span><span>Agree</span></div></fieldset>`).join("")}
    <label for="cm" style="font-weight:700;display:block;margin:16px 0 6px">Anything confusing or annoying? <span class="muted" style="font-weight:400">Optional</span></label><textarea id="cm" rows="3"></textarea>
    <div class="q-actions"><button class="btn primary" type="submit">Submit survey</button></div></form>`;
  $("#susForm").onsubmit = async (e) => {
    e.preventDefault();
    const answers = items.map((_, i) => +new FormData(e.target).get(`q${i}`));
    const r = await post("/api/sus", { user_id: state.user.id, answers, comment: $("#cm").value });
    toast(`Saved. SUS ${r.score.toFixed(1)}`);
    location.hash = "#/evaluate/results";
  };
}

function results(el, res) {
  const me = res.participants.find((p) => p.user_id === state.user.id) || {};
  const row = (k, v) => `<dt>${k}</dt><dd>${v}</dd>`;
  el.innerHTML = `<div class="cmp"><div class="col"><h3>Your numbers</h3><dl>
      ${row("Pre-check", pct(me.pre))}${row("Post-check", pct(me.post))}${row("Learning gain", dpct(me.gain))}${row("Practice answers", me.practice_n ?? 0)}${row("Minutes studied", me.minutes ?? 0)}${row("SUS score", me.sus == null ? "n/a" : me.sus.toFixed(1))}</dl></div>
    <div class="col"><h3>Export your data</h3><p class="muted small">For your report: every answer and every interaction, as spreadsheets.</p>
      <div style="display:flex;gap:8px;flex-wrap:wrap"><a class="btn sm" href="/api/export/attempts.csv" download>Answers (CSV)</a><a class="btn sm" href="/api/export/events.csv" download>Interaction log (CSV)</a></div></div></div>`;
}
