import { get, post, patch, track } from "./api.js";
import { state, display } from "./state.js";
import { $, $$, esc, icon, toast, hideTip, confirmBox } from "./util.js";
import { fallingLeaves } from "./leaves.js";
import * as dashboard from "./dashboard.js";
import * as study from "./study.js";
import * as quiz from "./quiz.js";
import * as evaluate from "./evaluate.js";
import * as library from "./library.js";

const NAV = [["#/", "Dashboard", "dash", "dashboard"], ["#/study", "Study", "book", "study"], ["#/quiz", "Quiz", "quiz", "quiz"], ["#/library", "Material", "books", "library"], ["#/evaluate", "Progress check", "flask", "evaluate"]];
const main = () => document.getElementById("main");

/* ───────── router ───────── */
function parse() {
  const [path, q] = (location.hash.replace(/^#\/?/, "") || "").split("?");
  return { parts: path.split("/").filter(Boolean), params: new URLSearchParams(q || "") };
}
let token = 0;
async function route() {
  const my = ++token;
  hideTip(); study.closeSession(); quiz.leave();
  const { parts, params } = parse();
  const view = parts[0] || "dashboard";
  $$("#nav a").forEach((a) => a.toggleAttribute("aria-current", a.dataset.view === view || (view === "check" && a.dataset.view === "evaluate")) || a.removeAttribute("aria-current"));
  $$("#nav a").forEach((a) => { if (a.hasAttribute("aria-current")) a.setAttribute("aria-current", "page"); });
  const el = main();
  try {
    if (!["library", "evaluate"].includes(view) && !(await get("/api/documents")).length) { location.hash = "#/library"; return; }
    if (view === "dashboard") await dashboard.render(el);
    else if (view === "study") await study.render(el, params, parts[1] ? +parts[1] : null);
    else if (view === "quiz") await quiz.render(el, params);
    else if (view === "check") await quiz.renderCheck(el, params);
    else if (view === "library") await library.render(el);
    else if (view === "evaluate") await evaluate.render(el, parts[1]);
    else el.innerHTML = `<div class="empty"><b>Page not found</b><a class="btn" href="#/">Back to dashboard</a></div>`;
  } catch (e) {
    if (my !== token) return;
    el.innerHTML = `<div class="panel empty"><b>Something went wrong</b>${esc(e.message)}<button class="btn" onclick="location.reload()">Reload</button></div>`;
  }
  if (my === token && view !== "study") { document.title = `${{ dashboard: "Dashboard", quiz: "Quiz", evaluate: "Progress check", library: "Your material", check: "Knowledge check" }[view] || "Cadence"} · Cadence`; }
}

/* ───────── shell ───────── */
function drawShell() {
  $("#brandMark").innerHTML = icon("leaf"); $("#displayIco").innerHTML = icon("sliders");
  $("#nav").innerHTML = NAV.map(([h, l, i, v]) => `<li><a href="${h}" data-view="${v}">${icon(i)}<span>${l}</span></a></li>`).join("");
  const chip = $("#modeChip");
  chip.textContent = state.user.mode === "adaptive" ? "Adaptive version" : "Control version";
  chip.dataset.mode = state.user.mode;
  const st = state.status?.llm;
  $("#llmNote").innerHTML = st?.available ? `<b>Local model on</b><br>${esc(st.model)} writes the simpler explanations.`
    : `<b>Built-in engine</b><br>Run Ollama to add a local model.`;
}
async function setUser(u) {
  state.user = u; try { localStorage.setItem("cadence.user", u.id); } catch (e) {}
  drawShell(); route();
}
async function refreshUsers(keepId) {
  state.users = await get("/api/users");
  const want = keepId ?? state.user?.id;
  state.user = state.users.find((u) => u.id === want) || state.users[0];
}

/* ───────── display & tools popover ───────── */
function openPopover() {
  const pop = $("#popover"), btn = $("#displayBtn"), d = display.load();
  const st = state.status?.llm || {};
  pop.innerHTML = `<h2>Display and tools</h2>
    <div class="row"><label for="dTheme">Theme</label><select id="dTheme"><option value="auto">Match my device</option><option value="light">Light</option><option value="dark">Dark</option></select></div>
    <div class="row"><label for="dFont">Reading font</label><select id="dFont"><option value="atkinson">Atkinson Hyperlegible</option><option value="lexend">Lexend (easier tracking)</option></select></div>
    <div class="row"><label for="dSize">Text size</label><input id="dSize" type="range" min="0.9" max="1.4" step="0.05" value="${d.size || 1}"></div>
    <div class="row"><label for="dLh">Line spacing</label><input id="dLh" type="range" min="1.4" max="2.1" step="0.05" value="${d.spacing || 1.62}"></div>
    <label class="check"><input id="dCon" type="checkbox" ${d.contrast ? "checked" : ""}> Higher contrast</label>
    <label class="check" style="margin:8px 0 14px"><input id="dMot" type="checkbox" ${d.motion === "reduce" ? "checked" : ""}> Reduce motion</label>
    <div class="tools">
      <div class="row" style="margin:0"><label for="tMode">Study version</label><select id="tMode"><option value="adaptive">Adaptive</option><option value="control">Control (no adaptation)</option></select></div>
      <button class="btn sm" id="skip" type="button">Demo: skip ahead one day</button>
      <button class="btn sm" id="reset" type="button">Reset my progress</button>
      ${st.reachable ? `<div class="row" style="margin:6px 0 0"><label for="tModel">Local model</label><select id="tModel">${(st.models.length ? st.models : [st.model]).map((m) => `<option ${m === st.model ? "selected" : ""}>${esc(m)}</option>`).join("")}</select></div>` : `<p class="small muted" style="margin:6px 0 0">No local model found. Install <b>Ollama</b>, run <code>ollama pull qwen2.5:3b</code>, then reload. Everything works without it.</p>`}
    </div>`;
  $("#dTheme", pop).value = d.theme || "auto"; $("#dFont", pop).value = d.font || "atkinson"; $("#tMode", pop).value = state.user.mode;
  const apply = () => {
    const v = { theme: $("#dTheme", pop).value, font: $("#dFont", pop).value, size: +$("#dSize", pop).value, spacing: +$("#dLh", pop).value, contrast: $("#dCon", pop).checked, motion: $("#dMot", pop).checked ? "reduce" : "" };
    display.save(v);
    const r = document.documentElement;
    v.theme === "auto" ? delete r.dataset.theme : (r.dataset.theme = v.theme);
    v.font === "lexend" ? (r.dataset.font = "lexend") : delete r.dataset.font;
    r.style.setProperty("--scale", v.size); r.style.setProperty("--lh", v.spacing);
    v.contrast ? (r.dataset.contrast = "high") : delete r.dataset.contrast;
    v.motion ? (r.dataset.motion = "reduce") : delete r.dataset.motion;
    track("display", null, null, v);
  };
  $$("select,input", pop).forEach((x) => { if (!["tMode", "tModel"].includes(x.id)) x.addEventListener("input", apply); });
  $("#tMode", pop).onchange = async (e) => { const u = await patch(`/api/users/${state.user.id}`, { mode: e.target.value }); await refreshUsers(u.id); drawShell(); route(); toast(`Switched to the ${u.mode} version`); };
  $("#skip", pop).onclick = async () => { await patch(`/api/users/${state.user.id}`, { skip_days: 1 }); toast("Moved one day ahead. Recall estimates have decayed."); route(); };
  $("#reset", pop).onclick = async () => { if (await confirmBox("Reset your progress?", "This erases your mastery, answers and logs. Your material stays.", "Reset")) { await patch(`/api/users/${state.user.id}`, { reset: true }); toast("Progress reset"); route(); } };
  const tm = $("#tModel", pop); if (tm) tm.onchange = async (e) => { state.status.llm = await post("/api/llm/model", { model: e.target.value }); drawShell(); };
  pop.hidden = false; btn.setAttribute("aria-expanded", "true");
  $("#dTheme", pop).focus();
}
function closePopover() { const pop = $("#popover"); if (!pop.hidden) { pop.hidden = true; $("#displayBtn").setAttribute("aria-expanded", "false"); } }

/* ───────── boot ───────── */
async function boot() {
  fallingLeaves();
  [state.status, state.users] = await Promise.all([get("/api/status"), get("/api/users")]);
  state.user = state.users[0];
  drawShell();
  $("#displayBtn").onclick = (e) => { e.stopPropagation(); $("#popover").hidden ? openPopover() : closePopover(); };
  document.addEventListener("click", (e) => { if (!e.target.closest("#popover,#displayBtn")) closePopover(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closePopover(); $("#displayBtn").focus(); } });
  addEventListener("hashchange", route);
  route();
}
boot().catch((e) => { main().innerHTML = `<div class="panel empty"><b>Cannot reach the Cadence server</b>${esc(e.message)}<p class="small">Start it with <code>./run.sh</code> and reload.</p></div>`; });
