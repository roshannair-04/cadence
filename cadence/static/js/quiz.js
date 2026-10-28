import { get, post, track } from "./api.js";
import { state } from "./state.js";
import { esc, icon, pct, announce, $, $$ } from "./util.js";

const LET = ["A", "B", "C", "D"];
const ROUND = 6;
let cleanup = null;
export function leave() { cleanup && cleanup(); cleanup = null; }

function optionsHtml(q, sel, result) {
  return `<div class="opts" role="radiogroup" aria-label="Answer options">${q.options.map((o, i) => {
    const cls = result ? (i === result.answer ? "right" : i === sel ? "wrong" : "") : "";
    const tag = result ? (i === result.answer ? `<span class="res">${icon("tick", "chip-i")} Correct answer</span>` : i === sel ? `<span class="res">Your answer</span>` : "") : "";
    return `<button type="button" class="opt ${cls}" role="radio" aria-checked="${sel === i}" data-i="${i}" ${result ? "disabled" : ""}><span class="key">${q.options.length === 2 ? (i ? "F" : "T") : LET[i]}</span><span>${esc(o)}</span>${tag}</button>`;
  }).join("")}</div>`;
}
const longStem = (q) => (q.stem.length > 90 ? "long" : "");

/* ───────────────────────── Practice quiz ───────────────────────── */
export async function render(root, params) {
  leave();
  const scope = params.get("scope") || "auto";
  const S = { n: 0, asked: [], res: [], q: null, sel: null, changes: 0, t0: 0, answered: null };
  const scopeLabel = scope === "auto" ? (state.user.mode === "adaptive" ? "Chosen for you" : "Mixed topics") : scope.startsWith("section:") ? "This section" : "This module";

  async function next() {
    if (S.n >= ROUND) return summary();
    try { S.q = await get(`/api/quiz/next?user=${state.user.id}&scope=${encodeURIComponent(scope)}&exclude=${S.asked.join(",")}`); }
    catch (e) { return S.n ? summary() : (root.innerHTML = `<div class="quiz"><div class="panel empty"><b>No questions here yet</b>${esc(e.message)}<a class="btn" href="#/quiz">Mixed quiz</a></div></div>`); }
    S.asked.push(S.q.id); S.sel = null; S.changes = 0; S.answered = null; S.t0 = performance.now();
    track("q_view", S.q.section_id, null, { q: S.q.id, type: S.q.qtype });
    draw();
  }

  function draw() {
    const q = S.q, a = S.answered;
    const dots = Array.from({ length: ROUND }, (_, i) => `<i class="${i < S.res.length ? (S.res[i].correct ? "ok" : "no") : i === S.n ? "now" : ""}"></i>`).join("");
    root.innerHTML = `<div class="quiz">
      <div class="quiz-top"><div><h1 style="font-size:1.5rem">Quiz</h1><span class="muted small">${scopeLabel}</span></div>
        <div class="dots" role="img" aria-label="Question ${S.n + 1} of ${ROUND}">${dots}</div>
        <button class="btn ghost sm" id="endBtn" type="button">End session</button></div>
      <div class="q-card">
        <div class="q-meta"><span>${esc(q.section_title)}</span><span>Question ${S.n + 1} of ${ROUND}</span></div>
        ${q.why ? `<p class="small muted" style="margin:-4px 0 14px">${icon("info", "chip-i")} Why this question: ${esc(q.why)}</p>` : ""}
        <h2 class="q-stem ${longStem(q)}" id="stem">${esc(q.stem)}</h2>
        ${optionsHtml(q, S.sel, a)}
        ${a ? feedbackHtml(a) : `<div class="q-actions"><button class="btn primary" id="checkBtn" type="button" ${S.sel == null ? "disabled" : ""}>Check answer</button><span class="hint-keys">Press ${q.options.length === 2 ? "T or F" : "1–4"}, then Enter</span></div>`}
      </div></div>`;
    $("#endBtn").onclick = () => (S.res.length ? summary() : (location.hash = "#/"));
    if (!a) {
      $$(".opt").forEach((b) => (b.onclick = () => pick(+b.dataset.i)));
      $("#checkBtn").onclick = submit;
    } else {
      $("#nextBtn").onclick = () => { S.n += 1; next(); };
      $("#nextBtn").focus();
    }
  }
  function pick(i) {
    if (S.answered) return;
    if (S.sel != null && S.sel !== i) S.changes += 1;
    S.sel = i;
    $$(".opt").forEach((b) => b.setAttribute("aria-checked", String(+b.dataset.i === i)));
    $("#checkBtn").disabled = false;
  }
  async function submit() {
    if (S.sel == null || S.answered) return;
    const rt = Math.round(performance.now() - S.t0);
    const r = await post("/api/quiz/answer", { user_id: state.user.id, question_id: S.q.id, choice: S.sel, rt_ms: rt, changed: S.changes });
    S.answered = r;
    S.res.push({ correct: r.correct, section_id: r.section_id, title: r.section_title, before: r.mastery_before, after: r.mastery_after });
    announce(r.correct ? "Correct" : "Not quite");
    draw();
  }
  const onKey = (e) => {
    if (e.target.closest("input,textarea,select") || e.metaKey || e.ctrlKey) return;
    if (S.answered) { if (e.key === "Enter") { e.preventDefault(); $("#nextBtn")?.click(); } return; }
    const k = e.key.toLowerCase();
    const idx = S.q?.options.length === 2 ? { t: 0, f: 1, 1: 0, 2: 1 }[k] : { 1: 0, 2: 1, 3: 2, 4: 3, a: 0, b: 1, c: 2, d: 3 }[k];
    if (idx != null && idx < (S.q?.options.length || 0)) { pick(idx); return; }
    if (e.key === "Enter" && S.sel != null && document.activeElement?.tagName !== "BUTTON") { e.preventDefault(); submit(); }
  };
  document.addEventListener("keydown", onKey);
  cleanup = () => document.removeEventListener("keydown", onKey);

  function feedbackHtml(a) {
    const rem = a.remediation && (a.remediation.lead || a.remediation.steps?.length) ? `
      <details class="remedy" open><summary>A simpler way to see it</summary>
        <p style="margin:.6em 0 0"><b>${esc(a.remediation.lead || "")}</b></p>
        ${a.remediation.steps?.length ? `<ol>${a.remediation.steps.map((s) => `<li>${s.label ? `<b>${esc(s.label)}</b>: ` : ""}${esc(s.text)}</li>`).join("")}</ol>` : ""}
        ${a.remediation.analogy ? `<p class="small muted">${esc(a.remediation.analogy)}</p>` : ""}</details>` : "";
    return `<div class="feedback ${a.correct ? "ok" : "no"}" role="status">
      <h3>${a.correct ? icon("tick") + "Correct" : icon("cross") + "Not quite"}</h3>
      <p style="margin:0">${esc(a.explanation)}</p>
      <div class="delta"><span>Section mastery</span><span class="bar"><i style="width:${Math.round(a.mastery_after * 100)}%"></i></span><b class="tnum">${Math.round(a.mastery_before * 100)}% → ${Math.round(a.mastery_after * 100)}%</b></div>
      ${rem}
      <div class="q-actions"><button class="btn primary" id="nextBtn" type="button">${S.n + 1 >= ROUND ? "See results" : "Next question"}</button>
      ${a.correct ? "" : `<a class="btn" href="#/study/${a.section_id}">Re-read this section</a>`}<span class="hint-keys">Enter for next</span></div></div>`;
  }

  function summary() {
    const right = S.res.filter((r) => r.correct).length;
    const bySec = {};
    S.res.forEach((r) => { (bySec[r.section_id] ||= { title: r.title, first: r.before, last: r.after, id: r.section_id }).last = r.after; });
    const miss = S.res.find((r) => !r.correct);
    root.innerHTML = `<div class="quiz"><div class="q-card">
      <p class="muted" style="margin:0 0 6px">Round complete</p>
      <div class="score-big tnum">${right}<span class="muted" style="font-size:1.6rem"> of ${S.res.length}</span></div>
      <p style="margin:10px 0 18px" class="muted">${right === S.res.length ? "Clean sweep." : right >= S.res.length / 2 ? "Good round. The misses are the useful part." : "These sections need another look, and that is what the next round will target."}</p>
      <h3 style="margin-bottom:6px">What moved</h3>
      <ul class="sum-list">${Object.values(bySec).map((s) => `<li><a href="#/study/${s.id}">${esc(s.title)}</a><b class="tnum">${Math.round(s.first * 100)}% → ${Math.round(s.last * 100)}%</b></li>`).join("")}</ul>
      <div class="q-actions" style="margin-top:22px"><a class="btn primary" href="#/quiz?scope=${encodeURIComponent(scope)}" id="again">Another round</a>
        ${miss ? `<a class="btn" href="#/study/${miss.section_id}">Re-read ${esc(miss.title.length > 30 ? miss.title.slice(0, 28) + "…" : miss.title)}</a>` : ""}
        <a class="btn ghost" href="#/">Dashboard</a></div></div></div>`;
    track("quiz_round", null, right / Math.max(1, S.res.length), { n: S.res.length });
    leave();
  }
  await next();
}

/* ───────────────────────── Pre / post knowledge check ───────────────────────── */
export async function renderCheck(root, params) {
  leave();
  const phase = params.get("phase") === "post" ? "post" : "pre";
  const data = await get(`/api/check/${phase}?user=${state.user.id}`);
  const Q = data.questions, ans = [];
  let i = 0, sel = null, t0 = 0;

  root.innerHTML = `<div class="quiz"><div class="q-card">
    <p class="muted" style="margin:0 0 6px">${phase === "pre" ? "Before you study" : "After you study"}</p>
    <h1 style="font-size:1.9rem;margin-bottom:10px">${phase === "pre" ? "Knowledge check" : "Knowledge check, again"}</h1>
    <p>${Q.length} questions, about 4 minutes. You will not see right or wrong answers until the end${phase === "pre" ? ", and not at all on this first run" : ""}. The same questions are used before and after studying, so the difference shows what you learned.</p>
    ${phase === "pre" ? `<p class="muted">Guessing is fine. Skipping the study material first is the point.</p>` : ""}
    ${data.already_done ? `<p class="chip warn">${icon("alert")} You already did this one. Retaking replaces the earlier result.</p>` : ""}
    <div class="q-actions"><button class="btn primary" id="go" type="button">Start</button><a class="btn ghost" href="#/evaluate">Back</a></div></div></div>`;
  $("#go").onclick = show;

  function show() {
    if (i >= Q.length) return finish();
    const q = Q[i]; sel = null; t0 = performance.now();
    root.innerHTML = `<div class="quiz"><div class="quiz-top"><h1 style="font-size:1.5rem">${phase === "pre" ? "Pre-check" : "Post-check"}</h1>
      <div class="dots" role="img" aria-label="Question ${i + 1} of ${Q.length}" style="gap:4px">${Q.map((_, k) => `<i style="width:${Math.max(8, 260 / Q.length)}px" class="${k < i ? "ok" : k === i ? "now" : ""}"></i>`).join("")}</div><span class="muted small">${i + 1} / ${Q.length}</span></div>
      <div class="q-card"><h2 class="q-stem ${longStem(q)}">${esc(q.stem)}</h2>${optionsHtml(q, null, null)}
      <div class="q-actions"><button class="btn primary" id="nx" type="button" disabled>${i + 1 === Q.length ? "Finish" : "Next"}</button></div></div></div>`;
    $$(".opt").forEach((b) => (b.onclick = () => { sel = +b.dataset.i; $$(".opt").forEach((x) => x.setAttribute("aria-checked", String(x === b))); $("#nx").disabled = false; }));
    $("#nx").onclick = () => { ans.push({ question_id: q.id, choice: sel, rt_ms: Math.round(performance.now() - t0) }); i += 1; show(); };
  }
  async function finish() {
    const r = await post("/api/check/submit", { user_id: state.user.id, phase, answers: ans });
    track(`check_${phase}`, null, r.score);
    root.innerHTML = `<div class="quiz"><div class="q-card">
      <p class="muted" style="margin:0 0 6px">${phase === "pre" ? "Pre-check" : "Post-check"} saved</p>
      <div class="score-big tnum">${r.right}<span class="muted" style="font-size:1.6rem"> of ${r.total}</span></div>
      <p class="muted" style="margin:10px 0 18px">${phase === "pre" ? "Now study. Use the notes and quizzes for about 15 minutes, then take the check again." : "Compare with your first result on the Study protocol page."}</p>
      <div class="q-actions"><a class="btn primary" href="${phase === "pre" ? "#/" : "#/evaluate"}">${phase === "pre" ? "Start studying" : "Continue to the survey"}</a></div></div></div>`;
  }
}
