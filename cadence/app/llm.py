"""Optional local LLM through Ollama (https://ollama.com): free, private, runs on your machine.

    ollama pull qwen2.5:3b          # small and fast; llama3.2:3b or qwen2.5:7b also work
    ollama serve                    # usually already running after install

If Ollama is not running, every function here returns None and the app falls back to the
rule-based engine. Nothing is ever sent to the internet.
"""
import json
import random
import re
import urllib.error
import urllib.request

from . import db, nlp
from .config import OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_URL


def _req(path, payload=None, timeout=5.0):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(OLLAMA_URL.rstrip("/") + path, data=data,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def status():
    """{'available': bool, 'model': str, 'models': [...]}"""
    try:
        tags = _req("/api/tags", timeout=1.5)
        names = [m["name"] for m in tags.get("models", [])]
        model = db.get_meta("llm_model", OLLAMA_MODEL)
        ok = any(n == model or n.split(":")[0] == model.split(":")[0] for n in names)
        return {"available": ok, "reachable": True, "model": model, "models": names}
    except Exception:
        return {"available": False, "reachable": False, "model": db.get_meta("llm_model", OLLAMA_MODEL), "models": []}


def chat_json(system, prompt, model=None, num_predict=900):
    model = model or db.get_meta("llm_model", OLLAMA_MODEL)
    try:
        out = _req("/api/chat", {
            "model": model, "stream": False, "format": "json",
            "options": {"temperature": 0.3, "num_predict": num_predict},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }, timeout=OLLAMA_TIMEOUT)
        txt = out.get("message", {}).get("content", "")
        return json.loads(txt)
    except Exception:
        return None


SYSTEM = ("You are a careful teaching assistant for a university Human-Computer Interaction course. "
          "Use ONLY the supplied course notes. Never invent facts. Reply with a single JSON object and nothing else.")


def simplify(section):
    """Plain-language rewrite with one everyday analogy. Returns dict or None."""
    prompt = (
        f"Course notes titled \"{section['title']}\":\n\"\"\"\n{section['raw'][:2600]}\n\"\"\"\n\n"
        "Explain this to a first-year student who found it confusing. Use short sentences and plain words. "
        "Return JSON: {\"lead\": \"one sentence with the single most important idea\", "
        "\"steps\": [{\"label\": \"short term\", \"text\": \"plain explanation, max 25 words\"}] (3 to 5 items), "
        "\"analogy\": \"one everyday analogy, max 30 words\", \"hook\": \"a memory trick or one-line summary\"}")
    d = chat_json(SYSTEM, prompt)
    if not isinstance(d, dict) or not d.get("lead"):
        return None
    steps = [{"label": str(s.get("label", ""))[:60], "text": str(s.get("text", ""))[:220]}
             for s in d.get("steps", []) if isinstance(s, dict) and s.get("text")][:5]
    return {"lead": str(d["lead"])[:260], "steps": steps, "analogy": str(d.get("analogy", ""))[:260] or None,
            "hook": str(d.get("hook", ""))[:200] or None, "source": "llm"}


def _supported(answer: str, raw: str) -> bool:
    toks = nlp.tokens(answer)
    if not toks:
        return True
    hay = raw.lower()
    hit = sum(1 for t in toks if t in hay)
    return hit / len(toks) >= 0.6


def make_questions(section, n=4):
    prompt = (
        f"Course notes titled \"{section['title']}\":\n\"\"\"\n{section['raw'][:2600]}\n\"\"\"\n\n"
        f"Write {n} multiple-choice questions that test understanding of these notes (not trivia about wording). "
        "Each has exactly 4 options, one correct, and plausible wrong options taken from related ideas. "
        "Return JSON: {\"questions\": [{\"stem\": \"...\", \"options\": [\"..\",\"..\",\"..\",\"..\"], "
        "\"answer\": 0, \"explanation\": \"one sentence citing the notes\"}]} where answer is the index of the correct option.")
    d = chat_json(SYSTEM, prompt, num_predict=1200)
    out = []
    if not isinstance(d, dict):
        return out
    for q in d.get("questions", []):
        try:
            opts = [nlp.tidy(str(o)) for o in q["options"]]
            ans = int(q["answer"])
            stem = nlp.tidy(str(q["stem"]))
            if len(opts) != 4 or len(set(o.lower() for o in opts)) != 4 or not 0 <= ans < 4:
                continue
            if len(stem) < 15 or len(stem) > 260 or any(len(o) > 170 or not o for o in opts):
                continue
            if not _supported(opts[ans], section["raw"]) and not _supported(str(q.get("explanation", "")), section["raw"]):
                continue
            correct = opts[ans]
            random.Random(stem).shuffle(opts)
            out.append({"qtype": "llm_mcq", "stem": stem, "options": opts, "answer": opts.index(correct),
                        "explanation": nlp.tidy(str(q.get("explanation", "")))[:300], "evidence": correct[:40],
                        "difficulty": 2, "source": "llm"})
        except Exception:
            continue
    return out


def retitle(section):
    prompt = (f"Notes:\n\"\"\"\n{section['raw'][:1200]}\n\"\"\"\nGive a clear 2-6 word heading for these notes. "
              "Return JSON: {\"title\": \"...\"}")
    d = chat_json(SYSTEM, prompt, num_predict=60)
    t = nlp.tidy(str(d.get("title", ""))) if isinstance(d, dict) else ""
    return t if 4 <= len(t) <= 60 else None


def enrich_section(sec_id, log=print):
    s = db.one("SELECT * FROM sections WHERE id=?", (sec_id,))
    if not s:
        return
    with db.tx() as c:
        if any(x in s["title"] for x in ("·", "…")) or len(s["title"]) < 8:
            t = retitle(s)
            if t:
                c.execute("UPDATE sections SET title=? WHERE id=?", (t, sec_id))
        simple = simplify(s)
        if simple:
            c.execute("UPDATE sections SET simple=?, simple_source='llm' WHERE id=?", (json.dumps(simple), sec_id))
        c.execute("DELETE FROM questions WHERE section_id=? AND source='llm'", (sec_id,))
        for q in make_questions(s):
            c.execute(
                "INSERT INTO questions(section_id,qtype,stem,options,answer,explanation,evidence,difficulty,source)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (sec_id, q["qtype"], q["stem"], json.dumps(q["options"]), q["answer"], q["explanation"],
                 q["evidence"], q["difficulty"], "llm"))


def enrich_all(log=print):
    st = status()
    if not st["available"]:
        log(f"Ollama model '{st['model']}' not available at {OLLAMA_URL}. "
            "Start it with `ollama serve` and `ollama pull " + st["model"] + "`. Skipping LLM enrichment.")
        return
    ids = [r["id"] for r in db.rows("SELECT id FROM sections ORDER BY id")]
    for i, sid in enumerate(ids, 1):
        enrich_section(sid)
        log(f"  LLM enriched {i}/{len(ids)}")
