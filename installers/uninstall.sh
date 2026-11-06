#!/usr/bin/env bash
# Uninstall Mira (user install + PATH cleanup)
#
# Usage:
#   bash installers/uninstall.sh
#   bash installers/uninstall.sh --purge-data
#   bash installers/uninstall.sh --yes
#
set -euo pipefail

PURGE_DATA=0
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --purge-data) PURGE_DATA=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
  esac
done

echo "Mira uninstaller (Linux/macOS)"
echo "------------------------------"

INSTALL_ROOT="${HOME}/.local/share/mira"
BIN_DIR="${HOME}/.local/bin"
LAUNCHER="${BIN_DIR}/mira"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/mira"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/mira"

ask() {
  if [[ "$ASSUME_YES" -eq 1 ]]; then return 0; fi
  if [[ ! -t 0 ]]; then return 0; fi
  read -r -p "$1 [Y/n] " reply || true
  reply="${reply:-Y}"
  case "$reply" in Y|y|yes|YES) return 0 ;; *) return 1 ;; esac
}

strip_path_from_rc() {
  local rc="$1"
  [[ -f "$rc" ]] || return 0
  # Remove Mira installer / path_setup blocks and lines that only add BIN_DIR
  local tmp
  tmp="$(mktemp)"
  # Drop marker lines and the following export/fish_add_path line when adjacent
  awk -v bin="$BIN_DIR" '
    /# Mira CLI \(added by (installer|mira)\)/ { skip=1; next }
    skip==1 && ($0 ~ /export PATH=/ || $0 ~ /fish_add_path/) { skip=0; next }
    skip==1 { skip=0 }
    index($0, bin) && ($0 ~ /export PATH=/ || $0 ~ /fish_add_path/) { next }
    { print }
  ' "$rc" > "$tmp" && mv "$tmp" "$rc"
  echo "Cleaned PATH entries in: $rc"
}

if ! ask "Remove Mira application files from ${INSTALL_ROOT}?"; then
  echo "Aborted."
  exit 0
fi

# Remove launcher and install tree
rm -f "$LAUNCHER"
echo "Removed launcher (if present): $LAUNCHER"

if [[ -d "$INSTALL_ROOT" ]]; then
  rm -rf "$INSTALL_ROOT"
  echo "Removed: $INSTALL_ROOT"
fi

# Also remove /usr/local copy if owned by user (ignore errors)
if [[ -w /usr/local/bin/mira ]]; then
  rm -f /usr/local/bin/mira && echo "Removed: /usr/local/bin/mira"
fi

# Clean shell profiles
for rc in \
  "${ZDOTDIR:-$HOME}/.zshrc" \
  "$HOME/.bashrc" \
  "$HOME/.bash_profile" \
  "$HOME/.profile" \
  "$HOME/.config/fish/config.fish"
do
  strip_path_from_rc "$rc" || true
done

if [[ "$PURGE_DATA" -eq 1 ]]; then
  rm -rf "$CONFIG_DIR"
  # DATA_DIR may equal INSTALL_ROOT; remove residual cache/config names
  rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/mira"
  echo "Removed config/data under $CONFIG_DIR and data dir"
else
  echo ""
  echo "Config/data kept (if any):"
  echo "  $CONFIG_DIR"
  echo "  ${XDG_DATA_HOME:-$HOME/.local/share}/mira"
  echo "To delete them too: bash installers/uninstall.sh --purge-data"
fi

echo ""
echo "Done. Open a new terminal if PATH was updated."
