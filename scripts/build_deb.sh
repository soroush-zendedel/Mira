#!/usr/bin/env bash
# Build a simple amd64 .deb for Mira (no external packaging tools required).
# Usage: bash scripts/build_deb.sh 1.0.0
set -euo pipefail

VERSION="${1:?version required, e.g. 1.0.0}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/packaging/out"
STAGE="${ROOT}/packaging/stage"
PKG_NAME="mira"
ARCH="amd64"
DEB_DIR="${STAGE}/${PKG_NAME}_${VERSION}_${ARCH}"

rm -rf "$STAGE"
mkdir -p "${DEB_DIR}/DEBIAN"
mkdir -p "${DEB_DIR}/usr/lib/mira/src"
mkdir -p "${DEB_DIR}/usr/bin"
mkdir -p "${DEB_DIR}/usr/share/doc/mira"

# Application code
cp -a "${ROOT}/src/mira" "${DEB_DIR}/usr/lib/mira/src/"

# Launcher
cat > "${DEB_DIR}/usr/bin/mira" << 'LAUNCH'
#!/usr/bin/env bash
export PYTHONPATH="/usr/lib/mira/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m mira "$@"
LAUNCH
chmod 755 "${DEB_DIR}/usr/bin/mira"

# Docs
cp "${ROOT}/LICENSE" "${DEB_DIR}/usr/share/doc/mira/copyright"
cp "${ROOT}/README.md" "${DEB_DIR}/usr/share/doc/mira/" 2>/dev/null || true

# Control file
cat > "${DEB_DIR}/DEBIAN/control" << CTRL
Package: ${PKG_NAME}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.10)
Maintainer: Soroush Zendedel <noreply@users.noreply.github.com>
Description: Universal Software Repository Mirror Manager
 Mira discovers, evaluates, selects and configures repository mirrors
 for PyPI, Debian APT and Docker Engine. Zero third-party Python
 runtime dependencies.
CTRL

# Optional postinst: nothing critical
cat > "${DEB_DIR}/DEBIAN/postinst" << 'POST'
#!/bin/sh
set -e
echo "Mira installed. Run: mira update && mira status"
POST
chmod 755 "${DEB_DIR}/DEBIAN/postinst"

mkdir -p "$OUT"
# dpkg-deb is available on Debian/Ubuntu builders (GitHub ubuntu-latest has it)
if command -v dpkg-deb >/dev/null 2>&1; then
  dpkg-deb --build --root-owner-group "$DEB_DIR" "${OUT}/${PKG_NAME}_${VERSION}_${ARCH}.deb"
  echo "Built ${OUT}/${PKG_NAME}_${VERSION}_${ARCH}.deb"
else
  echo "dpkg-deb not found; skipping .deb (install dpkg-dev on the builder)." >&2
  exit 0
fi
