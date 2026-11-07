"""PyPI / pip index provider."""

from __future__ import annotations

import configparser
import os
from pathlib import Path
from typing import Any

from mira.core.registry import MirrorRegistry
from mira.exceptions import NetworkError, ProviderError
from mira.providers.base import RepositoryProvider
from mira.services.backup import BackupService
from mira.utils.network import fetch_url
from mira.utils.platform import is_windows


class PyPIProvider(RepositoryProvider):
    name = "pypi"

    def __init__(self, registry: MirrorRegistry, backup: BackupService | None = None):
        self.registry = registry
        self.backup = backup or BackupService()

    def list_mirrors(self, countries: list[str] | None = None) -> list[dict[str, Any]]:
        return self.registry.list_mirrors(provider="pypi", countries=countries)

    def check_mirror(self, mirror: dict[str, Any]) -> dict[str, Any]:
        url = mirror["url"].rstrip("/") + "/"
        # Prefer a known small package endpoint to avoid huge simple/ listings
        probe = url.rstrip("/") + "/pip/"
        try:
            status, headers, body, latency = fetch_url(probe, timeout=5.0, max_size=512 * 1024)
        except NetworkError:
            try:
                status, headers, body, latency = fetch_url(url, timeout=5.0, max_size=256 * 1024)
            except NetworkError as e:
                return {
                    "available": False,
                    "valid": False,
                    "latency_ms": None,
                    "error": str(e),
                    "stability": 0.0,
                }
        available = 200 <= status < 400
        content_type = (headers.get("Content-Type") or headers.get("content-type") or "").lower()
        text = body.decode("utf-8", errors="replace")[:4000]
        valid = available and (
            "text/html" in content_type
            or "application/vnd.pypi" in content_type
            or "simple" in text.lower()
            or "<a href" in text.lower()
            or "pip" in text.lower()
            or text.strip().startswith("{")
            or status == 200
        )
        return {
            "available": available,
            "valid": bool(valid),
            "latency_ms": latency if available else None,
            "error": None if valid else f"HTTP {status} or unexpected content",
            "stability": 0.7 if valid else 0.0,
        }

    def _pip_conf_paths(self, scope: str = "user") -> list[Path]:
        paths = []
        if scope == "project":
            # current venv or cwd
            venv = os.environ.get("VIRTUAL_ENV")
            if venv:
                paths.append(Path(venv) / "pip.conf")
            paths.append(Path.cwd() / "pip.conf")
        elif scope == "system":
            if is_windows():
                paths.append(Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "pip" / "pip.ini")
            else:
                paths.append(Path("/etc/pip.conf"))
        else:  # user
            if is_windows():
                appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
                paths.append(Path(appdata) / "pip" / "pip.ini")
            else:
                paths.append(Path.home() / ".config" / "pip" / "pip.conf")
                paths.append(Path.home() / ".pip" / "pip.conf")
        return paths

    def get_current(self) -> dict[str, Any] | None:
        for path in self._pip_conf_paths("user") + self._pip_conf_paths("project"):
            if path.exists():
                try:
                    cp = configparser.ConfigParser()
                    cp.read(path)
                    if cp.has_section("global") and cp.has_option("global", "index-url"):
                        return {
                            "url": cp.get("global", "index-url"),
                            "path": str(path),
                            "scope": "detected",
                        }
                except Exception:
                    continue
        return None

    def apply(self, mirror: dict[str, Any], *, dry_run: bool = False, scope: str = "user", **options: Any) -> dict[str, Any]:
        url = mirror["url"]
        paths = self._pip_conf_paths(scope)
        target = paths[0]
        summary = {
            "provider": "pypi",
            "mirror_id": mirror.get("id"),
            "url": url,
            "scope": scope,
            "path": str(target),
            "dry_run": dry_run,
            "action": "set index-url",
        }
        if dry_run:
            return summary

        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            self.backup.create_backup(target, provider="pypi", operation="set")

        cp = configparser.ConfigParser()
        if target.exists():
            cp.read(target)
        if not cp.has_section("global"):
            cp.add_section("global")
        cp.set("global", "index-url", url)
        # Trusted host helps mirrors with atypical TLS / corporate MITM
        from urllib.parse import urlparse
        host = urlparse(url).hostname
        if host:
            cp.set("global", "trusted-host", host)
        # do not touch extra-index-url
        with open(target, "w", encoding="utf-8") as f:
            cp.write(f)
        summary["status"] = "applied"
        summary["trusted-host"] = host
        return summary

    def reset(self, *, dry_run: bool = False, scope: str = "user") -> dict[str, Any]:
        paths = self._pip_conf_paths(scope)
        target = paths[0]
        summary = {"provider": "pypi", "path": str(target), "dry_run": dry_run, "action": "reset"}
        if not target.exists():
            summary["status"] = "nothing to reset"
            return summary
        if dry_run:
            return summary
        self.backup.create_backup(target, provider="pypi", operation="reset")
        cp = configparser.ConfigParser()
        cp.read(target)
        if cp.has_section("global") and cp.has_option("global", "index-url"):
            cp.remove_option("global", "index-url")
            with open(target, "w", encoding="utf-8") as f:
                cp.write(f)
            summary["status"] = "removed index-url"
        else:
            summary["status"] = "no index-url found"
        return summary