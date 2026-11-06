#!/usr/bin/env bash
# Local helper: build a standalone binary with PyInstaller (optional).
# CI uses the same flags. Not required for source installs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 -m pip install --user pyinstaller >/dev/null
python3 -m PyInstaller \
  --onefile \
  --name mira \
  --paths src \
  --hidden-import mira \
  --hidden-import mira.cli \
  --console \
  src/mira/__main__.py
echo "Binary: $ROOT/dist/mira"
