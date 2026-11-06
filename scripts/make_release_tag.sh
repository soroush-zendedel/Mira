#!/usr/bin/env bash
# Bump version (SemVer), sync all version fields, print git tag commands.
#
# Usage:
#   bash scripts/make_release_tag.sh 1.0.1
#   bash scripts/make_release_tag.sh 1.1.0
#
# Rules (SemVer):
#   MAJOR.MINOR.PATCH
#   - PATCH: bugfixes only
#   - MINOR: new features, backward compatible
#   - MAJOR: breaking changes
#
set -euo pipefail
VER="${1:?usage: make_release_tag.sh MAJOR.MINOR.PATCH}"
if [[ ! "$VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]]; then
  echo "Invalid SemVer: $VER (expected e.g. 1.0.0 or 1.0.0-rc.1)" >&2
  exit 1
fi
TAG="v${VER}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "$VER" > VERSION

# Single source of truth: VERSION file; mirror into package metadata
python3 - << PY
from pathlib import Path
import re
ver = Path("VERSION").read_text().strip()
Path("src/mira/__init__.py").write_text(
    f'''"""Mira - Universal Software Repository Mirror Manager."""

__version__ = "{ver}"
__author__ = "Soroush Zendedel"
'''
)
c = Path("src/mira/constants.py").read_text()
c = re.sub(r'APP_VERSION = "[^"]*"', f'APP_VERSION = "{ver}"', c)
Path("src/mira/constants.py").write_text(c)
t = Path("pyproject.toml").read_text()
t = re.sub(r'^version = "[^"]*"', f'version = "{ver}"', t, flags=re.M)
Path("pyproject.toml").write_text(t)
print(f"Synced package metadata to {ver}")
PY

echo ""
echo "Version set to ${VER}"
echo "Next steps:"
echo "  git add -A"
echo "  git commit -m \"Release ${TAG}\""
echo "  git tag -a ${TAG} -m \"Mira ${TAG}\""
echo "  git push origin main"
echo "  git push origin ${TAG}"
echo ""
echo "GitHub Actions will build binaries, .deb and attach them to the Release."
