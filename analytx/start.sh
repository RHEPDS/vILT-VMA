#!/usr/bin/env bash
# AnalytiX Web-UI (http://127.0.0.1:8765)
# Legt bei Bedarf die venv an (über unix/setup.sh), startet dann die App.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="${ROOT}/.venv/bin/python"

if [[ ! -x "${PY}" ]]; then
  echo "First run: installing dependencies …"
  bash "${ROOT}/unix/setup.sh" --no-start
fi

exec "${PY}" "${ROOT}/analytx_server.py"
