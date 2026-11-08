#!/usr/bin/env bash
# Build an Arch Linux package (.pkg.tar.zst) for Mira from the current source tree.
# Intended to run inside an Arch Linux environment (e.g. GitHub Actions archlinux container).
# Usage: bash scripts/build_arch.sh 1.0.22
set -euo pipefail

VERSION="${1:?version required, e.g. 1.0.22}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/packaging/out"
STAGE="${ROOT}/packaging/arch"
PKG_NAME="mira"

rm -rf "$STAGE"
mkdir -p "$STAGE" "$OUT"

# Generate PKGBUILD that packages the already-checked-out tree (no network fetch).
cat > "${STAGE}/PKGBUILD" << PKG
# Maintainer: Soroush Zendedel <noreply@users.noreply.github.com>
pkgname=${PKG_NAME}
pkgver=${VERSION}
pkgrel=1
pkgdesc='Universal Software Repository Mirror Manager'
arch=('any')
url='https://github.com/soroush-zendedel/Mira'
license=('MIT')
depends=('python>=3.10')
makedepends=()
options=('!strip')
# Source is the local tree; we install from \$srcdir which is the stage dir.
source=()
sha256sums=()

package() {
  # Application code under /usr/lib/mira/src (same layout as .deb)
  install -d "\$pkgdir/usr/lib/mira/src"
  cp -a "${ROOT}/src/mira" "\$pkgdir/usr/lib/mira/src/"

  # Optional mirrors data
  if [[ -d "${ROOT}/mirrors" ]]; then
    install -d "\$pkgdir/usr/lib/mira/share"
    cp -a "${ROOT}/mirrors" "\$pkgdir/usr/lib/mira/share/"
  fi

  # VERSION marker
  if [[ -f "${ROOT}/VERSION" ]]; then
    install -Dm644 "${ROOT}/VERSION" "\$pkgdir/usr/lib/mira/VERSION"
  else
    printf '%s\n' "${VERSION}" > "\$pkgdir/usr/lib/mira/VERSION"
  fi

  # Launcher
  install -d "\$pkgdir/usr/bin"
  cat > "\$pkgdir/usr/bin/mira" << 'LAUNCH'
#!/usr/bin/env bash
export PYTHONPATH="/usr/lib/mira/src\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m mira "\$@"
LAUNCH
  chmod 755 "\$pkgdir/usr/bin/mira"

  # Docs / license
  install -Dm644 "${ROOT}/LICENSE" "\$pkgdir/usr/share/licenses/\${pkgname}/LICENSE"
  if [[ -f "${ROOT}/README.md" ]]; then
    install -Dm644 "${ROOT}/README.md" "\$pkgdir/usr/share/doc/\${pkgname}/README.md"
  fi
}
PKG

cd "$STAGE"

# Non-interactive makepkg as root is common in containers; allow it.
export PACKAGER="Mira CI <ci@mira>"
# --nodeps: depends are runtime only; --repackage not needed
if ! command -v makepkg >/dev/null 2>&1; then
  echo "makepkg not found. Install base-devel on an Arch system." >&2
  exit 1
fi

# Allow running as root in CI containers (makepkg refuses EUID 0 by default).
if [[ "$(id -u)" -eq 0 ]]; then
  if grep -q 'EUID == 0' /usr/bin/makepkg 2>/dev/null; then
    sed -i 's/EUID == 0/EUID == 99999/' /usr/bin/makepkg
  fi
fi

makepkg -f --noconfirm --nodeps

# Copy the produced package
shopt -s nullglob
for f in "${PKG_NAME}-${VERSION}"-*.pkg.tar.*; do
  cp -a "$f" "$OUT/"
  echo "Built $OUT/$(basename "$f")"
done
ls -la "$OUT"
