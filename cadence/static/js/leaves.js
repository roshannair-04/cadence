// Opening animation: a few leaves drift down once when the page loads.
import { icon } from "./util.js";

export function fallingLeaves(n = 16) {
  const r = document.documentElement;
  if (r.dataset.motion === "reduce" || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  r.classList.add("intro");
  const wrap = document.createElement("div");
  wrap.className = "leaves";
  wrap.setAttribute("aria-hidden", "true");
  const tints = ["--m3", "--m4", "--m5", "--m6", "--mark"];
  for (let i = 0; i < n; i++) {
    const size = 16 + Math.random() * 26, fall = 5.5 + Math.random() * 4, delay = Math.random() * 2.2;
    const l = document.createElement("span");
    l.className = "leaf";
    l.style.cssText = `left:${(i + Math.random()) * (100 / n)}%;font-size:${size}px;color:var(${tints[i % tints.length]});` +
      `--fall:${fall}s;--delay:${delay}s;--sway:${(1.6 + Math.random() * 1.6).toFixed(2)}s;--drift:${(18 + Math.random() * 40).toFixed(0)}px;--spin:${(20 + Math.random() * 50).toFixed(0)}deg`;
    l.innerHTML = `<i>${icon("leafFill")}</i>`;
    wrap.append(l);
  }
  const curtain = document.createElement("div");
  curtain.className = "curtain";
  curtain.setAttribute("aria-hidden", "true");
  curtain.innerHTML = `<i class="cl"></i><i class="cr"></i><span class="cmark">${icon("leafFill")}Cadence</span>`;
  document.body.append(curtain, wrap);
  setTimeout(() => { curtain.remove(); wrap.remove(); r.classList.remove("intro"); }, 2200 + 9500);
}
