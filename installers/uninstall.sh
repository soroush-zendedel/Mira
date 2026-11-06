#!/usr/bin/env bash
set -euo pipefail
INSTALL_ROOT="${HOME}/.local/share/mira"
BIN="${HOME}/.local/bin/mira"
echo "Removing application files from $INSTALL_ROOT"
rm -rf "$INSTALL_ROOT"
rm -f "$BIN"
echo "Done. User config (~/.config/mira) and data were kept."
echo "To remove data as well: rm -rf ~/.config/mira ~/.local/share/mira"
