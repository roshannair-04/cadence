"""Small, dependency-free NLP helpers: tokens, TF-IDF, facts, key terms."""
import math
import re
from collections import Counter

STOP = set("""a about above after again all also am an and any are as at be because been before being below between both
but by can could did do does doing down during each few for from further had has have having he her here hers him his
how i if in into is it its just may me more most my no nor not now of off on once only or other our out over own same
she should so some such than that the their theirs them then there these they this those through to too under until up
very was we were what when where which while who whom why will with would you your yours via per eg ie etc can must
use used using uses""".split())

BULLET = re.compile(r"^\s*(?:[•\-–—*▪●○◦]|\d{1,2}[.)])\s*")
ACRONYM = re.compile(r"\b[A-Z]{2,6}s?\b")


def tokens(text: str):
    return [w for w in re.findall(r"[a-z][a-z0-9'\-]{1,}", text.lower()) if w not in STOP]


def sentences(text: str):
    """Split into sentence-like statements, respecting bullets and line breaks."""
    out = []
    for line in text.split("\n"):
        line = BULLET.sub("", line).strip()
        if not line:
            continue
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"(])", line)
        for p in parts:
            p = p.strip()
            if len(p) >= 3:
                out.append(p)
    return out


def tidy(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(" •-–—;,")
    return s


class Corpus:
    """Document frequencies over sections, used for TF-IDF weighting."""

    def __init__(self, texts):
        self.n = max(1, len(texts))
        self.df = Counter()
        for t in texts:
            for w in set(tokens(t)):
                self.df[w] += 1

    def idf(self, w):
        return math.log((1 + self.n) / (1 + self.df.get(w, 0))) + 1.0

    def vec(self, text):
        tf = Counter(tokens(text))
        v = {w: (1 + math.log(c)) * self.idf(w) for w, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {w: x / norm for w, x in v.items()}


def cosine(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(w, 0.0) for w, x in a.items())


# ---------- facts ("Label: text" lines and table rows) ----------

LABEL_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 /&'’()\-–+,.]{1,58}$")


def _label_ok(label: str) -> bool:
    label = label.strip()
    if not LABEL_OK.match(label):
        return False
    words = label.split()
    if len(words) > 7 or len(label) < 3:
        return False
    if label.lower().startswith(("http", "e.g", "i.e", "note")):
        return False
    if re.fullmatch(r"[\d\W]+", label):
        return False
    return True


def extract_facts(text: str):
    """Return [{label, text}] from 'Label: description' lines and 'A | B' table rows."""
    facts = []
    lines = [l for l in text.split("\n") if l.strip()]
    header = None
    for raw in lines:
        line = BULLET.sub("", raw).strip()
        if " | " in line:
            cells = [c.strip() for c in line.split(" | ")]
            if header is None:
                header = cells
                continue
            if len(cells) >= 2 and _label_ok(re.sub(r"^\d+\s+", "", cells[0])):
                label = re.sub(r"^\d+\s+", "", cells[0])
                rest = [c for c in cells[1:] if c]
                if rest:
                    if len(rest) == 1:
                        body = rest[0]
                    else:  # multi-column tables: "Column: value; Column: value"
                        body = "; ".join(f"{(header[i + 1] if i + 1 < len(header) else '')}: {v}".strip(": ")
                                         for i, v in enumerate(rest) if v)
                    if len(body) >= 15:
                        facts.append({"label": label, "text": tidy(body), "table": True})
            continue
        header = None
        m = re.match(r"^([^:]{3,60}):\s+(.{18,})$", line)
        if m:
            lab = re.sub(r"^\d+[.)]?\s+", "", m.group(1)).strip()
            if _label_ok(lab):
                facts.append({"label": tidy(lab), "text": tidy(m.group(2)), "table": False})
    # de-duplicate by label
    seen, uniq = set(), []
    for f in facts:
        k = f["label"].lower()
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq


def statements(text: str, facts=None):
    """Plain declarative statements (no table rows, no bare headings) suitable for cloze/true-false."""
    out = []
    for s in sentences(text):
        if " | " in s:
            continue
        if len(s) < 35 or len(s) > 230:
            continue
        if len(s.split()) < 6:
            continue
        if s.endswith("?") or re.search(r"\bSessions?\s+\d+", s) or " • " in s:
            continue
        if ".." in s or "…" in s or any(len(w) > 19 for w in s.split()) or re.search(r"[a-z]{4,}(what|where|who|how)\b", s):
            continue          # fragments from diagram-style slides
        if not is_sentence(s):
            continue
        out.append(tidy(s))
    seen, uniq = set(), []
    for s in out:
        if s.lower() not in seen:
            seen.add(s.lower())
            uniq.append(s)
    return uniq


# ---------- key terms ----------

TERM_PHRASE = re.compile(r"\b(?:[A-Z][a-z]+(?:[-’'][A-Za-z]+)?(?:[ ]+(?:of|and|&|for|the)[ ]+|[ ]+)){0,2}[A-Z][a-z]+(?:[-’'][A-Za-z]+)?\b")


def key_terms(text: str, facts, corpus: Corpus, limit=10):
    """Rank candidate terms: fact labels first, then acronyms and distinctive capitalised phrases."""
    scores = Counter()
    for f in facts:
        lab = f["label"]
        scores[lab] += 3.0
    for m in ACRONYM.finditer(text):
        a = m.group(0)
        if a.lower() not in STOP and len(a) >= 2 and a not in ("AND", "THE", "FOR", "NOT"):
            scores[a.rstrip("s") if a.endswith("s") and len(a) > 3 else a] += 1.5
    for m in TERM_PHRASE.finditer(text):
        p = m.group(0).strip()
        if len(p) < 4 or p.lower() in STOP:
            continue
        if " " not in p:          # lone capitalised words are mostly sentence starters
            continue
        w = tokens(p)
        if not w:
            continue
        rarity = sum(corpus.idf(x) for x in w) / len(w)
        scores[p] += 0.4 * rarity
    # prefer longer, remove sub-terms covered by chosen terms
    chosen = []
    for term, sc in scores.most_common(60):
        t = term.strip()
        low = t.lower()
        if any(low == c.lower() or low in c.lower() or c.lower() in low for c in chosen):
            continue
        if len(t) > 48:
            continue
        chosen.append(t)
        if len(chosen) >= limit:
            break
    return chosen


def definition_for(term: str, facts, statements_):
    for f in facts:
        if f["label"].lower() == term.lower():
            return f["text"]
    low = term.lower()
    best = None
    for s in statements_:
        if low in s.lower():
            if best is None or len(s) < len(best):
                best = s
    return best


VERBISH = re.compile(r"\b(is|are|was|can|should|must|will|may|helps?|allows?|reduces?|ensures?|provides?|uses?|requires?|"
                     r"means|makes?|improves?|supports?|enables?|keeps?|lets?|gives?|shows?|leads?|causes?|increases?|"
                     r"decreases?|include[sd]?|contains?|describes?|predicts?|measures?|affects?|depends?)\b", re.I)


def is_sentence(s: str) -> bool:
    words = len(s.split())
    return (s.endswith(".") and words >= 6 and (bool(VERBISH.search(s)) or s[0].isupper())) or \
        (bool(VERBISH.search(s)) and words >= 8)


def auto_title(text: str, corpus: Corpus):
    """Fallback title for slides with no usable heading: first short line, else distinctive words."""
    for line in text.split("\n"):
        l = BULLET.sub("", line).strip(" :-")
        if 3 <= len(l) <= 56 and 1 <= len(l.split()) <= 8 and " | " not in l and not l.endswith("."):
            return l[:1].upper() + l[1:]
    c = Counter(tokens(text))
    ranked = sorted(c, key=lambda w: -(c[w] * corpus.idf(w)))
    words = [w for w in ranked if len(w) > 3][:3]
    return " · ".join(w.capitalize() for w in words) if words else "Study notes"


def score_sentence(s: str, corpus: Corpus, section_vec):
    v = corpus.vec(s)
    base = cosine(v, section_vec)
    # mild preference for mid-length statements
    n = len(s.split())
    length_pen = 1.0 if 8 <= n <= 28 else 0.75
    return base * length_pen
