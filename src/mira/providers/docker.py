"""Docker Engine registry-mirror provider."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from mira.core.registry import MirrorRegistry
from mira.exceptions import NetworkError, ProviderError
from mira.providers.base import RepositoryProvider
from mira.services.backup import BackupService
from mira.utils.network import fetch_url
from mira.utils.platform import is_linux


class DockerProvider(RepositoryProvider):
    name = "docker"

    DAEMON_JSON = Path("/etc/docker/daemon.json")

    def __init__(self, registry: MirrorRegistry, backup: BackupService | None = None):
        self.registry = registry
        self.backup = backup or BackupService()

    def list_mirrors(self, countries: list[str] | None = None) -> list[dict[str, Any]]:
        return self.registry.list_mirrors(provider="docker", countries=countries)

    def check_mirror(self, mirror: dict[str, Any]) -> dict[str, Any]:
        url = mirror["url"].rstrip("/")
        # Docker registry v2 API
        candidates = [
            f"{url}/v2/",
            f"{url}/v2/_catalog",
        ]
        last_err = None
        for check_url in candidates:
            try:
                status, headers, body, latency = fetch_url(check_url, timeout=5.0)
                # 200 or 401 (auth required) are both signs of a live registry
                if status in (200, 401, 403):
                    docker_header = headers.get("Docker-Distribution-Api-Version") or headers.get(
                        "docker-distribution-api-version"
                    )
                    valid = bool(docker_header) or status in (200, 401)
                    return {
                        "available": True,
                        "valid": valid,
                        "latency_ms": latency,
                        "error": None if valid else "Missing Docker-Distribution-Api-Version",
                        "stability": 0.7 if valid else 0.3,
                    }
            except NetworkError as e:
                last_err = str(e)
                continue
        return {
            "available": False,
            "valid": False,
            "latency_ms": None,
            "error": last_err or "Registry endpoint unreachable",
            "stability": 0.0,
        }

    def _load_daemon(self) -> dict[str, Any]:
        if not self.DAEMON_JSON.exists():
            return {}
        try:
            return json.loads(self.DAEMON_JSON.read_text(encoding="utf-8"))
        except Exception as e:
            raise ProviderError(f"Invalid daemon.json: {e}") from e

    def get_current(self) -> dict[str, Any] | None:
        data = self._load_daemon()
        mirrors = data.get("registry-mirrors")
        if mirrors:
            return {"urls": list(mirrors), "path": str(self.DAEMON_JSON)}
        return None

    def apply(self, mirror: dict[str, Any], *, dry_run: bool = False, **options: Any) -> dict[str, Any]:
        if not is_linux():
            raise ProviderError("Docker provider currently supports Linux Docker Engine only")
        url = mirror["url"].rstrip("/")
        summary = {
            "provider": "docker",
            "mirror_id": mirror.get("id"),
            "url": url,
            "path": str(self.DAEMON_JSON),
            "dry_run": dry_run,
            "action": "set registry-mirrors",
            "note": "Docker restart required for changes to take effect. Mira will not restart Docker automatically.",
        }
        data = self._load_daemon()
        data["registry-mirrors"] = [url]
        new_text = json.dumps(data, indent=2) + "\n"
        if dry_run:
            summary["content_preview"] = new_text[:300]
            return summary

        if self.DAEMON_JSON.exists():
            self.backup.create_backup(self.DAEMON_JSON, provider="docker", operation="set")
        try:
            self.DAEMON_JSON.parent.mkdir(parents=True, exist_ok=True)
            self.DAEMON_JSON.write_text(new_text, encoding="utf-8")
            # basic validation
            json.loads(self.DAEMON_JSON.read_text(encoding="utf-8"))
            summary["status"] = "applied"
        except PermissionError as e:
            raise ProviderError(
                f"Permission denied writing {self.DAEMON_JSON}.\n"
                "  Linux:   sudo mira docker set\n"
                "  Or run the set command from a root shell.\n"
                "  After applying, restart Docker manually:\n"
                "          sudo systemctl restart docker\n"
                "  Mira never restarts Docker automatically."
            ) from e
        return summary

    def reset(self, *, dry_run: bool = False) -> dict[str, Any]:
        summary = {
            "provider": "docker",
            "path": str(self.DAEMON_JSON),
            "dry_run": dry_run,
            "action": "remove registry-mirrors",
        }
        if not self.DAEMON_JSON.exists():
            summary["status"] = "nothing to reset"
            return summary
        data = self._load_daemon()
        if "registry-mirrors" not in data:
            summary["status"] = "no registry-mirrors key"
            return summary
        if dry_run:
            return summary
        self.backup.create_backup(self.DAEMON_JSON, provider="docker", operation="reset")
        del data["registry-mirrors"]
        try:
            self.DAEMON_JSON.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            summary["status"] = "removed registry-mirrors"
        except PermissionError as e:
            raise ProviderError(f"Permission denied: {e}") from e
        return summary