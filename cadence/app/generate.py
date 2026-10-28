"""Rule-based content engine: turns raw sections into layered notes and quiz questions.

This is the always-available engine. When a local LLM (Ollama) is running, llm.py adds
richer rewrites and extra questions on top of what is produced here.
"""
import hashlib
import random
import re

from . import nlp

# --------------------------------------------------------------------------- helpers


def rng_for(*parts) -> random.Random:
    h = hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()
    return random.Random(int(h[:12], 16))


def shorten(s: str, limit: int) -> str:
    s = nlp.tidy(s)
    if len(s) <= limit:
        return s
    cut = s[:limit]
    for sep in ("; ", ", ", " – ", " - ", " "):
        i = cut.rfind(sep)
        if i > limit * 0.55:
            cut = cut[:i]
            break
    return cut.rstrip(" ,;:–-") + "…"


def mask(text: str, term: str) -> str:
    if len(term) < 4:
        return text
    return re.sub(re.escape(term), "_____", text, flags=re.I)


# --------------------------------------------------------------------------- notes


def structure(raw: str):
    """Turn raw lines into display blocks: heading / fact / point / para."""
    blocks = []
    lines = [l for l in raw.split("\n")]
    header = None
    pending_table = []
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        is_bullet = bool(nlp.BULLET.match(s))
        body = nlp.BULLET.sub("", s).strip()
        if " | " in body:
            cells = [c.strip() for c in body.split(" | ")]
            if header is None:
                header = cells
                blocks.append({"type": "table_head", "cells": cells})
            else:
                blocks.append({"type": "table_row", "cells": cells})
            continue
        header = None
        m = re.match(r"^([^:]{3,60}):\s+(.{12,})$", body)
        if m and nlp._label_ok(m.group(1)):
            blocks.append({"type": "fact", "label": nlp.tidy(m.group(1)), "text": nlp.tidy(m.group(2))})
            continue
        nxt = next((x.strip() for x in lines[i + 1:] if x.strip()), "")
        if not is_bullet and len(body.split()) <= 7 and not body.endswith((".", ",")) and nxt:
            blocks.append({"type": "heading", "text": nlp.tidy(body)})
            continue
        if is_bullet or len(body.split()) <= 24:
            blocks.append({"type": "point", "text": nlp.tidy(body)})
        else:
            blocks.append({"type": "para", "text": nlp.tidy(body)})
    # merge consecutive table pieces are rendered by the UI; drop empty headings at end
    while blocks and blocks[-1]["type"] == "heading":
        blocks.pop()
    return blocks


def make_glance(title, facts, stmts, corpus, svec):
    cands = []
    for f in facts:
        text = f"{f['label']} — {shorten(f['text'], 120)}"
        cands.append((nlp.score_sentence(f["label"] + " " + f["text"], corpus, svec) + 0.05, text))
    for s in stmts:
        cands.append((nlp.score_sentence(s, corpus, svec), shorten(s, 150)))
    cands.sort(key=lambda x: -x[0])
    out, seen = [], []
    for _, t in cands:
        toks = set(nlp.tokens(t))
        if any(len(toks & p) / max(1, len(toks | p)) > 0.5 for p in seen):
            continue
        out.append(t)
        seen.append(toks)
        if len(out) == 3:
            break
    return out


def make_simple(title, facts, stmts, glance):
    """Offline 'simpler' version: one idea first, then plain labelled chips and a recall hook."""
    lead = glance[0] if glance else title
    chips = [f["label"] for f in facts][:6]
    steps = []
    for f in facts[:4]:
        steps.append({"label": f["label"], "text": shorten(f["text"], 90)})
    hook = None
    if len(chips) >= 3:
        initials = "".join(c[0].upper() for c in chips if c and c[0].isalpha())
        if 3 <= len(initials) <= 6:
            hook = f"Recall hook: {' · '.join(chips)} → {initials}"
    elif stmts:
        hook = "Say it in your own words: " + shorten(stmts[0], 100)
    return {"lead": lead, "steps": steps, "hook": hook, "source": "rules"}


def self_explain(terms):
    out = []
    for t in terms[:3]:
        out.append(f"In one sentence, what does “{t['term']}” mean here, and when would you use it?")
    return out


# --------------------------------------------------------------------------- questions

GENERIC_LABELS = {"origin", "example", "examples", "description", "purpose", "why", "steps", "step", "goal", "goals",
                  "note", "notes", "key question", "evidence", "summary", "use", "uses", "task", "tasks", "output",
                  "input", "result", "results", "when", "how", "what", "who", "benefits", "limits", "limitations",
                  "strengths", "weaknesses", "tip", "tips", "idea", "ideas", "definition", "scope", "role", "focus",
                  "assessment", "teaching method", "session", "deliverable", "deliverables", "key insight"}


def good_label(label: str) -> bool:
    l = label.strip().lower()
    if l in GENERIC_LABELS or re.match(r"^(step|phase|stage|case|question|q|part|task|session|module)\s*\d*\b", l):
        return False
    if len(l) < 4 or len(l.split()) > 6:
        return False
    return True


BAD_STATEMENT = re.compile(r"^(case (question|study)|question \d|assignment|presentation|activity|task\b|deliverable|"
                           r"conduct|prepare|submit|choose and|discuss|analy[sz]e|map |design a|write |create a)", re.I)

NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:[.,]\d+)?)(?:\s?[–-]\s?(\d{1,3}(?:[.,]\d+)?))?(?=\s?(?:%|px|x|×|ms|s\b|seconds|users|evaluators|participants|words|items|levels|steps|principles|heuristics|colors|colours|rules|ratio|\b))")


def _distinct(options):
    seen, out = set(), []
    for o in options:
        k = re.sub(r"\W+", "", o.lower())
        if k and k not in seen:
            seen.add(k)
            out.append(o)
    return out


def _finish(qid_key, qtype, stem, correct, distractors, explanation, evidence, difficulty, tf=False):
    opts = _distinct([correct] + distractors)
    if tf:
        opts = ["True", "False"]
    if len(opts) < (2 if tf else 4):
        return None
    opts = opts[:4] if not tf else opts
    rnd = rng_for("shuffle", qid_key)
    if not tf:
        rnd.shuffle(opts)
    return {"qtype": qtype, "stem": stem, "options": opts, "answer": opts.index(correct),
            "explanation": explanation, "evidence": evidence, "difficulty": difficulty, "source": "rules"}


def _similar(pool, target, k, exclude=(), key=lambda x: x, near=()):
    """Pick distractors: items from `near` (same section) first, then the rest by similar length."""
    tw = len(str(key(target)).split()) if not isinstance(target, str) else len(target.split())
    ex = {str(e).lower() for e in exclude}
    nearset = {str(n).lower() for n in near}
    cand = [p for p in pool if str(key(p)).lower() not in ex]
    cand.sort(key=lambda p: (0 if str(key(p)).lower() in nearset else 1, abs(len(str(key(p)).split()) - tw)))
    return cand[: max(k * 2, k)]


def numeric_distractors(m, rnd):
    a, b = m.group(1), m.group(2)

    def num(x):
        return float(x.replace(",", "."))

    def fmt(v, like):
        if "." in like or "," in like:
            return f"{v:.1f}".rstrip("0").rstrip(".")
        return str(int(round(v)))

    if b:
        lo, hi = num(a), num(b)
        span = hi - lo
        cands = [(lo + 1, hi + 1), (max(0, lo - 1), max(1, hi - 1)), (lo, hi + span + 1), (lo * 2, hi * 2), (lo + 2, hi + 3)]
        outs = [f"{fmt(x, a)}–{fmt(y, b)}" for x, y in cands if y > x]
        correct = f"{a}–{b}"
    else:
        v = num(a)
        cands = [v + 1, max(0, v - 1), v * 2, max(0, v / 2), v + 2, v + 5, v * 10]
        outs = [fmt(x, a) for x in cands]
        correct = a
    outs = [o for o in dict.fromkeys(outs) if o != correct]
    rnd.shuffle(outs)
    return correct, outs[:3]


def build_questions(sec, doc_pool, all_terms, per_section=8):
    """sec: dict with id,title,facts,stmts,terms ; doc_pool: facts of the whole document."""
    qs = []
    title = sec["title"]
    facts, stmts = sec["facts"], sec["stmts"]
    labels_doc = [f for f in doc_pool if f["label"].lower() not in {x["label"].lower() for x in facts}]
    labels_same = [f for f in facts]
    term_pool = [t for t in all_terms if 3 < len(t) < 36]

    # A: which label matches this description?
    for f in facts:
        text = mask(f["text"], f["label"])
        if len(text) < 25 or not good_label(f["label"]):
            continue
        pool = [x for x in labels_same if x["label"] != f["label"]] + labels_doc
        pool = [x["label"] for x in pool if good_label(x["label"]) and f["label"].lower() not in x["label"].lower()
                and x["label"].lower() not in f["label"].lower()]
        pool = list(dict.fromkeys(pool))
        near_ = [x["label"] for x in labels_same]
        ds = _similar(pool, f["label"], 3, exclude=[f["label"]], near=near_)
        rnd = rng_for("A", sec["id"], f["label"])
        top = ds[:3] if len(ds) <= 3 else ds[:3]
        q = _finish(f"A{sec['id']}{f['label']}", "match_label",
                    f"Which of these is described by: “{shorten(text, 170)}”?",
                    f["label"], top, f"{f['label']}: {shorten(f['text'], 200)}",
                    f["label"], 1 if len(text) < 90 else 2)
        if q:
            qs.append(q)

    # B: pick the right description for a label (harder: reading heavy)
    for f in [x for x in facts if good_label(x["label"])][:4]:
        mine = shorten(f["text"], 115)
        pool = [x["text"] for x in (labels_same + labels_doc) if x["label"] != f["label"] and len(x["text"]) > 20]
        pool = list(dict.fromkeys(shorten(p, 115) for p in pool))
        near_ = [shorten(x["text"], 115) for x in labels_same]
        ds = _similar(pool, mine, 3, exclude=[mine], near=near_)
        q = _finish(f"B{sec['id']}{f['label']}", "describe",
                    f"In “{title}”, which statement best describes {f['label']}?",
                    mine, ds[:3], f"{f['label']}: {shorten(f['text'], 200)}", f["label"], 3)
        if q:
            qs.append(q)

    # C/D: cloze + true/false on plain statements that contain a known term
    used_terms = set()
    stmts = [s for s in stmts if not BAD_STATEMENT.match(s) and not re.match(r"^[A-Za-z][\w &/'’-]{1,30}:\s", s)]
    for s in stmts:
        cands = [t for t in sec["term_list"] + [x["label"] for x in facts if good_label(x["label"])]
                 if 4 <= len(t) <= 34 and len(re.findall(r"\b" + re.escape(t) + r"\b", s, flags=re.I)) == 1]
        cands = [t for t in cands if t.lower() not in used_terms]
        if not cands:
            continue
        cands.sort(key=lambda t: -len(t))
        term = cands[0]
        # ensure the statement is not just the term itself
        if len(s) - len(term) < 25:
            continue
        pool = [t for t in term_pool if t.lower() != term.lower() and t.lower() not in s.lower()
                and term.lower() not in t.lower() and t.lower() not in term.lower()]
        pool = list(dict.fromkeys(pool))
        ds = _similar(pool, term, 3, exclude=[term])
        rnd = rng_for("C", sec["id"], s)
        rnd.shuffle(ds)
        blank = re.sub(r"\b" + re.escape(term) + r"\b", "_____", s, count=1, flags=re.I)
        kind = rnd.random()
        if kind < 0.6 or len(ds) < 3:
            q = _finish(f"C{sec['id']}{s}", "cloze", f"Fill in the blank: {blank}", term, ds[:3],
                        s, term, 2)
        else:
            if rnd.random() < 0.5:
                q = _finish(f"D{sec['id']}{s}", "true_false", f"True or false: {s}", "True", [],
                            "True. " + s, term, 1, tf=True)
            else:
                wrong = re.sub(r"\b" + re.escape(term) + r"\b", ds[0], s, count=1, flags=re.I)
                q = _finish(f"D{sec['id']}{s}", "true_false", f"True or false: {wrong}", "False", [],
                            f"False. The original says: {s}", term, 1, tf=True)
        if q:
            used_terms.add(term.lower())
            qs.append(q)

    # E: numbers worth remembering
    for s in stmts:
        m = NUM.search(s)
        if not m or len(s.split()) < 8:
            continue
        rnd = rng_for("E", sec["id"], s)
        correct, ds = numeric_distractors(m, rnd)
        if len(ds) < 3:
            continue
        blank = s[: m.start()] + "_____" + s[m.end():]
        q = _finish(f"E{sec['id']}{s}", "cloze_num", f"Fill in the blank: {blank}", correct, ds, s,
                    s[:40], 2)
        if q:
            qs.append(q)
            break

    # F: fallback when a section is thin - blank the most distinctive word in a statement
    if len(qs) < 3:
        corpus = sec.get("corpus")
        for s in stmts:
            if len(qs) >= 3 or corpus is None:
                break
            if not s.endswith("."):
                continue
            words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]{5,}", s) if w.lower() not in nlp.STOP
                     and s.find(w) > 12]
            if not words:
                continue
            w = max(words, key=lambda x: corpus.idf(x.lower()))

            def shape(x):
                return (x[0].isupper(), x.lower().endswith("ing"), x.lower().endswith("ed"),
                        x.lower().endswith("ly"), x.lower().endswith("tion"), x.lower().endswith("s"))
            pool = [t for t in sec.get("doc_words", []) if t.lower() != w.lower() and t.lower() not in s.lower()
                    and shape(t) == shape(w)]
            ds = _similar(pool, w, 3, exclude=[w])
            if len(ds) < 3:
                continue
            q = _finish(f"F{sec['id']}{s}", "cloze", "Fill in the blank: " + re.sub(re.escape(w), "_____", s, count=1),
                        w, ds[:3], s, w, 2)
            if q:
                qs.append(q)

    # G: recognition question - works on any text, used to make sure thin sections are still quizzable
    if len(qs) < 2:
        mine = [ln for i, ln in sec.get("doc_lines", []) if i == sec.get("i")]
        others = [ln for i, ln in sec.get("doc_lines", []) if i != sec.get("i")]
        mine_l = {m.lower() for m in mine}
        others = [o for o in dict.fromkeys(others) if o.lower() not in mine_l]
        rnd = rng_for("G", sec["id"])
        rnd.shuffle(mine)
        for ln in mine[: 2 - len(qs) + 1]:
            if len(qs) >= 2 or len(others) < 3:
                break
            ds = _similar(others, ln, 3, exclude=[ln])
            q = _finish(f"G{sec['id']}{ln}", "recognize",
                        f"Which of these points appears in the notes on “{title}”?",
                        shorten(ln, 110), [shorten(d, 110) for d in ds[:3]],
                        f"“{ln}” is part of this section.", ln[:40], 1)
            if q:
                qs.append(q)

    # keep a balanced, de-duplicated set
    seen, out = set(), []
    rnd = rng_for("order", sec["id"])
    rnd.shuffle(qs)
    qs.sort(key=lambda q: q["difficulty"])
    for q in qs:
        k = re.sub(r"\W+", "", q["stem"].lower())[:80]
        if k in seen:
            continue
        seen.add(k)
        out.append(q)
    # ensure each difficulty tier is represented before cutting
    tiers = {1: [], 2: [], 3: []}
    for q in out:
        tiers[q["difficulty"]].append(q)
    picked = []
    while len(picked) < per_section and any(tiers.values()):
        for d in (1, 2, 3):
            if tiers[d] and len(picked) < per_section:
                picked.append(tiers[d].pop(0))
    return picked
