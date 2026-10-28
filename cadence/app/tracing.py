"""The learner model: Bayesian Knowledge Tracing + an exponential forgetting curve + question selection.

Everything here is small and explainable on purpose, because the UI shows learners *why*
the system chose something (a core HCI concern: visibility and user control).
"""
import math
import random
import time

from . import db
from .config import BKT, RETENTION_DUE

DAY = 86400.0


def clock(user) -> float:
    """Learner's clock. 'Skip a day' in the UI moves it forward so spaced repetition can be demoed."""
    return time.time() + (user.get("clock_offset_days") or 0.0) * DAY


def get_user(user_id):
    u = db.one("SELECT * FROM users WHERE id=?", (user_id,))
    return u


def guess_for(qtype):
    return BKT["guess_tf"] if qtype == "true_false" else BKT["guess_mcq"]


def bkt_posterior(p, correct, guess):
    s = BKT["p_slip"]
    if correct:
        num = p * (1 - s)
        den = p * (1 - s) + (1 - p) * guess
    else:
        num = p * s
        den = p * s + (1 - p) * (1 - guess)
    post = num / den if den else p
    return post + (1 - post) * BKT["p_learn"]


def retention(stability, last_seen, now):
    if not last_seen or not stability:
        return 0.0
    days = max(0.0, (now - last_seen) / DAY)
    return math.exp(-days / max(0.05, stability))


def due_at(stability, last_seen):
    """Moment when predicted recall falls to RETENTION_DUE."""
    return last_seen + (-math.log(RETENTION_DUE)) * stability * DAY


def get_mastery(user_id, section_id):
    return db.one("SELECT * FROM mastery WHERE user_id=? AND section_id=?", (user_id, section_id))


def _upsert(user_id, section_id, **kw):
    row = get_mastery(user_id, section_id) or dict(
        user_id=user_id, section_id=section_id, p_known=BKT["p_init"], stability=0.8, last_seen=0.0,
        attempts=0, correct=0, reads=0)
    row.update(kw)
    with db.tx() as c:
        c.execute(
            "INSERT INTO mastery(user_id,section_id,p_known,stability,last_seen,attempts,correct,reads)"
            " VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(user_id,section_id) DO UPDATE SET p_known=excluded.p_known,"
            " stability=excluded.stability,last_seen=excluded.last_seen,attempts=excluded.attempts,"
            " correct=excluded.correct,reads=excluded.reads",
            (user_id, section_id, row["p_known"], row["stability"], row["last_seen"], row["attempts"],
             row["correct"], row["reads"]))
    return row


def record_answer(user, section_id, correct, qtype):
    now = clock(user)
    m = get_mastery(user["id"], section_id) or dict(p_known=BKT["p_init"], stability=0.8, attempts=0, correct=0, reads=0, last_seen=0.0)
    before = m["p_known"]
    p = bkt_posterior(before, correct, guess_for(qtype))
    # spaced-repetition stability: grows when recalled, shrinks after a miss
    S = m["stability"] or 0.8
    S = min(60.0, S * (1.5 + 1.5 * p)) if correct else max(0.4, S * 0.5)
    row = _upsert(user["id"], section_id, p_known=p, stability=S, last_seen=now,
                  attempts=m["attempts"] + 1, correct=m["correct"] + (1 if correct else 0))
    return before, row


def record_read(user, section_id):
    """Finishing a read gives a small head-start, but never counts as mastery."""
    now = clock(user)
    m = get_mastery(user["id"], section_id) or dict(p_known=BKT["p_init"], stability=0.8, attempts=0, correct=0, reads=0, last_seen=0.0)
    p = m["p_known"] + (1 - m["p_known"]) * 0.06 if m["reads"] == 0 else m["p_known"]
    return _upsert(user["id"], section_id, p_known=p, last_seen=m["last_seen"] or now,
                   reads=m["reads"] + 1, stability=m["stability"] or 0.8,
                   attempts=m["attempts"], correct=m["correct"])


# --------------------------------------------------------------------------- selection

def section_state(m, now):
    """Summarise a mastery row for the UI."""
    if not m:
        return dict(p=0.0, r=0.0, seen=False, due=False, attempts=0, reads=0)
    r = retention(m["stability"], m["last_seen"], now) if m["attempts"] else 0.0
    seen = bool(m["attempts"] or m["reads"])
    due = bool(m["attempts"] and r < RETENTION_DUE)
    return dict(p=m["p_known"] if seen else 0.0, r=r, seen=seen, due=due, attempts=m["attempts"], reads=m["reads"])


def priority(m, now, recent_wrong):
    if not m or not (m["attempts"] or m["reads"]):
        return 0.18
    st = section_state(m, now)
    if not m["attempts"]:
        return 0.62                      # read but never checked: good moment to quiz
    return 0.55 * (1 - st["p"]) + 0.35 * (1 - st["r"]) + 0.10 * min(1.0, recent_wrong / 2)


def pick_next(user, section_ids, exclude_q=(), rnd=None):
    """Adaptive: choose the section that needs work, then a question near the learner's level."""
    rnd = rnd or random.Random()
    now = clock(user)
    mode = user["mode"]
    rows = {r["section_id"]: r for r in db.rows("SELECT * FROM mastery WHERE user_id=?", (user["id"],))}
    wrong = {}
    for r in db.rows("SELECT section_id, COUNT(*) n FROM (SELECT section_id, correct FROM attempts WHERE user_id=? AND phase='practice' "
                     "ORDER BY id DESC LIMIT 12) WHERE correct=0 GROUP BY section_id", (user["id"],)):
        wrong[r["section_id"]] = r["n"]
    asked = {r["question_id"]: r["n"] for r in db.rows(
        "SELECT question_id, COUNT(*) n FROM attempts WHERE user_id=? AND phase='practice' GROUP BY question_id", (user["id"],))}
    secs = [s for s in section_ids]
    if not secs:
        return None
    if mode == "control":
        sid = rnd.choice(secs)
        pool = db.rows("SELECT * FROM questions WHERE section_id=?", (sid,))
        pool = [q for q in pool if q["id"] not in exclude_q] or pool
        return (rnd.choice(pool), sid, "Random question from your chosen scope.") if pool else None

    scored = sorted(((priority(rows.get(s), now, wrong.get(s, 0)), s) for s in secs), reverse=True)[:4]
    weights = [max(0.05, sc) ** 2 for sc, _ in scored]
    for _ in range(4):
        sid = rnd.choices([s for _, s in scored], weights=weights)[0]
        m = rows.get(sid)
        p = m["p_known"] if m else BKT["p_init"]
        target = 1 if p < 0.4 else 2 if p < 0.7 else 3
        pool = [q for q in db.rows("SELECT * FROM questions WHERE section_id=?", (sid,)) if q["id"] not in exclude_q]
        if not pool:
            continue
        pool.sort(key=lambda q: (asked.get(q["id"], 0), abs(q["difficulty"] - target), rnd.random()))
        return pool[0], sid, why(m, now, wrong.get(sid, 0), target)
    return None


def why(m, now, recent_wrong, target):
    if not m or not (m["attempts"] or m["reads"]):
        return "A section you haven't studied yet; this is a first look."
    st = section_state(m, now)
    if not m["attempts"]:
        return "You read this section but haven't been checked on it yet."
    if recent_wrong:
        return "You missed a question here recently, so it comes back sooner."
    if st["due"]:
        return f"Predicted recall has dropped to {round(st['r'] * 100)}%, so it is due for review."
    lvl = {1: "an easier", 2: "a medium", 3: "a harder"}[target]
    return f"Your mastery here is about {round(st['p'] * 100)}%, so you get {lvl} question."


def rec_layer(user, m, wrong_recent):
    """Which note layer to open first. Returns (layer, banner) - banner explains the adaptation."""
    if user["mode"] != "adaptive" or not m:
        return "notes", None
    now = clock(user)
    st = section_state(m, now)
    if m["attempts"] >= 1 and wrong_recent >= 1 and st["p"] < 0.55:
        return "simple", (f"You missed {wrong_recent} question{'s' if wrong_recent != 1 else ''} on this section, "
                          "so the simpler version comes first.")
    if m["attempts"] >= 3 and st["p"] >= 0.85 and st["r"] >= 0.7 and wrong_recent == 0:
        return "glance", "You know this well. Showing just the key points. Open the notes any time."
    return "notes", None
