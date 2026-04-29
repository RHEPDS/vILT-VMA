#!/usr/bin/env bash
# Build a single-file PyInstaller binary on Linux (or macOS). Run from repo root:
#   chmod +x build-linux-app.sh && ./build-linux-app.sh
# Output: dist/VMAnalytic  (ELF on Linux, Mach-O on macOS)
set -euo pipefail
cd "$(dirname "$0")"

echo "Installing PyInstaller..."
python3 -m pip install --upgrade pip
python3 -m pip install "pyinstaller>=6.0" -r requirements.txt

echo "Building binary (may take several minutes)..."
python3 -m PyInstaller --clean --noconfirm vmanalytic.spec

OUT="dist/VMAnalytic"
if [[ -f "$OUT" ]]; then
  chmod +x "$OUT" || true
  echo ""
  echo "OK: $(pwd)/$OUT"
  echo "Data directory when frozen: \$XDG_DATA_HOME/VMAnalytic (Linux) or ~/Library/Application Support/VMAnalytic (macOS)"
else
  echo "Build finished but $OUT not found."
  exit 1
fi
