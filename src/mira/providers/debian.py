"""Debian APT repository provider."""

from __future__ import annotations

import platform
import re
import subprocess
from pathlib import Path
from typing import Any

from mira.core.registry import MirrorRegistry
from mira.exceptions import NetworkError, ProviderError
from mira.providers.base import RepositoryProvider
from mira.services.backup import BackupService
from mira.utils.network import fetch_url
from mira.utils.platform import is_linux


class DebianProvider(RepositoryProvider):
    name = "debian"

    MIRA_SOURCES = Path("/etc/apt/sources.list.d/mira.sources")

    def __init__(self, registry: MirrorRegistry, backup: BackupService | None = None):
        self.registry = registry
        self.backup = backup or BackupService()

    def list_mirrors(self, countries: list[str] | None = None) -> list[dict[str, Any]]:
        return self.registry.list_mirrors(provider="debian", countries=countries)

    def _detect_codename(self) -> str:
        try:
            out = subprocess.check_output(
                ["lsb_release", "-cs"], stderr=subprocess.DEVNULL, text=True, timeout=5
            )
            return out.strip()
        except Exception:
            pass
        # fallback /etc/os-release
        try:
            text = Path("/etc/os-release").read_text(encoding="utf-8")
            m = re.search(r"VERSION_CODENAME=(.+)", text)
            if m:
                return m.group(1).strip().strip('"')
        except Exception:
            pass
        return "bookworm"  # safe default for recent Debian

    def _detect_arch(self) -> str:
        machine = platform.machine().lower()
        mapping = {
            "x86_64": "amd64",
            "amd64": "amd64",
            "aarch64": "arm64",
            "armv7l": "armhf",
            "i686": "i386",
            "i386": "i386",
        }
        return mapping.get(machine, "amd64")

    def check_mirror(self, mirror: dict[str, Any]) -> dict[str, Any]:
        base = mirror["url"].rstrip("/")
        codename = self._detect_codename()
        # Try detected codename plus common Debian/Ubuntu suites (mirrors differ)
        suites = []
        for s in (codename, "stable", "bookworm", "jammy", "noble", "testing"):
            if s and s not in suites:
                suites.append(s)
        candidates = []
        for suite in suites:
            candidates.append(f"{base}/dists/{suite}/InRelease")
            candidates.append(f"{base}/dists/{suite}/Release")
        # Root probe as last resort
        candidates.append(base + "/")

        last_err = None
        best_latency = None
        for url in candidates:
            try:
                status, headers, body, latency = fetch_url(url, timeout=8.0, max_size=512 * 1024)
                if best_latency is None:
                    best_latency = latency
                if not (200 <= status < 400):
                    last_err = f"HTTP {status} for {url}"
                    continue
                text = (body or b"").decode("utf-8", errors="replace")
                valid = (
                    "Origin:" in text
                    or "Suite:" in text
                    or "Codename:" in text
                    or "SHA256:" in text
                    or "MD5Sum:" in text
                    or "Components:" in text
                    or status == 200 and len(body or b"") > 64
                )
                if valid:
                    return {
                        "available": True,
                        "valid": True,
                        "latency_ms": latency,
                        "error": None,
                        "stability": 0.75,
                        "codename": codename,
                    }
                last_err = f"Unexpected content at {url}"
            except NetworkError as e:
                last_err = str(e)
                continue
        return {
            "available": False,
            "valid": False,
            "latency_ms": best_latency,
            "error": last_err or "No usable Release/InRelease",
            "stability": 0.0,
        }

    def get_current(self) -> dict[str, Any] | None:
        if self.MIRA_SOURCES.exists():
            try:
                text = self.MIRA_SOURCES.read_text(encoding="utf-8")
                m = re.search(r"URIs:\s*(\S+)", text)
                if m:
                    return {"url": m.group(1), "path": str(self.MIRA_SOURCES)}
            except Exception:
                pass
        return None

    def apply(self, mirror: dict[str, Any], *, dry_run: bool = False, **options: Any) -> dict[str, Any]:
        if not is_linux():
            raise ProviderError("Debian APT provider is only supported on Linux")
        url = mirror["url"].rstrip("/")
        codename = self._detect_codename()
        arch = self._detect_arch()
        content = f"""# Written by Mira - do not edit manually unless you know what you are doing
Types: deb
URIs: {url}
Suites: {codename} {codename}-updates {codename}-backports
Components: main contrib non-free non-free-firmware
Architectures: {arch}
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
"""
        summary = {
            "provider": "debian",
            "mirror_id": mirror.get("id"),
            "url": url,
            "path": str(self.MIRA_SOURCES),
            "codename": codename,
            "dry_run": dry_run,
            "action": "write mira.sources",
        }
        if dry_run:
            summary["content_preview"] = content[:200]
            return summary

        if self.MIRA_SOURCES.exists():
            self.backup.create_backup(self.MIRA_SOURCES, provider="debian", operation="set")
        try:
            self.MIRA_SOURCES.parent.mkdir(parents=True, exist_ok=True)
            self.MIRA_SOURCES.write_text(content, encoding="utf-8")
            summary["status"] = "applied"
        except PermissionError as e:
            raise ProviderError(
                f"Permission denied writing {self.MIRA_SOURCES}.\n"
                "  Linux:   sudo mira debian set\n"
                "  Mira only needs elevated privileges for system APT files."
            ) from e
        return summary

    def reset(self, *, dry_run: bool = False) -> dict[str, Any]:
        summary = {
            "provider": "debian",
            "path": str(self.MIRA_SOURCES),
            "dry_run": dry_run,
            "action": "remove mira.sources",
        }
        if not self.MIRA_SOURCES.exists():
            summary["status"] = "nothing to reset"
            return summary
        if dry_run:
            return summary
        self.backup.create_backup(self.MIRA_SOURCES, provider="debian", operation="reset")
        try:
            self.MIRA_SOURCES.unlink()
            summary["status"] = "removed"
        except PermissionError as e:
            raise ProviderError(f"Permission denied removing {self.MIRA_SOURCES}") from e
        return summary