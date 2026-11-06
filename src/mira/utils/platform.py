"""Platform detection and path helpers."""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

from mira.constants import CONFIG_DIR_NAME


def get_os_name() -> str:
    return platform.system().lower()


def is_linux() -> bool:
    return get_os_name() == "linux"


def is_windows() -> bool:
    return get_os_name() == "windows"


def is_macos() -> bool:
    return get_os_name() == "darwin"


def get_python_version() -> tuple[int, int, int]:
    return sys.version_info[:3]


def check_python_version(min_major: int = 3, min_minor: int = 10) -> bool:
    major, minor, _ = get_python_version()
    return (major, minor) >= (min_major, min_minor)


def get_user_config_dir() -> Path:
    """Return user configuration directory for Mira."""
    if is_windows():
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "Mira"
        return Path.home() / "AppData" / "Roaming" / "Mira"
    # Linux / macOS XDG
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / CONFIG_DIR_NAME
    return Path.home() / ".config" / CONFIG_DIR_NAME


def get_user_data_dir() -> Path:
    """Return user data directory (database, cache, backups)."""
    if is_windows():
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "Mira"
        return Path.home() / "AppData" / "Local" / "Mira"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / CONFIG_DIR_NAME
    return Path.home() / ".local" / "share" / CONFIG_DIR_NAME


def get_system_data_dir() -> Path:
    if is_windows():
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return Path(base) / "Mira"
    return Path("/var/lib/mira")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path