"""Build the study library: parse material -> sections -> notes layers -> questions -> SQLite.

Run directly:   python -m app.build            (rule-based engine)
                python -m app.build --llm      (also enrich with the local Ollama model)
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from . import db, generate as gen, ingest, nlp
from .config import MATERIAL_DIR


def fingerprint(files):
    h = hashlib.sha1()
    for p in files:
        st = p.stat()
        h.update(f"{p.name}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()


def build(material_dir=MATERIAL_DIR, use_llm=False, force=False, log=print, only=None):
    """only=[paths] appends those files and leaves everything already in the library (and all progress) untouched."""
    db.init()
    append = only is not None
    files = list(only) if append else ingest.discover(material_dir)
    if not files:
        log(f"No PDF / PPTX / TXT files found in {material_dir}")
        return 0
    fp = fingerprint(files) + ("+llm" if use_llm else "")
    if not append and not force and db.get_meta("fingerprint", "").startswith(fingerprint(files)) and \
            db.one("SELECT COUNT(*) n FROM sections")["n"] > 0:
        if not use_llm or db.get_meta("fingerprint") == fp:
            log("Library is up to date.")
            return db.one("SELECT COUNT(*) n FROM sections")["n"]

    t0 = time.time()
    docs = []
    base = db.one("SELECT COALESCE(MAX(ord),-1)+1 n FROM documents")["n"] if append else 0
    for ord_, p in enumerate(files):
        units = ingest.load_document(p)
        lens = sorted(len(u["text"]) for u in units) or [0]
        sparse = lens[len(lens) // 2] < 330          # image-heavy / one-liner slides: group more of them
        secs = ingest.to_sections(units, min_chars=700 if sparse else None)
        if not secs:
            continue
        docs.append({"path": p, "title": ingest.doc_title(p, units), "ord": base + ord_, "n_units": len(units), "sections": secs})
        log(f"  read {p.name}: {len(units)} pages/slides -> {len(secs)} sections")

    # module order: by the module number in the title when present
    def mod_no(d):
        import re
        m = re.search(r"Module\s*(\d+)", d["title"], re.I)
        return (int(m.group(1)) if m else 99, d["ord"])
    docs.sort(key=mod_no)
    if not docs:
        log("Nothing readable found in that file.")
        return 0
    existing = db.rows("SELECT id, raw, terms FROM sections") if append else []

    all_raw = [r["raw"] for r in existing] + [s["text"] for d in docs for s in d["sections"]]
    corpus = nlp.Corpus(all_raw)

    # pass 1: per-section analysis
    for d in docs:
        for k, s in enumerate(d["sections"]):
            s["i"] = k
            s["facts"] = nlp.extract_facts(s["text"])
            s["stmts"] = nlp.statements(s["text"], s["facts"])
            if ingest.weak_title(s["title"]):
                s["title"] = nlp.auto_title(s["text"], corpus)
            s["vec"] = corpus.vec(s["text"])
            s["term_list"] = nlp.key_terms(s["text"], s["facts"], corpus)
    overrides = {}
    tj = Path(__file__).resolve().parent.parent / "titles.json"
    if tj.exists():
        overrides = {k: v for k, v in json.loads(tj.read_text()).items() if not k.startswith("_")}
    for d in docs:
        for s in d["sections"]:
            s["title"] = overrides.get(s["title"], s["title"])
    all_terms = list(dict.fromkeys([t["term"] for r in existing for t in json.loads(r["terms"] or "[]")]
                                   + [t for d in docs for s in d["sections"] for t in s["term_list"]]))
    for d in docs:
        words = sorted({w for s in d["sections"] for w in __import__("re").findall(r"[A-Za-z][A-Za-z\-]{5,}", s["text"])
                        if w.lower() not in nlp.STOP and corpus.idf(w.lower()) > 2.6}, key=str.lower)
        lines = []
        for s in d["sections"]:
            for ln in s["text"].split("\n"):
                ln = nlp.tidy(nlp.BULLET.sub("", ln))
                ln = ln.split(": ", 1)[1] if ": " in ln[:50] and len(ln.split(": ", 1)[1].split()) >= 4 else ln
                if 4 <= len(ln.split()) <= 18 and " | " not in ln:
                    lines.append((s["i"], ln))
        for s in d["sections"]:
            s["corpus"] = corpus
            s["doc_words"] = words
            s["doc_lines"] = lines

    sid0 = db.one("SELECT COALESCE(MAX(id),0) n FROM sections")["n"] if append else 0
    with db.tx() as c:
        if not append:
            for t in ("questions", "sections", "documents", "mastery", "attempts", "events", "sus"):
                c.execute(f"DELETE FROM {t}")
        sid = sid0
        for d in docs:
            cur = c.execute("INSERT INTO documents(filename,title,ord,n_units) VALUES(?,?,?,?)",
                            (d["path"].name, d["title"], d["ord"], d["n_units"]))
            doc_id = cur.lastrowid
            doc_facts = [f for s in d["sections"] for f in s["facts"]]
            for i, s in enumerate(d["sections"]):
                sid += 1
                s["id"] = sid
                s["doc_id"] = doc_id
                s["i"] = i
        # relatedness across the whole library
        flat = [s for d in docs for s in d["sections"]]
        pool = flat + [{"id": r["id"], "vec": corpus.vec(r["raw"])} for r in existing]
        for s in flat:
            sims = sorted(((nlp.cosine(s["vec"], o["vec"]), o["id"]) for o in pool if o["id"] != s["id"]), reverse=True)
            s["related"] = [oid for sc, oid in sims[:3] if sc > 0.12]

        nq = 0
        for d in docs:
            doc_facts = [f for s in d["sections"] for f in s["facts"]]
            for i, s in enumerate(d["sections"]):
                terms = []
                for t in s["term_list"][:8]:
                    terms.append({"term": t, "definition": gen.shorten(nlp.definition_for(t, s["facts"], s["stmts"]) or "", 190)})
                terms = [t for t in terms if t["definition"]]
                glance = gen.make_glance(s["title"], s["facts"], s["stmts"], corpus, s["vec"])
                standard = gen.structure(s["text"])
                deep = {"prompts": gen.self_explain(terms), "related": s["related"]}
                simple = gen.make_simple(s["title"], s["facts"], s["stmts"], glance)
                minutes = max(1.0, round(len(s["text"].split()) / 170, 1))
                c.execute(
                    "INSERT INTO sections(id,doc_id,ord,title,raw,glance,standard,deep,terms,simple,simple_source,minutes,source_ref)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (s["id"], s["doc_id"], i, s["title"], s["text"], json.dumps(glance), json.dumps(standard),
                     json.dumps(deep), json.dumps(terms), json.dumps(simple), "rules", minutes,
                     ingest.ref_label(s["refs"])))
                qs = gen.build_questions(s, doc_facts, all_terms)
                for q in qs:
                    c.execute(
                        "INSERT INTO questions(section_id,qtype,stem,options,answer,explanation,evidence,difficulty,source)"
                        " VALUES(?,?,?,?,?,?,?,?,?)",
                        (s["id"], q["qtype"], q["stem"], json.dumps(q["options"]), q["answer"], q["explanation"],
                         q["evidence"], q["difficulty"], q["source"]))
                    nq += 1
        db.set_meta("fingerprint", "" if append else fp)
        db.set_meta("built_at", time.time())

    n_sec = len(flat) if append else db.one("SELECT COUNT(*) n FROM sections")["n"]
    log(f"Built {n_sec} sections and {nq} questions in {time.time() - t0:.1f}s")

    if use_llm:
        from . import llm
        llm.enrich_all(log=log)
    return n_sec


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="enrich notes/questions with the local Ollama model")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--material", default=str(MATERIAL_DIR))
    a = ap.parse_args()
    n = build(Path(a.material), use_llm=a.llm, force=a.force)
    sys.exit(0 if n else 1)
