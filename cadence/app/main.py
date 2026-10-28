"""FastAPI server: JSON API + the static front end."""
import json
import random
import time
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analytics, build, db, llm, tracing
from .config import MATERIAL_DIR, OLLAMA_MODEL, STATIC_DIR

app = FastAPI(title="Cadence")


@app.on_event("startup")
def startup():
    db.init()
    if db.one("SELECT COUNT(*) n FROM sections")["n"] == 0:
        build.build(MATERIAL_DIR)
    if db.one("SELECT COUNT(*) n FROM users")["n"] == 0:
        with db.tx() as c:
            c.execute("INSERT INTO users(name,mode,created) VALUES('You','adaptive',?)", (time.time(),))


def user_or_404(uid) -> dict:
    u = tracing.get_user(uid)
    if not u:
        raise HTTPException(404, "Unknown participant")
    return u


# ------------------------------------------------------------------ status / users

@app.get("/api/status")
def status():
    st = llm.status()
    return {"llm": st, "sections": db.one("SELECT COUNT(*) n FROM sections")["n"],
            "questions": db.one("SELECT COUNT(*) n FROM questions")["n"],
            "llm_questions": db.one("SELECT COUNT(*) n FROM questions WHERE source='llm'")["n"]}


class ModelIn(BaseModel):
    model: str


@app.post("/api/llm/model")
def set_model(m: ModelIn):
    db.set_meta("llm_model", m.model)
    return llm.status()


@app.get("/api/users")
def users():
    return db.rows("SELECT id,name,mode,clock_offset_days FROM users ORDER BY id")


class UserIn(BaseModel):
    name: str
    mode: str = "adaptive"


@app.post("/api/users")
def create_user(u: UserIn):
    name = u.name.strip()[:40] or "Participant"
    mode = u.mode if u.mode in ("adaptive", "control") else "adaptive"
    with db.tx() as c:
        cur = c.execute("INSERT INTO users(name,mode,created) VALUES(?,?,?)", (name, mode, time.time()))
    return db.one("SELECT id,name,mode,clock_offset_days FROM users WHERE id=?", (cur.lastrowid,))


class UserPatch(BaseModel):
    mode: Optional[str] = None
    skip_days: Optional[float] = None
    reset: Optional[bool] = None


@app.patch("/api/users/{uid}")
def patch_user(uid: int, p: UserPatch):
    u = user_or_404(uid)
    with db.tx() as c:
        if p.mode in ("adaptive", "control"):
            c.execute("UPDATE users SET mode=? WHERE id=?", (p.mode, uid))
        if p.skip_days:
            c.execute("UPDATE users SET clock_offset_days=clock_offset_days+? WHERE id=?", (p.skip_days, uid))
        if p.reset:
            for t in ("mastery", "attempts", "events", "sus"):
                c.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
            c.execute("UPDATE users SET clock_offset_days=0 WHERE id=?", (uid,))
    return db.one("SELECT id,name,mode,clock_offset_days FROM users WHERE id=?", (uid,))


# ------------------------------------------------------------------ your material

EXTS = (".pdf", ".pptx", ".txt", ".md")


@app.get("/api/documents")
def documents():
    return db.rows("SELECT d.id, d.title, d.filename, (SELECT COUNT(*) FROM sections s WHERE s.doc_id=d.id) sections, "
                   "(SELECT COUNT(*) FROM questions q JOIN sections s ON s.id=q.section_id WHERE s.doc_id=d.id) questions "
                   "FROM documents d ORDER BY d.ord")


@app.post("/api/materials")
def upload(files: List[UploadFile] = File(...)):
    MATERIAL_DIR.mkdir(parents=True, exist_ok=True)
    added, problems = [], []
    for f in files:
        name = Path(f.filename or "").name
        if not name.lower().endswith(EXTS):
            problems.append(f"{name or 'file'}: only PDF, PPTX, TXT and MD files are supported"); continue
        if db.one("SELECT 1 x FROM documents WHERE filename=?", (name,)):
            problems.append(f"{name}: already in your library"); continue
        dest = MATERIAL_DIR / name
        data = f.file.read(40 * 1024 * 1024 + 1)
        if len(data) > 40 * 1024 * 1024:
            problems.append(f"{name}: larger than 40 MB"); continue
        dest.write_bytes(data)
        try:
            n = build.build(MATERIAL_DIR, only=[dest], log=lambda *_: None)
        except Exception as e:  # unreadable or corrupt file
            n = 0
        if not n:
            dest.unlink(missing_ok=True)
            problems.append(f"{name}: no readable text found (scanned pages need OCR first)"); continue
        added.append({"file": name, "sections": n})
    return {"added": added, "problems": problems}


@app.delete("/api/documents/{did}")
def delete_document(did: int):
    d = db.one("SELECT * FROM documents WHERE id=?", (did,))
    if not d:
        raise HTTPException(404, "Unknown document")
    ids = "SELECT id FROM sections WHERE doc_id=?"
    with db.tx() as c:
        for t in ("mastery", "attempts", "events"):
            c.execute(f"DELETE FROM {t} WHERE section_id IN ({ids})", (did,))
        c.execute(f"DELETE FROM questions WHERE section_id IN ({ids})", (did,))
        c.execute("DELETE FROM sections WHERE doc_id=?", (did,))
        c.execute("DELETE FROM documents WHERE id=?", (did,))
    (MATERIAL_DIR / d["filename"]).unlink(missing_ok=True)
    return {"ok": True}


# ------------------------------------------------------------------ library & sections

@app.get("/api/library")
def library():
    return analytics.library()


def _wrong_recent(uid, sid):
    return db.one("SELECT COUNT(*) n FROM (SELECT correct FROM attempts WHERE user_id=? AND section_id=? AND phase='practice' "
                  "ORDER BY id DESC LIMIT 4) WHERE correct=0", (uid, sid))["n"]


@app.get("/api/section/{sid}")
def section(sid: int, user: int = Query(...)):
    u = user_or_404(user)
    s = db.one("SELECT * FROM sections WHERE id=?", (sid,))
    if not s:
        raise HTTPException(404, "Unknown section")
    m = tracing.get_mastery(user, sid)
    now = tracing.clock(u)
    wrong = _wrong_recent(user, sid)
    layer, banner = tracing.rec_layer(u, m, wrong)
    deep = db.jl(s["deep"], {})
    related = []
    for rid in deep.get("related", []):
        r = db.one("SELECT id,title FROM sections WHERE id=?", (rid,))
        if r:
            related.append(r)
    missed = []
    if wrong:
        for q in db.rows("SELECT q.evidence FROM attempts a JOIN questions q ON q.id=a.question_id WHERE a.user_id=? AND a.section_id=? "
                         "AND a.correct=0 AND a.phase='practice' ORDER BY a.id DESC LIMIT 4", (user, sid)):
            missed.append(q["evidence"])
    nxt = db.one("SELECT id,title FROM sections WHERE id>? ORDER BY id LIMIT 1", (sid,))
    prv = db.one("SELECT id,title FROM sections WHERE id<? ORDER BY id DESC LIMIT 1", (sid,))
    doc = db.one("SELECT title FROM documents WHERE id=?", (s["doc_id"],))
    return {
        "id": sid, "title": s["title"], "module": doc["title"], "minutes": s["minutes"], "ref": s["source_ref"],
        "glance": db.jl(s["glance"], []), "standard": db.jl(s["standard"], []), "terms": db.jl(s["terms"], []),
        "simple": db.jl(s["simple"], {}), "simple_source": s["simple_source"],
        "prompts": deep.get("prompts", []), "related": related, "missed": missed,
        "state": tracing.section_state(m, now), "layer": layer, "banner": banner,
        "next": nxt, "prev": prv, "n_questions": db.one("SELECT COUNT(*) n FROM questions WHERE section_id=?", (sid,))["n"],
    }


@app.post("/api/simplify/{sid}")
def simplify(sid: int):
    """Ask the local model for a fresh plain-language rewrite; falls back to the stored one."""
    s = db.one("SELECT * FROM sections WHERE id=?", (sid,))
    if not s:
        raise HTTPException(404)
    cur = db.jl(s["simple"], {})
    if s["simple_source"] != "llm" and llm.status()["available"]:
        new = llm.simplify(s)
        if new:
            with db.tx() as c:
                c.execute("UPDATE sections SET simple=?, simple_source='llm' WHERE id=?", (json.dumps(new), sid))
            return {"simple": new, "source": "llm"}
    return {"simple": cur, "source": s["simple_source"]}


# ------------------------------------------------------------------ events

class EventIn(BaseModel):
    user_id: int
    kind: str
    section_id: Optional[int] = None
    value: Optional[float] = None
    meta: Optional[dict] = None


@app.post("/api/events")
def events(e: EventIn):
    u = user_or_404(e.user_id)
    with db.tx() as c:
        c.execute("INSERT INTO events(user_id,kind,section_id,value,meta,ts) VALUES(?,?,?,?,?,?)",
                  (e.user_id, e.kind[:40], e.section_id, e.value, json.dumps(e.meta) if e.meta else None, time.time()))
    if e.kind == "read_complete" and e.section_id:
        tracing.record_read(u, e.section_id)
    return {"ok": True}


# ------------------------------------------------------------------ quiz

def _public_q(q, sec=None):
    return {"id": q["id"], "section_id": q["section_id"], "qtype": q["qtype"], "stem": q["stem"],
            "options": db.jl(q["options"], []), "difficulty": q["difficulty"], "source": q["source"]}


@app.get("/api/quiz/next")
def quiz_next(user: int, scope: str = "auto", exclude: str = ""):
    u = user_or_404(user)
    ex = {int(x) for x in exclude.split(",") if x.strip().isdigit()}
    if scope.startswith("section:"):
        sids = [int(scope.split(":")[1])]
    elif scope.startswith("doc:"):
        sids = [r["id"] for r in db.rows("SELECT id FROM sections WHERE doc_id=?", (int(scope.split(":")[1]),))]
    else:
        sids = [r["id"] for r in db.rows("SELECT id FROM sections ORDER BY id")]
    sids = [s for s in sids if db.one("SELECT 1 x FROM questions WHERE section_id=? LIMIT 1", (s,))]
    picked = tracing.pick_next(u, sids, exclude_q=ex)
    if not picked:
        raise HTTPException(404, "No questions available for this scope")
    q, sid, why = picked
    sec = db.one("SELECT title FROM sections WHERE id=?", (sid,))
    out = _public_q(q)
    out.update({"section_title": sec["title"], "why": why if u["mode"] == "adaptive" else None})
    return out


class AnswerIn(BaseModel):
    user_id: int
    question_id: int
    choice: int
    rt_ms: Optional[float] = None
    changed: int = 0


@app.post("/api/quiz/answer")
def quiz_answer(a: AnswerIn):
    u = user_or_404(a.user_id)
    q = db.one("SELECT * FROM questions WHERE id=?", (a.question_id,))
    if not q:
        raise HTTPException(404)
    correct = int(a.choice == q["answer"])
    before, row = tracing.record_answer(u, q["section_id"], bool(correct), q["qtype"])
    with db.tx() as c:
        c.execute("INSERT INTO attempts(user_id,question_id,section_id,correct,choice,rt_ms,changed,phase,mode,ts) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (a.user_id, q["id"], q["section_id"], correct, a.choice, a.rt_ms, a.changed, "practice", u["mode"], time.time()))
    sec = db.one("SELECT title,simple,simple_source FROM sections WHERE id=?", (q["section_id"],))
    out = {"correct": bool(correct), "answer": q["answer"], "explanation": q["explanation"], "evidence": q["evidence"],
           "section_id": q["section_id"], "section_title": sec["title"],
           "mastery_before": round(before, 3), "mastery_after": round(row["p_known"], 3)}
    if u["mode"] == "adaptive" and not correct:
        out["remediation"] = db.jl(sec["simple"], {})
        out["remediation_source"] = sec["simple_source"]
    return out


# ------------------------------------------------------------------ pre / post knowledge check

@app.get("/api/check/{phase}")
def check_start(phase: str, user: int):
    if phase not in ("pre", "post"):
        raise HTTPException(404)
    user_or_404(user)
    qs = analytics.check_set()
    done = db.one("SELECT COUNT(*) n FROM attempts WHERE user_id=? AND phase=?", (user, phase))["n"]
    return {"phase": phase, "already_done": done > 0, "questions": [_public_q(q) for q in qs]}


class CheckIn(BaseModel):
    user_id: int
    phase: str
    answers: List[dict]


@app.post("/api/check/submit")
def check_submit(c_in: CheckIn):
    u = user_or_404(c_in.user_id)
    if c_in.phase not in ("pre", "post"):
        raise HTTPException(400)
    res, right = [], 0
    with db.tx() as c:
        c.execute("DELETE FROM attempts WHERE user_id=? AND phase=?", (c_in.user_id, c_in.phase))
        for a in c_in.answers:
            q = db.one("SELECT * FROM questions WHERE id=?", (a["question_id"],))
            if not q:
                continue
            ok = int(a.get("choice") == q["answer"])
            right += ok
            c.execute("INSERT INTO attempts(user_id,question_id,section_id,correct,choice,rt_ms,changed,phase,mode,ts) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (c_in.user_id, q["id"], q["section_id"], ok, a.get("choice"), a.get("rt_ms"), 0, c_in.phase, u["mode"], time.time()))
            res.append({"question_id": q["id"], "correct": bool(ok), "answer": q["answer"], "explanation": q["explanation"]})
    n = len(res) or 1
    return {"score": right / n, "right": right, "total": len(res), "results": res}


# ------------------------------------------------------------------ dashboard / evaluation

@app.get("/api/dashboard")
def dashboard(user: int):
    return analytics.dashboard(user_or_404(user))


@app.get("/api/results")
def results():
    return analytics.results()


@app.get("/api/sus/items")
def sus_items():
    return analytics.SUS_ITEMS


class SusIn(BaseModel):
    user_id: int
    answers: List[int]
    comment: Optional[str] = ""


@app.post("/api/sus")
def sus(s: SusIn):
    user_or_404(s.user_id)
    if len(s.answers) != 10:
        raise HTTPException(400, "SUS needs 10 answers")
    score = analytics.sus_score(s.answers)
    with db.tx() as c:
        c.execute("INSERT INTO sus(user_id,answers,score,comment,ts) VALUES(?,?,?,?,?)",
                  (s.user_id, json.dumps(s.answers), score, (s.comment or "")[:1000], time.time()))
    return {"score": score}


@app.get("/api/export/{table}.csv")
def export(table: str, user: Optional[int] = None):
    if table not in ("attempts", "events", "sus"):
        raise HTTPException(404)
    return PlainTextResponse(analytics.export_csv(table, user), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=cadence_{table}.csv"})


# ------------------------------------------------------------------ static

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
