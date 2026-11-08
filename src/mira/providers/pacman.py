"""Arch Linux pacman mirror management."""

from __future__ import annotations

import re
import os
import stat
import time
from pathlib import Path
from typing import Any

from mira.exceptions import MiraError, NetworkError
from mira.providers.base import RepositoryProvider
from mira.utils.filesystem import atomic_write
from mira.utils.network import fetch_url
from mira.utils.platform import is_linux


_BEGIN = "# >>> Mira managed mirrors >>>"
_END = "# <<< Mira managed mirrors <<<"


class PacmanProvider(RepositoryProvider):
    name = "pacman"
    mirrorlist_path = Path("/etc/pacman.d/mirrorlist")

    def __init__(self, registry, backup):
        self.registry = registry
        self.backup = backup

    def list_mirrors(self, countries=None):
        return self.registry.list_mirrors(provider=self.name, countries=countries)

    def check_mirror(self, mirror: dict[str, Any]) -> dict[str, Any]:
        base = mirror.get("url", "").rstrip("/")
        probe = base + "/lastsync"
        try:
            status, _, body, latency = fetch_url(probe, timeout=8, max_size=128)
            stamp = int(body.decode("ascii").strip()) if status == 200 else 0
            now = int(time.time())
            valid = 200 <= status < 300 and now - 7 * 86400 <= stamp <= now + 3600
            return {"available": status < 500, "valid": valid, "latency_ms": latency,
                    "error": None if valid else f"Arch mirror lastsync metadata invalid or unavailable (HTTP {status})"}
        except (NetworkError, ValueError, UnicodeDecodeError) as exc:
            return {"available": False, "valid": False, "latency_ms": None, "error": str(exc)}

    def _require_linux(self):
        if not is_linux():
            raise MiraError("Pacman configuration is supported on Linux only.", code=2)

    @staticmethod
    def _without_managed(text: str) -> str:
        return re.sub(r"(?ms)^" + re.escape(_BEGIN) + r"\n.*?^" + re.escape(_END) + r"\n?", "", text)

    def get_current(self):
        if not is_linux() or not self.mirrorlist_path.exists():
            return None
        text = self.mirrorlist_path.read_text(encoding="utf-8", errors="replace")
        managed = _BEGIN in text
        for line in text.splitlines():
            match = re.match(r"\s*Server\s*=\s*(\S+)", line)
            if match and (managed and _BEGIN in text[:text.find(line)] or not managed):
                return {"server": match.group(1), "managed": managed, "path": str(self.mirrorlist_path)}
        return None

    def apply(self, mirror, *, dry_run=False, **options):
        self._require_linux()
        url = mirror.get("url", "").rstrip("/")
        if not url.startswith("https://"):
            raise MiraError("Pacman mirrors must use HTTPS.", code=2)
        path = self.mirrorlist_path
        try:
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
            block = f"{_BEGIN}\n## {mirror.get('name', mirror.get('id', 'Mira mirror'))}\nServer = {url}/$repo/os/$arch\n{_END}\n"
            new = block + self._without_managed(old)
            if dry_run:
                return {"status": "dry-run", "path": str(path), "server": url}
            if path.exists():
                self.backup.create_backup(path, provider=self.name, operation="set")
            atomic_write(path, new)
            os.chmod(path, mode)
            return {"status": "configured", "path": str(path), "server": url}
        except PermissionError as exc:
            raise MiraError("Permission denied writing /etc/pacman.d/mirrorlist; rerun with sudo.", code=4) from exc
        except OSError as exc:
            raise MiraError(f"Could not write pacman mirrorlist: {exc}", code=4) from exc

    def reset(self, *, dry_run=False):
        self._require_linux()
        path = self.mirrorlist_path
        if not path.exists():
            return {"status": "nothing to reset"}
        try:
            old = path.read_text(encoding="utf-8")
            mode = stat.S_IMODE(path.stat().st_mode)
            new = self._without_managed(old)
            if new == old:
                return {"status": "no Mira-managed mirror block"}
            if dry_run:
                return {"status": "dry-run", "path": str(path)}
            self.backup.create_backup(path, provider=self.name, operation="reset")
            atomic_write(path, new)
            os.chmod(path, mode)
            return {"status": "restored previous mirrorlist entries", "path": str(path)}
        except PermissionError as exc:
            raise MiraError("Permission denied writing /etc/pacman.d/mirrorlist; rerun with sudo.", code=4) from exc
        except OSError as exc:
            raise MiraError(f"Could not reset pacman mirrorlist: {exc}", code=4) from exc
