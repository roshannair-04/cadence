import { get, post } from "./api.js";
import { esc, icon, toast, announce, confirmBox, $ } from "./util.js";

async function send(files) {
  const fd = new FormData();
  [...files].forEach((f) => fd.append("files", f));
  const r = await fetch("/api/materials", { method: "POST", body: fd });
  if (!r.ok) throw new Error(`Upload failed (${r.status})`);
  return r.json();
}

export async function render(root) {
  const docs = await get("/api/documents");
  const total = docs.reduce((a, d) => a + d.sections, 0);
  root.innerHTML = `<header class="page-head"><div><h1>Your material</h1>
    <p>${docs.length ? `${docs.length} file${docs.length === 1 ? "" : "s"}, ${total} sections.` : "Add your lecture slides, PDFs or notes and Cadence turns them into layered notes and quizzes."} Adding a file never touches your progress.</p></div></header>
    <label class="drop" id="drop" for="pick"><span class="drop-ico">${icon("upload")}</span>
      <b>Drop files here, or choose them</b><span class="muted small">PDF, PPTX, TXT or MD, up to 40 MB each. Takes a few seconds per file.</span>
      <input id="pick" class="sr" type="file" multiple accept=".pdf,.pptx,.txt,.md"></label>
    <div id="msg" class="small" role="status"></div>
    ${docs.length ? `<ul class="docs">${docs.map((d) => `<li><div><b>${esc(d.title)}</b><div class="muted small">${esc(d.filename)}, ${d.sections} sections, ${d.questions} questions</div></div>
      <button class="btn sm ghost" type="button" data-del="${d.id}" aria-label="Remove ${esc(d.title)}">${icon("trash")} Remove</button></li>`).join("")}</ul>` : ""}`;

  const go = async (files) => {
    if (!files.length) return;
    $("#drop").classList.add("busy");
    $("#msg").textContent = "Reading your files and writing questions...";
    try {
      const r = await send(files);
      const n = r.added.reduce((a, x) => a + x.sections, 0);
      if (r.added.length) toast(`Added ${r.added.length} file${r.added.length === 1 ? "" : "s"}, ${n} sections`);
      announce(r.problems.join(". ") || "Done");
      await render(root);
      if (r.problems.length) $("#msg").innerHTML = r.problems.map((p) => `<div class="bad-note">${icon("info")} ${esc(p)}</div>`).join("");
    } catch (e) { $("#drop").classList.remove("busy"); $("#msg").textContent = e.message; }
  };
  $("#pick").onchange = (e) => go(e.target.files);
  const drop = $("#drop");
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => go(e.dataTransfer.files));
  root.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    const d = docs.find((x) => x.id === +b.dataset.del);
    if (!(await confirmBox(`Remove ${d.title}?`, "This deletes its notes, questions and your progress on it. You can add the file again later, but the progress is gone.", "Remove"))) return;
    await fetch(`/api/documents/${d.id}`, { method: "DELETE" });
    toast("Removed"); render(root);
  }));
}
