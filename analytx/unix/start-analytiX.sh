#!/usr/bin/env bash
# Start AnalytiX if .venv already exists.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"

if [[ ! -x "${PY}" ]]; then
  echo "Virtual environment not found."
  echo "Run first: ./unix/install-and-start.sh"
  echo "    or:    ./unix/setup.sh"
  exit 1
fi

echo "Starting AnalytiX at http://127.0.0.1:8765 (Ctrl+C to stop)"
exec "${PY}" "${ROOT}/analytx_server.py"
