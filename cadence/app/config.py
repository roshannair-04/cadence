"""Central configuration. Everything can be overridden with environment variables."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # .../cadence
PROJECT = ROOT.parent                                   # .../hciproj

MATERIAL_DIR = Path(os.environ.get("CADENCE_MATERIAL", PROJECT / "material"))
DATA_DIR = Path(os.environ.get("CADENCE_DATA", ROOT / "data"))
DB_PATH = DATA_DIR / "cadence.db"
# Hosted mode: every browser gets its own private workspace (own database and files). Local runs stay single-user.
MULTI = os.environ.get("CADENCE_MULTI") == "1"
STATIC_DIR = ROOT / "static"

# Local LLM through Ollama (free, runs on your machine). Optional: without it the
# app uses its built-in rule-based engine, so everything still works.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("CADENCE_MODEL", "qwen2.5:3b")
OLLAMA_TIMEOUT = float(os.environ.get("CADENCE_LLM_TIMEOUT", "120"))

# Files whose name matches one of these are skipped (administrative handouts).
SKIP_PATTERNS = [p.strip().lower() for p in os.environ.get("CADENCE_SKIP", "handout").split(",") if p.strip()]

# Sections shorter than this are merged into a neighbour.
MIN_SECTION_CHARS = 260

# Learning-model parameters (Bayesian Knowledge Tracing + forgetting curve)
BKT = dict(p_init=0.25, p_learn=0.12, p_slip=0.12, guess_mcq=0.30, guess_tf=0.5)
RETENTION_DUE = 0.70      # a section is "due" when predicted recall falls below this
