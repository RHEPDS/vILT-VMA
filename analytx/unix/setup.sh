#!/usr/bin/env bash
# AnalytiX – macOS / Linux: create venv, install dependencies, optionally start the server.
# Usage:
#   ./unix/setup.sh              # install and start
#   ./unix/setup.sh --no-start   # install only
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

NO_START=false
if [[ "${1:-}" == "--no-start" ]]; then
  NO_START=true
fi

VENV="${ROOT}/.venv"
PY="${VENV}/bin/python"
PIP="${VENV}/bin/pip"

resolve_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi
  if command -v python >/dev/null 2>&1; then
    if python -c 'import sys; assert sys.version_info >= (3, 10)' 2>/dev/null; then
      echo "python"
      return
    fi
  fi
  echo ""
}

echo "AnalytiX – setup (macOS / Linux)"
echo "Project root: ${ROOT}"

HOST_PY="$(resolve_python)"
if [[ -z "${HOST_PY}" ]]; then
  echo "ERROR: Python 3.10+ not found (tried: python3, python)." >&2
  echo "Install e.g. https://docs.python.org/3/using/unix.html or use your package manager." >&2
  exit 1
fi

echo "Using: ${HOST_PY} ($(${HOST_PY} -c 'import sys; print(sys.version.split()[0])'))"

if [[ ! -x "${PY}" ]]; then
  echo "Creating virtual environment in .venv ..."
  "${HOST_PY}" -m venv "${VENV}"
fi

if [[ ! -x "${PIP}" ]]; then
  echo "ERROR: venv created but pip not found at ${PIP}" >&2
  exit 1
fi

echo "Upgrading pip …"
"${PY}" -m pip install --upgrade pip -q

REQ="${ROOT}/requirements.txt"
if [[ ! -f "${REQ}" ]]; then
  echo "ERROR: requirements.txt not found at ${REQ}" >&2
  exit 1
fi

echo "Installing packages from requirements.txt …"
"${PY}" -m pip install -r "${REQ}"

echo ""
echo "Setup finished successfully."

if [[ "${NO_START}" == true ]]; then
  echo "Start later with: ./unix/start-analytiX.sh   or   ./start.sh"
  exit 0
fi

echo ""
echo "Starting AnalytiX: http://127.0.0.1:8765"
echo "Press Ctrl+C to stop."
echo ""
exec "${PY}" "${ROOT}/analytx_server.py"
