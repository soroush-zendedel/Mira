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
        mirrors = self.registry.list_mirrors(provider="debian", countries=countries)
        try:
            upstream = self._upstream_mirror()
            if not any(m.get("url", "").rstrip("/") == upstream["url"].rstrip("/") for m in mirrors):
                mirrors.append(upstream)
        except ProviderError:
            pass
        return mirrors

    @staticmethod
    def _os_release() -> dict[str, str]:
        result: dict[str, str] = {}
        try:
            for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
                key, sep, value = line.partition("=")
                if sep:
                    result[key] = value.strip().strip('"').strip("'")
        except OSError:
            pass
        return result

    def _distribution_family(self) -> str:
        info = self._os_release()
        identity = " ".join((info.get("ID", ""), info.get("ID_LIKE", ""))).lower().split()
        if "ubuntu" in identity:
            return "ubuntu"
        if "debian" in identity:
            return "debian"
        raise ProviderError("Mira APT mirror selection supports Debian and Ubuntu releases only")

    def _detect_codename(self) -> str:
        info = self._os_release()
        # Ubuntu derivatives such as Mint use their own lsb_release codename,
        # while Ubuntu archives are indexed by the Ubuntu base codename.
        if info.get("UBUNTU_CODENAME"):
            return info["UBUNTU_CODENAME"]
        try:
            out = subprocess.check_output(
                ["lsb_release", "-cs"], stderr=subprocess.DEVNULL, text=True, timeout=5
            )
            return out.strip()
        except Exception:
            pass
        if info.get("VERSION_CODENAME"):
            return info["VERSION_CODENAME"]
        raise ProviderError("Could not detect this system's Debian/Ubuntu release codename")

    def _components(self) -> list[str]:
        family = self._distribution_family()
        if family == "ubuntu":
            return ["main", "restricted", "universe", "multiverse"]
        return ["main", "contrib", "non-free", "non-free-firmware"]

    def _upstream_mirror(self) -> dict[str, Any]:
        family = self._distribution_family()
        if family == "ubuntu":
            url = "https://archive.ubuntu.com/ubuntu"
            name = "Ubuntu Official Archive (global fallback)"
        else:
            url = "https://deb.debian.org/debian"
            name = "Debian Official Archive (global fallback)"
        return {
            "id": f"{family}-official-upstream",
            "name": name,
            "url": url,
            "country": "global",
            "provider": "debian",
            "enabled": True,
            "priority": 10,
        }

    def _detect_arch(self) -> str:
        machine = platform.machine().lower()
        mapping = {
            "x86_64": "amd64",
            "amd64": "amd64",
            "aarch64": "arm64",
            "armv7l": "armhf",
            "i686": "i386",
            "i386": "i386",
            "ppc64le": "ppc64el",
            "ppc64el": "ppc64el",
            "s390x": "s390x",
            "riscv64": "riscv64",
            "armv6l": "armel",
        }
        if machine not in mapping:
            raise ProviderError(f"Unsupported APT architecture: {machine}")
        return mapping[machine]

    def check_mirror(self, mirror: dict[str, Any]) -> dict[str, Any]:
        base = mirror["url"].rstrip("/")
        try:
            codename = self._detect_codename()
            components = set(self._components())
            architecture = self._detect_arch()
        except ProviderError as e:
            return {"available": False, "valid": False, "latency_ms": None, "error": str(e), "stability": 0.0}

        last_err = None
        best_latency = None
        for filename in ("InRelease", "Release"):
            url = f"{base}/dists/{codename}/{filename}"
            try:
                status, headers, body, latency = fetch_url(url, timeout=8.0, max_size=512 * 1024)
                if best_latency is None:
                    best_latency = latency
                if not 200 <= status < 300:
                    last_err = f"HTTP {status} for {url}"
                    continue
                text = (body or b"").decode("utf-8", errors="replace")
                fields = {
                    match.group(1).lower(): match.group(2).strip()
                    for match in re.finditer(r"^([A-Za-z0-9-]+):\s*(.*?)\s*$", text, re.MULTILINE)
                }
                release_name = fields.get("codename") or fields.get("suite")
                missing_components = components - set(fields.get("components", "").split())
                architectures = set(fields.get("architectures", "").split())
                if release_name and release_name != codename:
                    last_err = f"Release codename {release_name!r} does not match {codename!r}"
                    continue
                if missing_components:
                    last_err = f"Missing components for {codename}: {', '.join(sorted(missing_components))}"
                    continue
                if architectures and architecture not in architectures:
                    last_err = f"Architecture {architecture} is not supported by {codename}"
                    continue
                if fields.get("components"):
                    return {
                        "available": True,
                        "valid": True,
                        "latency_ms": latency,
                        "error": None,
                        "stability": 0.75,
                        "codename": codename,
                        "distribution": self._distribution_family(),
                        "architecture": architecture,
                    }
                last_err = f"Release metadata at {url} has no Components field"
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
        family = self._distribution_family()
        components = " ".join(self._components())
        keyring = (
            "/usr/share/keyrings/ubuntu-archive-keyring.gpg"
            if family == "ubuntu"
            else "/usr/share/keyrings/debian-archive-keyring.gpg"
        )
        content = f"""# Written by Mira - do not edit manually unless you know what you are doing
Types: deb
URIs: {url}
Suites: {codename}
Components: {components}
Architectures: {arch}
Signed-By: {keyring}
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
