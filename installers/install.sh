#!/usr/bin/env bash
# Mira installer (Linux)
#
# Usage:
#   bash installers/install.sh
#   bash installers/install.sh --from-release
#   bash installers/install.sh --yes              # non-interactive (assume yes for PATH)
#   MIRA_INSTALL_NONINTERACTIVE=1 bash installers/install.sh
#
set -euo pipefail

APP_NAME="mira"
REPO="soroush-zendedel/Mira"
MIN_PY_MAJOR=3
MIN_PY_MINOR=10
FROM_RELEASE=0
ASSUME_YES=0

for arg in "$@"; do
  case "$arg" in
    --from-release) FROM_RELEASE=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
  esac
done
if [[ "${MIRA_INSTALL_NONINTERACTIVE:-0}" == "1" ]]; then
  ASSUME_YES=1
fi

echo "Mira installer (Linux)"
echo "----------------------"

INSTALL_ROOT="${HOME}/.local/share/mira"
BIN_DIR="${HOME}/.local/bin"
LAUNCHER="${BIN_DIR}/mira"
mkdir -p "$INSTALL_ROOT" "$BIN_DIR"

# --- PATH helpers ---
path_contains_bin() {
  case ":$PATH:" in
    *":${BIN_DIR}:"*) return 0 ;;
    *) return 1 ;;
  esac
}

detect_shell_rc() {
  # Prefer the user's login shell rc
  local sh
  sh="$(basename "${SHELL:-bash}")"
  case "$sh" in
    zsh) echo "${ZDOTDIR:-$HOME}/.zshrc" ;;
    bash)
      if [[ -f "$HOME/.bash_profile" ]]; then echo "$HOME/.bash_profile"
      else echo "$HOME/.bashrc"
      fi
      ;;
    fish) echo "$HOME/.config/fish/config.fish" ;;
    *) echo "$HOME/.profile" ;;
  esac
}

ask_yes_no() {
  # $1 prompt  default Y if empty answer and default yes
  local prompt="$1"
  local default="${2:-Y}"
  if [[ "$ASSUME_YES" -eq 1 ]]; then
    return 0
  fi
  if [[ ! -t 0 ]]; then
    # non-tty (piped curl|bash): do not modify shell profiles automatically
    return 1
  fi
  local reply
  if [[ "$default" == "Y" ]]; then
    read -r -p "$prompt [Y/n] " reply || true
    reply="${reply:-Y}"
  else
    read -r -p "$prompt [y/N] " reply || true
    reply="${reply:-N}"
  fi
  case "$reply" in
    Y|y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

configure_path() {
  if path_contains_bin; then
    echo "PATH already includes $BIN_DIR — nothing to do."
    return 0
  fi

  echo ""
  echo "The launcher was installed to: $LAUNCHER"
  echo "This directory is not on your current PATH: $BIN_DIR"
  echo ""

  if ! ask_yes_no "Add $BIN_DIR to PATH in your shell profile?"; then
    echo "Skipped. You can run Mira via: $LAUNCHER"
    echo "Or add this to your shell profile later:"
    echo "  export PATH=\"$BIN_DIR:\$PATH\""
    return 0
  fi

  local rc
  rc="$(detect_shell_rc)"
  mkdir -p "$(dirname "$rc")"
  local marker="# Mira CLI (added by installer)"
  local line="export PATH=\"$BIN_DIR:\$PATH\""

  if [[ "$(basename "$rc")" == "config.fish" ]]; then
    line="fish_add_path $BIN_DIR"
  fi

  if [[ -f "$rc" ]] && grep -qF "$BIN_DIR" "$rc" 2>/dev/null; then
    echo "Profile already mentions $BIN_DIR ($rc)."
  else
    {
      echo ""
      echo "$marker"
      echo "$line"
    } >> "$rc"
    echo "Added PATH entry to: $rc"
  fi

  # Also apply to current session
  export PATH="$BIN_DIR:$PATH"
  echo "PATH updated for this session. Open a new terminal for other sessions."
}

install_from_release() {
  echo "Downloading standalone binary from latest GitHub Release..."
  URL="https://github.com/${REPO}/releases/latest/download/mira-linux-x86_64"
  TMP="$(mktemp)"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$TMP" "$URL" || return 1
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$TMP" "$URL" || return 1
  else
    echo "Need curl or wget to download release binary." >&2
    return 1
  fi
  chmod +x "$TMP"
  mv "$TMP" "$LAUNCHER"
  echo "Installed standalone binary to $LAUNCHER"
  "$LAUNCHER" --version || true
  return 0
}

install_from_source_tree() {
  local REPO_ROOT="$1"
  echo "Installing from source: $REPO_ROOT"
  PYTHON=""
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON="$candidate"
      break
    fi
  done
  if [[ -z "$PYTHON" ]]; then
    echo "Error: Python not found. Install Python ${MIN_PY_MAJOR}.${MIN_PY_MINOR}+." >&2
    exit 1
  fi
  MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
  MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")
  if (( MAJOR < MIN_PY_MAJOR || (MAJOR == MIN_PY_MAJOR && MINOR < MIN_PY_MINOR) )); then
    echo "Error: Python ${MIN_PY_MAJOR}.${MIN_PY_MINOR}+ required." >&2
    exit 1
  fi
  echo "Using Python $($PYTHON -c 'import sys; print("%d.%d"%sys.version_info[:2])') ($PYTHON)"

  # Show package version from source if available
  if [[ -f "$REPO_ROOT/VERSION" ]]; then
    echo "Package version: $(tr -d '[:space:]' < "$REPO_ROOT/VERSION")"
  fi

  rm -rf "$INSTALL_ROOT/src"
  mkdir -p "$INSTALL_ROOT/src"
  cp -a "$REPO_ROOT/src/mira" "$INSTALL_ROOT/src/"
  if [[ -d "$REPO_ROOT/mirrors" ]]; then
    mkdir -p "$INSTALL_ROOT/share"
    cp -a "$REPO_ROOT/mirrors" "$INSTALL_ROOT/share/" 2>/dev/null || true
  fi
  # Keep VERSION next to install for diagnostics
  if [[ -f "$REPO_ROOT/VERSION" ]]; then
    cp "$REPO_ROOT/VERSION" "$INSTALL_ROOT/VERSION"
  fi

  cat > "$LAUNCHER" << LAUNCH
#!/usr/bin/env bash
export PYTHONPATH="${INSTALL_ROOT}/src\${PYTHONPATH:+:\$PYTHONPATH}"
exec ${PYTHON} -m mira "\$@"
LAUNCH
  chmod +x "$LAUNCHER"
  echo "Installed source layout to $INSTALL_ROOT"
  "$LAUNCHER" --version || true
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ "$FROM_RELEASE" -eq 1 ]]; then
  if install_from_release; then
    :
  else
    echo "Release binary not available; falling back to source if possible."
    if [[ -d "$REPO_ROOT/src/mira" ]]; then
      install_from_source_tree "$REPO_ROOT"
    else
      exit 1
    fi
  fi
elif [[ -d "$REPO_ROOT/src/mira" ]]; then
  install_from_source_tree "$REPO_ROOT"
else
  if install_from_release; then
    :
  elif command -v git >/dev/null 2>&1; then
    TMP=$(mktemp -d)
    trap 'rm -rf "$TMP"' EXIT
    git clone --depth 1 "https://github.com/${REPO}.git" "$TMP/Mira"
    install_from_source_tree "$TMP/Mira"
  else
    echo "Error: no local source, no release binary, and git not found." >&2
    exit 1
  fi
fi

configure_path

echo ""
echo "Done. Run: mira update && mira status"
