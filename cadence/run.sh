#!/usr/bin/env bash
# Start Cadence in its conda environment "cadence" (created on first run), then open the app.
set -e
cd "$(dirname "$0")"
command -v conda >/dev/null || { echo "conda not found. Install Miniconda, then run ./run.sh again."; exit 1; }
eval "$(conda shell.bash hook)"

if ! conda env list | grep -q '^cadence '; then
  echo "First run: creating the conda environment 'cadence' (about a minute)..."
  conda env create -f environment.yml
fi
conda activate cadence

PORT="${PORT:-8000}"
echo "Cadence is starting at http://localhost:$PORT   (Ctrl+C to stop)"
( sleep 2; (open "http://localhost:$PORT/app" || xdg-open "http://localhost:$PORT/app") >/dev/null 2>&1 ) &
exec python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
