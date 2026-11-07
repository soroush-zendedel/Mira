"""Fully uninstall Mira from the current user account."""

from __future__ import annotations

import os
import shutil
import subprocess
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


def _try_rename(path: Path) -> bool:
    """Rename a locked Windows binary so a fresh install can replace it."""
    try:
        doomed = path.with_suffix(path.suffix + ".old")
        if doomed.exists():
            try:
                doomed.unlink()
            except OSError:
                pass
        path.rename(doomed)
        return True
    except OSError:
        return False


def _schedule_windows_cleanup(paths: list[Path]) -> Path | None:
    """
    Start a detached cmd script that waits until files unlock, then deletes them.
    Required because Windows cannot delete the running mira.exe.
    """
    if not is_windows():
        return None
    targets: list[str] = []
    seen: set[str] = set()
    for pth in paths:
        key = _normalize(pth)
        if key not in seen:
            seen.add(key)
            targets.append(str(pth))
    if not targets:
        return None

    tmp = Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".")
    script = tmp / f"mira_uninstall_{os.getpid()}.cmd"
    lines = [
        "@echo off",
        "setlocal",
        "rem Mira post-exit cleanup - delete locked install files",
        "set /a n=0",
        ":waitloop",
        "set /a n+=1",
        "if %n% GTR 60 goto done",
        "timeout /t 1 /nobreak >nul",
    ]
    for t in targets:
        lines.append(f'if exist "{t}" (')
        lines.append(f'  del /f /q "{t}" 2>nul')
        lines.append(f'  rd /s /q "{t}" 2>nul')
        lines.append(")")
    lines.append("set still=0")
    for t in targets:
        lines.append(f'if exist "{t}" set still=1')
    lines.append("if %still%==1 goto waitloop")
    lines.append(":done")
    for t in targets:
        lines.append(f'if exist "{t}" del /f /q "{t}" 2>nul')
        lines.append(f'if exist "{t}" rd /s /q "{t}" 2>nul')
    lines.append('del "%~f0" >nul 2>&1')
    script.write_text("\r\n".join(lines) + "\r\n", encoding="ascii", errors="replace")

    creationflags = 0
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creationflags |= subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags |= subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    subprocess.Popen(
        ["cmd.exe", "/c", "start", "/min", "", str(script)],
        close_fds=True,
        creationflags=creationflags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return script


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
    pending_windows: list[Path] = []
    for launcher in _launcher_candidates():
        success, msg = _rm_tree(launcher)
        if success:
            actions.append(msg)
            continue
        # Try rename (works for some locked Windows binaries)
        if is_windows() and launcher.exists() and _try_rename(launcher):
            actions.append(f"renamed locked file for deletion: {launcher}")
            pending_windows.append(launcher.with_suffix(launcher.suffix + ".old"))
            continue
        if self_exe and _normalize(launcher) == _normalize(self_exe):
            pending_windows.append(launcher)
            actions.append(f"scheduled delete after exit: {launcher}")
        else:
            if is_windows():
                pending_windows.append(launcher)
                actions.append(f"scheduled delete after exit: {launcher}")
            else:
                failures.append(msg)

    # 3) Install roots (Programs\Mira, ~/.local/share/mira)
    install_trees: list[Path] = []
    for root in _install_roots():
        if root.name in ("bin", "Bin"):
            continue
        install_trees.append(root)

    for tree in install_trees:
        success, msg = _rm_tree(tree)
        if success:
            actions.append(msg)
        elif "not found" not in msg:
            if is_windows():
                pending_windows.append(tree)
                actions.append(f"scheduled delete after exit: {tree}")
            else:
                failures.append(msg)

    # 3b) Windows: detach cleanup for anything still locked (running exe)
    if is_windows() and pending_windows:
        try:
            script = _schedule_windows_cleanup(pending_windows)
            if script:
                actions.append(f"cleanup helper started: {script}")
        except Exception as e:
            failures.append(f"could not schedule cleanup helper: {e}")

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
        warn("Some items could not be removed immediately.")
        if is_windows():
            warn("If a cleanup helper was started, wait a few seconds and check the install folder is gone.")
        return 1

    ok("Uninstall finished. Open a new terminal so PATH changes apply.")
    if is_windows() and pending_windows:
        ok("Locked files will be removed automatically in a few seconds after this process exits.")
    return 0
