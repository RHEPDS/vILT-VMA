#!/usr/bin/env bash
# Dev: Flask built-in server. For Waitress + auto-browser use: ./Start-VMAnalytic.sh
#   ./run-web.sh
set -euo pipefail
cd "$(dirname "$0")"
if [[ -d .venv ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi
export FLASK_APP=web.app
exec flask run --host "${HOST:-127.0.0.1}" --port "${PORT:-5000}"
