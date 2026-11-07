"""Fully uninstall Mira from the current user account."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from mira.utils.platform import get_user_config_dir, get_user_data_dir, is_windows, is_macos


def _normalize(p: str | Path) -> str:
    try:
        return str(Path(p).resolve())
    except Exception:
        return str(p)


def _install_roots() -> list[Path]:
    """Directories that may hold the application itself (launchers / source layout)."""
    roots: list[Path] = []
    home = Path.home()
    if is_windows():
        local = os.environ.get("LOCALAPPDATA")
        if local:
            roots.append(Path(local) / "Programs" / "Mira")
            roots.append(Path(local) / "Mira")  # data dir may also host tools
        roots.append(home / "bin")
        roots.append(home / ".local" / "bin")
    else:
        roots.append(home / ".local" / "share" / "mira")
        roots.append(home / ".local" / "bin")
        roots.append(Path("/usr/local/bin"))
    return roots


def _launcher_candidates() -> list[Path]:
    names = ("mira", "mira.exe", "mira.cmd", "mira.ps1")
    found: list[Path] = []
    for root in _install_roots():
        if root.is_dir():
            for name in names:
                p = root / name
                if p.exists():
                    found.append(p)
        # When root is itself a bin file path parent already covered
    # which mira
    which = shutil.which("mira")
    if which:
        found.append(Path(which))
    # Frozen binary path
    if getattr(sys, "frozen", False):
        found.append(Path(sys.executable))
    # Deduplicate
    seen: set[str] = set()
    out: list[Path] = []
    for p in found:
        key = _normalize(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _bin_dirs_for_path_cleanup() -> list[Path]:
    dirs: list[Path] = []
    if is_windows():
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Programs" / "Mira" / "bin")
    else:
        dirs.append(Path.home() / ".local" / "bin")
    for launcher in _launcher_candidates():
        dirs.append(launcher.parent)
    # unique
    seen: set[str] = set()
    out: list[Path] = []
    for d in dirs:
        key = _normalize(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _remove_from_windows_user_path(directory: Path) -> bool:
    target = _normalize(directory)
    try:
        import winreg  # type: ignore
    except ImportError:
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        )
    except OSError:
        return False
    changed = False
    try:
        try:
            user_path, _ = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            return False
        parts = [p for p in user_path.split(";") if p and _normalize(p) != target]
        new_path = ";".join(parts)
        if new_path != user_path:
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
            changed = True
        # session
        session = os.environ.get("PATH", "")
        sparts = [p for p in session.split(os.pathsep) if p and _normalize(p) != target]
        os.environ["PATH"] = os.pathsep.join(sparts)
    finally:
        winreg.CloseKey(key)
    if changed:
        try:
            import ctypes
            ctypes.windll.user32.SendMessageW(0xFFFF, 0x001A, 0, "Environment")
        except Exception:
            pass
    return changed


def _strip_unix_profile(rc: Path, bin_dir: Path) -> bool:
    if not rc.is_file():
        return False
    text = rc.read_text(encoding="utf-8", errors="replace")
    bin_s = str(bin_dir)
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    skip_next_export = False
    changed = False
    for line in lines:
        if "# Mira CLI (added by installer)" in line or "# Mira CLI (added by mira)" in line:
            skip_next_export = True
            changed = True
            continue
        if skip_next_export and (
            "export PATH=" in line or "fish_add_path" in line
        ):
            skip_next_export = False
            changed = True
            continue
        skip_next_export = False
        if bin_s in line and ("export PATH=" in line or "fish_add_path" in line):
            changed = True
            continue
        out.append(line)
    if changed:
        rc.write_text("".join(out), encoding="utf-8")
    return changed


def _clean_unix_path(bin_dir: Path) -> list[str]:
    notes: list[str] = []
    home = Path.home()
    shell = os.path.basename(os.environ.get("SHELL", "bash"))
    candidates = [
        home / ".bashrc",
        home / ".bash_profile",
        home / ".profile",
        home / ".zshrc",
        Path(os.environ["ZDOTDIR"]) / ".zshrc" if os.environ.get("ZDOTDIR") else None,
        home / ".config" / "fish" / "config.fish",
    ]
    if is_macos():
        candidates.append(home / ".zprofile")
    for rc in candidates:
        if rc is None:
            continue
        try:
            if _strip_unix_profile(rc, bin_dir):
                notes.append(f"cleaned shell profile: {rc}")
        except OSError as e:
            notes.append(f"could not edit {rc}: {e}")
    # session PATH
    target = _normalize(bin_dir)
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p and _normalize(p) != target]
    os.environ["PATH"] = os.pathsep.join(parts)
    return notes


def _rm_tree(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"not found: {path}"
    try:
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
        else:
            shutil.rmtree(path)
        return True, f"removed: {path}"
    except OSError as e:
        return False, f"failed to remove {path}: {e}"


def uninstall(*, purge_data: bool = True, assume_yes: bool = False, term=None) -> int:
    """
    Remove Mira launchers, install tree, PATH entries, and (by default) config/data.

    Returns process exit code (0 = success / nothing left that we could remove).
    """
    def info(msg: str) -> None:
        if term:
            term.info(msg)
        else:
            print(msg)

    def warn(msg: str) -> None:
        if term:
            term.warning(msg)
        else:
            print(msg)

    def ok(msg: str) -> None:
        if term:
            term.success(msg)
        else:
            print(msg)

    def err(msg: str) -> None:
        if term:
            term.error(msg)
        else:
            print(msg, file=sys.stderr)

    if term:
        term.header("MIRA UNINSTALL")
    else:
        info("Mira uninstall")
        info("-------------")

    if not assume_yes:
        if not sys.stdin.isatty():
            err("Refusing non-interactive uninstall without --yes")
            return 2
        try:
            reply = input("This will remove Mira from your user account. Continue? [y/N] ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            info("Aborted.")
            return 1
        if reply.lower() not in ("y", "yes"):
            info("Aborted.")
            return 1

    actions: list[str] = []
    failures: list[str] = []

    # 1) PATH cleanup
    for d in _bin_dirs_for_path_cleanup():
        if is_windows():
            try:
                if _remove_from_windows_user_path(d):
                    actions.append(f"removed from user PATH: {d}")
            except Exception as e:
                failures.append(f"PATH cleanup failed for {d}: {e}")
        else:
            actions.extend(_clean_unix_path(d))

    # 2) Launchers
    self_exe = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None
    for launcher in _launcher_candidates():
        # On Windows, deleting the running frozen EXE may fail — try anyway
        success, msg = _rm_tree(launcher)
        if success:
            actions.append(msg)
        else:
            if self_exe and _normalize(launcher) == _normalize(self_exe):
                failures.append(f"{msg} (running binary; delete manually after exit if needed)")
            else:
                failures.append(msg)

    # 3) Install roots (Programs\Mira, ~/.local/share/mira)
    # Prefer shared helper so tests can patch _install_roots.
    install_trees: list[Path] = []
    for root in _install_roots():
        # Skip pure bin directories (launchers already handled)
        if root.name in ("bin", "Bin"):
            continue
        install_trees.append(root)

    for tree in install_trees:
        success, msg = _rm_tree(tree)
        if success:
            actions.append(msg)
        elif "not found" not in msg:
            failures.append(msg)

    # 4) Config + data
    if purge_data:
        for d in (get_user_config_dir(), get_user_data_dir()):
            success, msg = _rm_tree(d)
            if success:
                actions.append(msg)
            elif "not found" not in msg:
                failures.append(msg)
    else:
        info("Keeping config/data (run with default purge to delete them).")
        info(f"  config: {get_user_config_dir()}")
        info(f"  data:   {get_user_data_dir()}")

    # Report
    if actions:
        for a in actions:
            ok(a)
    else:
        warn("Nothing to remove — Mira does not appear to be installed for this user.")

    if failures:
        for f in failures:
            warn(f)
        warn("Some items could not be removed. Close all terminals using mira and retry.")
        return 1

    ok("Uninstall finished. Open a new terminal so PATH changes apply.")
    return 0
