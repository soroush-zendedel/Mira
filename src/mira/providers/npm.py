"""npm registry provider."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mira.core.registry import MirrorRegistry
from mira.exceptions import NetworkError, ProviderError
from mira.providers.base import RepositoryProvider
from mira.services.backup import BackupService
from mira.utils.network import fetch_url
from mira.utils.platform import is_windows


class NpmProvider(RepositoryProvider):
    name = "npm"

    def __init__(self, registry: MirrorRegistry, backup: BackupService | None = None):
        self.registry = registry
        self.backup = backup or BackupService()

    def list_mirrors(self, countries: list[str] | None = None) -> list[dict[str, Any]]:
        return self.registry.list_mirrors(provider="npm", countries=countries)

    def check_mirror(self, mirror: dict[str, Any]) -> dict[str, Any]:
        base = mirror["url"].rstrip("/")
        try:
            status, headers, body, latency = fetch_url(
                f"{base}/express", timeout=8.0, max_size=1024 * 1024
            )
            if not 200 <= status < 300:
                raise NetworkError(f"HTTP {status} for npm package metadata")
            import json

            data = json.loads(body.decode("utf-8"))
            valid = (
                isinstance(data, dict)
                and data.get("name") == "express"
                and isinstance(data.get("versions"), dict)
                and bool(data["versions"])
            )
            return {
                "available": True,
                "valid": valid,
                "latency_ms": latency,
                "error": None if valid else "Unexpected npm package metadata",
                "stability": 0.8 if valid else 0.0,
            }
        except (NetworkError, ValueError, UnicodeDecodeError) as e:
            return {
                "available": False,
                "valid": False,
                "latency_ms": None,
                "error": str(e),
                "stability": 0.0,
            }

    def _npmrc_paths(self, scope: str = "user") -> list[Path]:
        if scope not in ("user", "project", "system"):
            raise ProviderError(f"Unsupported npm configuration scope: {scope}")
        if scope == "project":
            return [Path.cwd() / ".npmrc"]
        if scope == "system":
            if is_windows():
                return [Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "nodejs" / "etc" / "npmrc"]
            return [Path("/etc/npmrc")]
        if is_windows():
            return [Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".npmrc"]
        return [Path.home() / ".npmrc"]

    def get_current(self) -> dict[str, Any] | None:
        paths = self._npmrc_paths("user") + self._npmrc_paths("project")
        for path in paths:
            if not path.exists():
                continue
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    key, sep, value = line.partition("=")
                    if sep and key.strip().lower() == "registry":
                        return {"url": value.strip(), "path": str(path), "scope": "detected"}
            except (OSError, UnicodeDecodeError):
                continue
        return None

    def apply(self, mirror: dict[str, Any], *, dry_run: bool = False, scope: str = "user", **options: Any) -> dict[str, Any]:
        url = mirror["url"].strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ProviderError("npm registry URL must be an absolute HTTPS URL")
        paths = self._npmrc_paths(scope)
        if not paths:
            raise ProviderError(f"Unsupported npm configuration scope: {scope}")
        target = paths[0]
        summary = {
            "provider": "npm", "mirror_id": mirror.get("id"), "url": url,
            "scope": scope, "path": str(target), "dry_run": dry_run,
            "action": "set registry",
        }
        if dry_run:
            return summary

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
            if target.exists():
                self.backup.create_backup(target, provider="npm", operation="set")
            output: list[str] = []
            replaced = False
            for line in lines:
                key, sep, _ = line.partition("=")
                if sep and key.strip().lower() == "registry":
                    if not replaced:
                        output.append(f"registry={url}")
                        replaced = True
                else:
                    output.append(line)
            if not replaced:
                output.append(f"registry={url}")
            target.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
        except PermissionError as e:
            raise ProviderError(f"Permission denied writing {target}; use an elevated shell for system scope") from e
        summary["status"] = "applied"
        return summary

    def reset(self, *, dry_run: bool = False, scope: str = "user") -> dict[str, Any]:
        paths = self._npmrc_paths(scope)
        if not paths:
            raise ProviderError(f"Unsupported npm configuration scope: {scope}")
        target = paths[0]
        summary = {"provider": "npm", "path": str(target), "scope": scope, "dry_run": dry_run, "action": "reset registry"}
        if not target.exists():
            summary["status"] = "nothing to reset"
            return summary
        lines = target.read_text(encoding="utf-8").splitlines()
        kept = [line for line in lines if not ("=" in line and line.partition("=")[0].strip().lower() == "registry")]
        if len(kept) == len(lines):
            summary["status"] = "no registry found"
            return summary
        if dry_run:
            return summary
        try:
            self.backup.create_backup(target, provider="npm", operation="reset")
            if kept:
                target.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
            else:
                target.unlink()
        except PermissionError as e:
            raise ProviderError(f"Permission denied updating {target}; use an elevated shell for system scope") from e
        summary["status"] = "removed registry"
        return summary
