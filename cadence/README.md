# Cadence: adaptive notes and quizzes for HCI (AIM4141)

A study tool built from **your own course material** (the PDFs and slides in `../material`).
It turns each module into layered notes, quizzes you on them, models what you know,
and shows what to study next on a dashboard. It also contains a built-in usability study
(pre/post knowledge check, SUS survey, interaction logging), so the project is both an
AI/ML system *and* an HCI evaluation.

## Run it

```bash
cd cadence
./run.sh            # first run creates the conda env "cadence" and builds the library (~1 min)
# manual: conda env create -f environment.yml && conda activate cadence && python -m uvicorn app.main:app --port 8000
```

Open http://localhost:8000. Needs Python 3.9+. Nothing leaves your machine.

### Optional: local LLM (free)

The app works on its own with a built-in rule-based engine. For plain-language rewrites with
analogies, add a local model with [Ollama](https://ollama.com):

```bash
ollama pull qwen2.5:3b      # ~2 GB. llama3.2:3b or qwen2.5:7b also work
python -m app.build --llm --force    # (after `conda activate cadence`) pre-generate rewrites + extra questions
```

With Ollama running, **Explain it simpler** also generates a fresh rewrite on demand. LLM-written
questions are only kept if their answer is supported by the section text.

## What it does

| Step | What happens | AI/ML |
|---|---|---|
| Ingest | Reads PDF/PPTX, splits into ~110 sections | text extraction, layout heuristics |
| Notes | Three layers per section: key points, notes, deep dive, plus a simpler rewrite | TF-IDF extractive summarisation, key-term extraction; optional local LLM |
| Quiz | ~600 questions: match, describe, fill-in, true/false, numbers | rule-based generation with distractor selection; optional LLM |
| Model | Tracks the learner's mastery per section | Bayesian Knowledge Tracing + exponential forgetting curve |
| Adapt | Chooses next section and difficulty; reorders review; swaps to simpler notes after misses | priority scoring over mastery, recall and recent errors |
| Dashboard | Mastery map, forgetting curve, accuracy trend, time, trouble spots | analytics over the interaction log |

## HCI ideas it demonstrates (for your report)

- **Visibility of system status:** mastery rings, quiz feedback with before/after mastery, the forgetting curve.
- **User control and freedom:** every adaptation is explained ("Why this question"), dismissible, and the layers can always be switched manually.
- **Explainability:** the banner says *why* the simpler version is showing; trouble spots list their evidence.
- **Cognitive load:** layered detail (key points / notes / deep dive), one question at a time, sparse dashboard.
- **Recognition over recall:** key terms are highlighted in the text with definitions in the margin.
- **Accessibility:** keyboard-only quiz (1-4 / A-D, Enter), screen-reader labels and live regions, Atkinson Hyperlegible (designed for low vision), Lexend option, adjustable text size and spacing, dark mode, high contrast, reduced motion, read-aloud, "view as table" for every chart.
- **Error prevention and recovery:** missed questions flag the exact line in the notes and offer the simpler explanation.

## Progress check (solo)

Cadence is single-user. **Progress check** runs a pre-check, your own study time, a post-check and the SUS survey,
and shows your learning gain. The Display menu has a **Study version** switch (Adaptive or Control) if you want to
compare the two on yourself; exports are CSVs of every answer and interaction.

SUS above 68 is the usual "average" benchmark.

**Demo tools** (sidebar > Display and tools): *skip ahead one day* shows spaced repetition (recall decays, sections become due);
*reset progress* clears one participant.

## How the learner model works

- **Mastery** per section uses Bayesian Knowledge Tracing: after each answer, P(known) is updated using slip and guess
  probabilities (guess = 0.30 for 4-option questions, 0.50 for true/false), then a small learning gain is added.
- **Recall** follows R = exp(-t / S). Stability S grows after correct answers and halves after a miss.
  A section is **due** when recall drops below 70%. This is an *estimate from a model*, not a measurement.
- **Next question** (adaptive version): pick from the 4 highest-priority sections (weighted by low mastery, low recall,
  recent misses), then choose difficulty to match mastery. The control version samples uniformly.

Parameters live in `app/config.py`.

## Files

```
cadence/
  run.sh  environment.yml  requirements.txt  titles.json      launcher, deps, optional section renames
  app/    ingest.py  nlp.py  generate.py  build.py   material -> notes + questions
          tracing.py  analytics.py  llm.py  main.py  learner model, dashboard data, Ollama, API
  static/ index.html  styles.css  js/*.js  fonts/  the interface (no build step, fonts bundled)
  data/   cadence.db                          created on first run (all progress and logs)
```

## Adding material

Open **Material** in the top bar and drop in PDF, PPTX, TXT or MD files. New files are added without touching your
progress, and **Remove** deletes a file and its progress. (`python -m app.build --force` still rebuilds from the
`material` folder and clears progress.) If a slide heading was read badly, rename the section in `titles.json`.

## Known limits

- Rule-based questions are only as good as the slides. Slides that are mostly diagrams (parts of Module 2) give thin
  or awkward questions. The local LLM pass helps here.
- Knowledge tracing assumes one skill per section. It is a model of study progress, not a validated test.

## Deploying

Cadence needs a Python host (FastAPI + SQLite), so it cannot run as a static page. From the `hciproj` folder:

- **Render:** push `hciproj` to GitHub, New > Blueprint, pick the repo (`render.yaml` is included).
- **Hugging Face Spaces:** new Space, SDK Docker, upload the folder (port 7860 is already the default).
- **Anywhere with Docker:** `docker build -t cadence . && docker run -p 7860:7860 -v cadence-data:/data cadence`

Notes: no local model in the cloud, so the built-in engine is used. Progress is stored in SQLite under `/data`; without a persistent disk it resets on restart. Uploaded files are kept in `/data/material`, so they persist with the disk too.
