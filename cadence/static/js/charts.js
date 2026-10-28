// Tiny dependency-free SVG charts. Single series, one axis, thin marks, hover readout, table view.
import { esc, showTip, hideTip, pct } from "./util.js";

const W = 560, H = 240, M = { l: 46, r: 20, t: 14, b: 34 };

export function lineChart(el, pts, o) {
  // o: {x, y, xTicks, xFmt, yFmt, threshold, thresholdLabel, tipFn, ariaLabel, xTitle}
  const xs = pts.map((p) => p[o.x]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs) || 1;
  const sx = (v) => M.l + ((v - x0) / (x1 - x0 || 1)) * (W - M.l - M.r);
  const sy = (v) => H - M.b - v * (H - M.t - M.b);
  const grid = [0, 0.25, 0.5, 0.75, 1].map((g) => `<line class="tick-line" x1="${M.l}" x2="${W - M.r}" y1="${sy(g)}" y2="${sy(g)}"/><text x="${M.l - 8}" y="${sy(g) + 4}" text-anchor="end">${Math.round(g * 100)}%</text>`).join("");
  const xt = (o.xTicks || pts.map((p) => p[o.x])).map((t) => `<text x="${sx(t)}" y="${H - 10}" text-anchor="middle">${esc(o.xFmt ? o.xFmt(t) : t)}</text>`).join("");
  const path = pts.map((p, i) => `${i ? "L" : "M"}${sx(p[o.x]).toFixed(1)},${sy(p[o.y]).toFixed(1)}`).join("");
  const last = pts[pts.length - 1];
  const th = o.threshold != null
    ? `<line class="thresh" x1="${M.l}" x2="${W - M.r}" y1="${sy(o.threshold)}" y2="${sy(o.threshold)}"/><text class="label" x="${W - M.r}" y="${sy(o.threshold) - 6}" text-anchor="end">${esc(o.thresholdLabel)}</text>` : "";
  el.innerHTML = `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.ariaLabel)}">
    ${grid}<line class="axis-line" x1="${M.l}" x2="${W - M.r}" y1="${H - M.b}" y2="${H - M.b}"/>${xt}${th}
    <path class="series" d="${path}"/>
    <line class="cross" y1="${M.t}" y2="${H - M.b}"/><circle class="pt hov" r="5" cx="0" cy="0"/>
    <circle class="pt" r="5" cx="${sx(last[o.x])}" cy="${sy(last[o.y])}"/>
    <text class="label" x="${Math.min(sx(last[o.x]) + 2, W - M.r)}" y="${sy(last[o.y]) - 12}" text-anchor="${sx(last[o.x]) > W - 80 ? "end" : "start"}">${esc(o.yFmt ? o.yFmt(last[o.y]) : pct(last[o.y]))}</text>
    <rect class="hit" x="${M.l}" y="${M.t}" width="${W - M.l - M.r}" height="${H - M.t - M.b}"/></svg></div>`;
  if (o.xTitle) el.querySelector(".chart").insertAdjacentHTML("beforeend", `<div class="small muted" style="text-align:center;margin-top:2px">${esc(o.xTitle)}</div>`);
  const svg = el.querySelector("svg"), cross = svg.querySelector(".cross"), dot = svg.querySelectorAll(".pt")[0], hit = svg.querySelector(".hit");
  hit.addEventListener("mousemove", (e) => {
    const r = svg.getBoundingClientRect();
    const vx = ((e.clientX - r.left) / r.width) * W;
    let best = pts[0];
    for (const p of pts) if (Math.abs(sx(p[o.x]) - vx) < Math.abs(sx(best[o.x]) - vx)) best = p;
    cross.setAttribute("x1", sx(best[o.x])); cross.setAttribute("x2", sx(best[o.x])); cross.style.opacity = 1; dot.style.opacity = 1;
    dot.setAttribute("cx", sx(best[o.x])); dot.setAttribute("cy", sy(best[o.y]));
    showTip(o.tipFn(best), e.clientX, e.clientY);
  });
  hit.addEventListener("mouseleave", () => { cross.style.opacity = 0; dot.style.opacity = 0; hideTip(); });
}

export function barList(el, items, o) {
  const max = Math.max(...items.map((i) => i.value), 0.0001);
  el.innerHTML = `<div class="chart" role="img" aria-label="${esc(o.ariaLabel)}">` + items.map((i) => `
    <div style="display:grid;grid-template-columns:minmax(90px,38%) 1fr 64px;gap:10px;align-items:center;padding:6px 0" data-v="${i.value}" data-t="${esc(i.label)}">
      <div class="small" style="line-height:1.25">${esc(i.label)}</div>
      <div style="height:10px;background:var(--sunk);border-radius:99px;position:relative"><div style="position:absolute;inset:0 auto 0 0;width:${(i.value / max) * 100}%;background:var(--series);border-radius:0 5px 5px 0;min-width:${i.value ? 4 : 0}px"></div></div>
      <div class="small tnum" style="text-align:right;font-weight:700">${esc(o.fmt(i.value))}</div>
    </div>`).join("") + `</div>`;
}

export function tableView(headers, rows) {
  return `<table class="data"><thead><tr>${headers.map((h, i) => `<th class="${i ? "num" : ""}">${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td class="${i ? "num" : ""}">${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

/** Wraps a chart with a "View as table" toggle. render(el) draws the chart; table = {headers, rows}. */
export function withTable(host, render, table) {
  host.innerHTML = `<div class="view"></div><div style="text-align:right;margin-top:6px"><button class="view-toggle" type="button">View as table</button></div>`;
  const view = host.querySelector(".view"), btn = host.querySelector("button");
  let asTable = false;
  const draw = () => { asTable ? (view.innerHTML = tableView(table.headers, table.rows)) : render(view); btn.textContent = asTable ? "View as chart" : "View as table"; btn.setAttribute("aria-pressed", asTable); };
  btn.addEventListener("click", () => { asTable = !asTable; draw(); });
  draw();
}
