"""Detect whether Mira is on PATH and optionally add it permanently."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from mira.utils.platform import is_windows, is_macos


def _normalize(p: str | Path) -> str:
    try:
        return str(Path(p).resolve())
    except Exception:
        return str(p)


def resolve_mira_bin_dir() -> Path | None:
    """
    Directory that should be on PATH so the user can type `mira`.

    Priority:
    1. Directory of a real `mira` / `mira.exe` / `mira.cmd` found next to argv[0]
    2. Directory of sys.executable when frozen (PyInstaller)
    3. Common user install locations if a mira launcher exists there
    """
    # Frozen binary (PyInstaller)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    argv0 = Path(sys.argv[0]).resolve() if sys.argv else None
    if argv0 and argv0.name.lower().startswith("mira"):
        return argv0.parent

    # Look for launcher beside common install layouts
    candidates: list[Path] = []
    home = Path.home()
    if is_windows():
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / "Programs" / "Mira" / "bin")
    else:
        candidates.append(home / ".local" / "bin")
        candidates.append(Path("/usr/local/bin"))
        candidates.append(Path("/usr/bin"))

    names = ("mira", "mira.exe", "mira.cmd", "mira.ps1")
    for d in candidates:
        for name in names:
            if (d / name).exists():
                return d

    # Which mira on PATH already?
    which = shutil.which("mira")
    if which:
        return Path(which).resolve().parent

    return None


def is_dir_on_path(directory: Path | None) -> bool:
    if directory is None:
        return False
    target = _normalize(directory)
    path_env = os.environ.get("PATH", "")
    for part in path_env.split(os.pathsep):
        if not part:
            continue
        if _normalize(part) == target:
            return True
    return False


def is_mira_on_path() -> bool:
    """True if invoking `mira` would find an executable."""
    return shutil.which("mira") is not None


def _detect_shell_rc() -> Path:
    shell = os.path.basename(os.environ.get("SHELL", "bash"))
    home = Path.home()
    if shell == "zsh":
        zdot = os.environ.get("ZDOTDIR")
        return Path(zdot) / ".zshrc" if zdot else home / ".zshrc"
    if shell == "fish":
        return home / ".config" / "fish" / "config.fish"
    if shell == "bash":
        bash_profile = home / ".bash_profile"
        if is_macos() and bash_profile.exists():
            return bash_profile
        return home / ".bashrc"
    return home / ".profile"


def add_to_path_permanent(bin_dir: Path) -> str:
    """
    Permanently add bin_dir to the user PATH.
    Returns a short human-readable description of what was changed.
    """
    bin_dir = bin_dir.resolve()
    if is_windows():
        return _add_windows_user_path(bin_dir)
    return _add_unix_path(bin_dir)


def _add_windows_user_path(bin_dir: Path) -> str:
    try:
        import winreg  # type: ignore
    except ImportError:
        # Fallback via setx (limited length but works)
        current = os.environ.get("PATH", "")
        # Prefer reading user PATH from registry when possible; setx merges poorly
        os.system(f'setx PATH "{bin_dir};%PATH%" >NUL')
        os.environ["PATH"] = str(bin_dir) + os.pathsep + current
        return f"Added to user PATH via setx: {bin_dir}"

    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Environment",
        0,
        winreg.KEY_READ | winreg.KEY_WRITE,
    )
    try:
        try:
            user_path, _ = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            user_path = ""
        parts = [p for p in user_path.split(";") if p]
        target = str(bin_dir)
        if any(_normalize(p) == _normalize(target) for p in parts):
            return f"Already on user PATH: {bin_dir}"
        new_path = target + ";" + user_path if user_path else target
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
    finally:
        winreg.CloseKey(key)

    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    # Broadcast env change (best-effort)
    try:
        import ctypes
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        ctypes.windll.user32.SendMessageW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment")
    except Exception:
        pass
    return f"Added to Windows user PATH: {bin_dir}"


def _add_unix_path(bin_dir: Path) -> str:
    rc = _detect_shell_rc()
    rc.parent.mkdir(parents=True, exist_ok=True)
    marker = "# Mira CLI (added by mira)"
    if rc.name == "config.fish":
        line = f"fish_add_path {bin_dir}"
    else:
        line = f'export PATH="{bin_dir}:$PATH"'

    existing = rc.read_text(encoding="utf-8") if rc.exists() else ""
    if str(bin_dir) in existing:
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
        return f"Profile already references {bin_dir} ({rc})"

    with open(rc, "a", encoding="utf-8") as f:
        f.write(f"\n{marker}\n{line}\n")
    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    return f"Added PATH entry to {rc}"


def ensure_launcher(bin_dir: Path) -> Path:
    """
    Ensure a `mira` launcher exists in bin_dir.
    Returns path to the launcher.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    if is_windows():
        cmd = bin_dir / "mira.cmd"
        # Prefer frozen exe if present
        exe = bin_dir / "mira.exe"
        if exe.exists():
            content = f'@echo off\r\n"{exe}" %*\r\n'
            cmd.write_text(content, encoding="ascii", newline="\r\n")
            return cmd
        # Module-based launcher
        py = sys.executable
        # Discover package location
        pkg = Path(__file__).resolve().parents[1]  # .../mira
        src_root = pkg.parent  # .../src
        content = (
            f"@echo off\r\n"
            f"set PYTHONPATH={src_root};%PYTHONPATH%\r\n"
            f"\"{py}\" -m mira %*\r\n"
        )
        cmd.write_text(content, encoding="ascii", newline="\r\n")
        return cmd

    launcher = bin_dir / "mira"
    if getattr(sys, "frozen", False):
        # Symlink or copy frozen binary name
        target = Path(sys.executable).resolve()
        if not launcher.exists():
            try:
                launcher.symlink_to(target)
            except OSError:
                import shutil
                shutil.copy2(target, launcher)
                launcher.chmod(0o755)
        return launcher

    py = sys.executable
    pkg = Path(__file__).resolve().parents[1]
    src_root = pkg.parent
    content = f"""#!/usr/bin/env bash
export PYTHONPATH="{src_root}${{PYTHONPATH:+:$PYTHONPATH}}"
exec "{py}" -m mira "$@"
"""
    launcher.write_text(content, encoding="utf-8")
    launcher.chmod(0o755)
    return launcher


def default_bin_dir() -> Path:
    if is_windows():
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local) / "Programs" / "Mira" / "bin"
    return Path.home() / ".local" / "bin"


def maybe_offer_path_setup(config, term) -> None:
    """
    If Mira is not on PATH, ask once (unless declined) to add it permanently.
    Creates a user-level launcher when needed. Safe no-op when non-interactive.
    """
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return
    if os.environ.get("CI") or os.environ.get("MIRA_NO_PATH_PROMPT"):
        return
    if getattr(term, "quiet", False):
        return

    if config.get("path_offer_declined"):
        return
    if config.get("path_configured") and is_mira_on_path():
        return
    if is_mira_on_path():
        return

    bin_dir = resolve_mira_bin_dir() or default_bin_dir()

    term.print()
    term.warning("Mira is not available as the `mira` command on your PATH.")
    term.info(f"Will install a launcher into: {bin_dir}")
    # Auto-configure PATH (no interactive prompt)
    reply = "y"
    if reply == "" or reply.lower() in ("y", "yes"):
        try:
            launcher = ensure_launcher(bin_dir)
            msg = add_to_path_permanent(bin_dir)
            config.set("path_configured", True)
            config.set("path_offer_declined", False)
            term.success(f"Launcher: {launcher}")
            term.success(msg)
            term.info("If a new terminal still cannot find `mira`, log out and back in.")
        except Exception as e:
            term.error(f"Could not update PATH: {e}")
    else:
        config.set("path_offer_declined", True)
        term.info("OK — will not ask again. Reset with: mira config set path_offer_declined false")
