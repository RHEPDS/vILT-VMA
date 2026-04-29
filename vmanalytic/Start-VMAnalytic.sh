#!/usr/bin/env bash
# Self-running VMAnalytic on Linux/macOS (Waitress + venv). From repo root:
#   chmod +x Start-VMAnalytic.sh && ./Start-VMAnalytic.sh
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  echo "[VMAnalytic] Creating virtual environment..."
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate

echo "[VMAnalytic] Installing dependencies (first run may take a minute)..."
python -m pip install -q -U pip
python -m pip install -q -r requirements.txt

export PYTHONPATH="${PWD}"
export HOST="${HOST:-127.0.0.1}"
export PORT="${PORT:-5000}"

exec python local_server.py
