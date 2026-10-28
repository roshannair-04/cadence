"""Everything the dashboard and the evaluation page need, computed from the SQLite tables."""
import csv
import io
import math
import statistics
from collections import defaultdict

from . import db, tracing
from .config import RETENTION_DUE

DAY = 86400.0


def library():
    docs = db.rows("SELECT * FROM documents ORDER BY id")
    secs = db.rows("SELECT s.id, s.doc_id, s.ord, s.title, s.minutes, s.source_ref, "
                   "(SELECT COUNT(*) FROM questions q WHERE q.section_id=s.id) nq FROM sections s ORDER BY s.id")
    by = defaultdict(list)
    for s in secs:
        by[s["doc_id"]].append(s)
    return [dict(d, sections=by[d["id"]]) for d in docs]


def _events_by_section(user_id):
    ev = defaultdict(lambda: dict(opens=0, ms=0.0, simpler=0, listen=0))
    for r in db.rows("SELECT kind, section_id, SUM(value) v, COUNT(*) n FROM events WHERE user_id=? AND section_id IS NOT NULL "
                     "GROUP BY kind, section_id", (user_id,)):
        e = ev[r["section_id"]]
        if r["kind"] == "section_open":
            e["opens"] = r["n"]
        elif r["kind"] == "section_close":
            e["ms"] = r["v"] or 0.0
        elif r["kind"] == "simpler":
            e["simpler"] = r["n"]
        elif r["kind"] == "listen":
            e["listen"] = r["n"]
    return ev


def dashboard(user):
    now = tracing.clock(user)
    uid = user["id"]
    docs = library()
    mrows = {r["section_id"]: r for r in db.rows("SELECT * FROM mastery WHERE user_id=?", (uid,))}
    ev = _events_by_section(uid)
    total = 0
    seen = due = mastered = 0
    p_sum = 0.0
    tiles = []
    time_by_doc = []
    sec_title = {}
    for d in docs:
        row = {"id": d["id"], "title": d["title"], "sections": []}
        mins = 0.0
        for s in d["sections"]:
            st = tracing.section_state(mrows.get(s["id"]), now)
            total += 1
            seen += st["seen"]
            due += st["due"]
            mastered += st["p"] >= 0.8 and st["attempts"] >= 2
            p_sum += st["p"]
            sec_title[s["id"]] = s["title"]
            mins += ev[s["id"]]["ms"] / 60000.0
            row["sections"].append({"id": s["id"], "title": s["title"], "p": round(st["p"], 3), "r": round(st["r"], 3),
                                    "seen": st["seen"], "due": st["due"], "attempts": st["attempts"]})
        tiles.append(row)
        time_by_doc.append({"title": d["title"], "minutes": round(mins, 1)})

    att = db.rows("SELECT correct, ts, section_id FROM attempts WHERE user_id=? AND phase='practice' ORDER BY id", (uid,))
    acc_all = (sum(a["correct"] for a in att) / len(att)) if att else None
    last20 = att[-20:]
    acc_recent = (sum(a["correct"] for a in last20) / len(last20)) if last20 else None
    trend = []
    W = 5
    for i in range(W, len(att) + 1):
        w = att[i - W:i]
        trend.append({"n": i, "acc": round(sum(a["correct"] for a in w) / W, 3)})
    mins_total = sum(t["minutes"] for t in time_by_doc)
    days = {int(r["ts"] // DAY) for r in db.rows("SELECT ts FROM events WHERE user_id=?", (uid,))}

    # forgetting curve: average predicted recall over sections that have been quizzed
    curve = []
    quizzed = [m for m in mrows.values() if m["attempts"]]
    if quizzed:
        for t in [0, 0.5, 1, 2, 3, 5, 7, 10, 14]:
            vals = [math.exp(-(max(0.0, (now - m["last_seen"]) / DAY) + t) / max(0.05, m["stability"])) for m in quizzed]
            curve.append({"day": t, "recall": round(sum(vals) / len(vals), 3)})

    # hotspots: where learners struggle (errors, re-reading, asking for the simpler version)
    hot = []
    for sid, m in mrows.items():
        e = ev[sid]
        err = 1 - (m["correct"] / m["attempts"]) if m["attempts"] else 0.0
        rereads = max(0, e["opens"] - 1)
        score = 0.55 * err + 0.2 * min(1, e["simpler"] / 2) + 0.15 * min(1, rereads / 3) + 0.1 * (1 - m["p_known"])
        if m["attempts"] == 0 and e["simpler"] == 0:
            continue
        why = []
        if m["attempts"]:
            why.append(f"{m['attempts'] - m['correct']} of {m['attempts']} answers missed")
        if e["simpler"]:
            why.append(f"simpler version opened {e['simpler']}×")
        if rereads >= 2:
            why.append(f"re-read {rereads}×")
        hot.append({"id": sid, "title": sec_title.get(sid, ""), "score": round(score, 3), "why": ", ".join(why)})
    hot.sort(key=lambda h: -h["score"])
    hot = [h for h in hot if h["score"] > 0.25][:5]

    return {
        "overview": {
            "mastery": round(p_sum / total, 3) if total else 0, "mastered": mastered, "seen": seen, "total": total, "due": due,
            "accuracy": acc_all, "accuracy_recent": acc_recent, "answered": len(att),
            "minutes": round(mins_total, 1), "active_days": len(days),
        },
        "map": tiles, "forgetting": curve, "threshold": RETENTION_DUE, "trend": trend,
        "time": time_by_doc, "hotspots": hot, "next_up": next_up(user, docs, mrows, now, sec_title),
    }


def next_up(user, docs, mrows, now, sec_title):
    order = [s for d in docs for s in d["sections"]]
    items = []
    if user["mode"] == "control":
        for s in order:
            m = mrows.get(s["id"])
            if not m or not (m["reads"] or m["attempts"]):
                items.append({"kind": "learn", "section": s["id"], "title": s["title"], "minutes": s["minutes"],
                              "why": "Next section in the syllabus."})
                break
        return items
    wrong = {r["section_id"]: r["n"] for r in db.rows(
        "SELECT section_id, COUNT(*) n FROM (SELECT section_id, correct FROM attempts WHERE user_id=? AND phase='practice' "
        "ORDER BY id DESC LIMIT 12) WHERE correct=0 GROUP BY section_id", (user["id"],))}
    cand = []
    for s in order:
        m = mrows.get(s["id"])
        if not m or not (m["reads"] or m["attempts"]):
            continue
        st = tracing.section_state(m, now)
        if wrong.get(s["id"]):
            cand.append((1.0 + wrong[s["id"]], "fix", s, "You missed this recently. Read the simpler version, then try again."))
        elif st["due"]:
            cand.append((0.9 + (1 - st["r"]) * 0.1, "review", s, f"Predicted recall is {round(st['r'] * 100)}%. A quick check keeps it fresh."))
        elif not m["attempts"]:
            cand.append((0.8, "check", s, "You read this but haven't tested yourself yet."))
        elif st["p"] < 0.6:
            cand.append((0.6 + (1 - st["p"]) * 0.2, "practise", s, f"Mastery is {round(st['p'] * 100)}%; more practice will lift it."))
    cand.sort(key=lambda x: -x[0])
    for _, kind, s, why in cand[:2]:
        items.append({"kind": kind, "section": s["id"], "title": s["title"], "minutes": s["minutes"], "why": why})
    for s in order:
        m = mrows.get(s["id"])
        if not m or not (m["reads"] or m["attempts"]):
            items.append({"kind": "learn", "section": s["id"], "title": s["title"], "minutes": s["minutes"],
                          "why": "Next new material in the syllabus." if items else "Start here."})
            break
    return items[:3]


# ------------------------------------------------------------------ pre/post checks

CHECK_TYPES = ("match_label", "cloze", "true_false", "cloze_num", "recognize")


def check_set(n=12):
    """Same fixed questions for pre- and post-test so the difference is a real learning gain."""
    docs = library()
    per_doc = []
    for d in docs:
        qs = []
        used_sec = set()
        for q in db.rows("SELECT q.* FROM questions q JOIN sections s ON s.id=q.section_id WHERE s.doc_id=? AND q.source='rules' "
                         "AND q.difficulty<=2", (d["id"],)):
            if q["qtype"] in CHECK_TYPES:
                qs.append(q)
        qs.sort(key=lambda q: (q["id"] * 2654435761) % 1000003)
        picked = []
        for q in qs:
            if q["section_id"] not in used_sec:
                picked.append(q)
                used_sec.add(q["section_id"])
        per_doc.append(picked)
    out = []
    i = 0
    while len(out) < n and any(per_doc):
        lst = per_doc[i % len(per_doc)]
        if lst:
            out.append(lst.pop(0))
        i += 1
        if i > 10000:
            break
    return out


def results():
    users = db.rows("SELECT * FROM users ORDER BY id")
    rows = []
    for u in users:
        uid = u["id"]
        pre = db.rows("SELECT correct FROM attempts WHERE user_id=? AND phase='pre'", (uid,))
        post = db.rows("SELECT correct FROM attempts WHERE user_id=? AND phase='post'", (uid,))
        prac = db.rows("SELECT correct, rt_ms FROM attempts WHERE user_id=? AND phase='practice'", (uid,))
        sus = db.one("SELECT score FROM sus WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,))
        mins = (db.one("SELECT SUM(value) v FROM events WHERE user_id=? AND kind='section_close'", (uid,))["v"] or 0) / 60000
        pre_s = sum(a["correct"] for a in pre) / len(pre) if pre else None
        post_s = sum(a["correct"] for a in post) / len(post) if post else None
        rows.append({
            "user_id": uid, "name": u["name"], "mode": u["mode"], "pre": pre_s, "post": post_s,
            "gain": (post_s - pre_s) if pre_s is not None and post_s is not None else None,
            "practice_n": len(prac), "practice_acc": (sum(a["correct"] for a in prac) / len(prac)) if prac else None,
            "minutes": round(mins, 1), "sus": sus["score"] if sus else None,
        })
    groups = {}
    for mode in ("adaptive", "control"):
        g = [r for r in rows if r["mode"] == mode]

        def mean(key):
            v = [r[key] for r in g if r[key] is not None]
            return (sum(v) / len(v)) if v else None

        def sd(key):
            v = [r[key] for r in g if r[key] is not None]
            return statistics.stdev(v) if len(v) > 1 else None
        groups[mode] = {"n": len(g), "gain": mean("gain"), "gain_sd": sd("gain"), "sus": mean("sus"),
                        "practice_acc": mean("practice_acc"), "minutes": mean("minutes"), "post": mean("post"), "pre": mean("pre")}
    return {"participants": rows, "groups": groups}


SUS_ITEMS = [
    "I think that I would like to use this system frequently.",
    "I found the system unnecessarily complex.",
    "I thought the system was easy to use.",
    "I think that I would need the support of a technical person to be able to use this system.",
    "I found the various functions in this system were well integrated.",
    "I thought there was too much inconsistency in this system.",
    "I would imagine that most people would learn to use this system very quickly.",
    "I found the system very cumbersome to use.",
    "I felt very confident using the system.",
    "I needed to learn a lot of things before I could get going with this system.",
]


def sus_score(answers):
    total = 0
    for i, a in enumerate(answers):
        a = max(1, min(5, int(a)))
        total += (a - 1) if i % 2 == 0 else (5 - a)
    return total * 2.5


def export_csv(table, user_id=None):
    where, args = ("WHERE user_id=?", (user_id,)) if user_id else ("", ())
    sql = {"attempts": "SELECT a.*, u.name, q.qtype, q.difficulty FROM attempts a JOIN users u ON u.id=a.user_id "
                       "JOIN questions q ON q.id=a.question_id " + where.replace("user_id", "a.user_id") + " ORDER BY a.id",
           "events": "SELECT e.*, u.name FROM events e JOIN users u ON u.id=e.user_id " + where.replace("user_id", "e.user_id") + " ORDER BY e.id",
           "sus": "SELECT s.*, u.name, u.mode FROM sus s JOIN users u ON u.id=s.user_id " + where.replace("user_id", "s.user_id")}[table]
    rows = db.rows(sql, args)
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue()
