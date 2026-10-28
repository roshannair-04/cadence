"""SQLite storage. One small file, no server, easy to inspect for the report."""
import json
import sqlite3
import threading
from contextlib import contextmanager

from .config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY, filename TEXT UNIQUE, title TEXT, ord INTEGER, n_units INTEGER
);
CREATE TABLE IF NOT EXISTS sections(
  id INTEGER PRIMARY KEY, doc_id INTEGER, ord INTEGER, title TEXT, raw TEXT,
  glance TEXT, standard TEXT, deep TEXT, terms TEXT, simple TEXT, simple_source TEXT,
  minutes REAL, source_ref TEXT
);
CREATE TABLE IF NOT EXISTS questions(
  id INTEGER PRIMARY KEY, section_id INTEGER, qtype TEXT, stem TEXT, options TEXT,
  answer INTEGER, explanation TEXT, evidence TEXT, difficulty INTEGER, source TEXT
);
CREATE INDEX IF NOT EXISTS q_sec ON questions(section_id);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, name TEXT, mode TEXT DEFAULT 'adaptive',
  clock_offset_days REAL DEFAULT 0, created REAL
);
CREATE TABLE IF NOT EXISTS mastery(
  user_id INTEGER, section_id INTEGER, p_known REAL, stability REAL, last_seen REAL,
  attempts INTEGER DEFAULT 0, correct INTEGER DEFAULT 0, reads INTEGER DEFAULT 0,
  PRIMARY KEY(user_id, section_id)
);
CREATE TABLE IF NOT EXISTS attempts(
  id INTEGER PRIMARY KEY, user_id INTEGER, question_id INTEGER, section_id INTEGER,
  correct INTEGER, choice INTEGER, rt_ms REAL, changed INTEGER, phase TEXT, mode TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, user_id INTEGER, kind TEXT, section_id INTEGER, value REAL,
  meta TEXT, ts REAL
);
CREATE INDEX IF NOT EXISTS ev_user ON events(user_id, kind);
CREATE TABLE IF NOT EXISTS sus(
  id INTEGER PRIMARY KEY, user_id INTEGER, answers TEXT, score REAL, comment TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""

_local = threading.local()


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        _local.c = c
    return c


def init():
    c = conn()
    c.executescript(SCHEMA)
    c.commit()


@contextmanager
def tx():
    c = conn()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise


def rows(sql, args=()):
    return [dict(r) for r in conn().execute(sql, args).fetchall()]


def one(sql, args=()):
    r = conn().execute(sql, args).fetchone()
    return dict(r) if r else None


def jl(s, default=None):
    """json.loads that tolerates NULL."""
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


def get_meta(key, default=None):
    r = one("SELECT value FROM meta WHERE key=?", (key,))
    return r["value"] if r else default


def set_meta(key, value):
    with tx() as c:
        c.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, str(value)))
