"""Debian APT repository provider."""

from __future__ import annotations

import os
import platform
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

from mira.core.registry import MirrorRegistry
from mira.exceptions import NetworkError, ProviderError
from mira.providers.base import RepositoryProvider
from mira.services.backup import BackupService
from mira.utils.filesystem import atomic_write
from mira.utils.network import fetch_url
from mira.utils.platform import is_linux


class DebianProvider(RepositoryProvider):
    name = "debian"

    APT_MAIN_SOURCES = Path("/etc/apt/sources.list")
    APT_SOURCE_PARTS = Path("/etc/apt/sources.list.d")
    MIRA_SOURCES = Path("/etc/apt/sources.list.d/mira.sources")
    # Keep disabled sources OUT of sources.list.d so apt does not emit
    # "Ignoring file '...mira-disabled' ... invalid filename extension".
    DISABLED_DIR = Path("/var/lib/mira/apt-disabled")
    # Legacy in-place suffix (older Mira versions). Still recognised on reset.
    DISABLED_SUFFIX = ".mira-disabled"

    def __init__(self, registry: MirrorRegistry, backup: BackupService | None = None):
        self.registry = registry
        self.backup = backup or BackupService()

    def _disabled_path_for(self, source: Path) -> Path:
        """Return the stash path for an active APT source file."""
        source = source.resolve() if source.exists() else source
        if source == self.APT_MAIN_SOURCES or source.name == "sources.list" and source.parent == self.APT_MAIN_SOURCES.parent:
            return self.DISABLED_DIR / "sources.list"
        # files under sources.list.d/
        return self.DISABLED_DIR / "sources.list.d" / source.name

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

    def _archive_keyring(self) -> Path:
        family = self._distribution_family()
        name = "ubuntu-archive-keyring.gpg" if family == "ubuntu" else "debian-archive-keyring.gpg"
        return Path("/usr/share/keyrings") / name

    def _archive_keyring_available(self) -> bool:
        return self._archive_keyring().is_file()

    def _active_source_files(self) -> list[Path]:
        """Return active APT source files Mira will temporarily take ownership of."""
        files: set[Path] = set()
        if self.APT_MAIN_SOURCES.is_file():
            files.add(self.APT_MAIN_SOURCES)
        if self.APT_SOURCE_PARTS.is_dir():
            for pattern in ("*.list", "*.sources"):
                files.update(
                    path
                    for path in self.APT_SOURCE_PARTS.glob(pattern)
                    if path.is_file() and re.fullmatch(r"[A-Za-z0-9_.-]+", path.name)
                )
        files.discard(self.MIRA_SOURCES)
        return sorted(files, key=lambda path: str(path))

    def _disabled_source_pairs(self) -> list[tuple[Path, Path]]:
        """
        Find source files disabled by Mira and their original paths.

        Prefer the stash under DISABLED_DIR (current behaviour). Also recognise
        legacy in-place renames (``*.mira-disabled`` next to the original) so
        older installs can still be reset cleanly.
        """
        pairs: list[tuple[Path, Path]] = []
        seen_originals: set[Path] = set()

        # Current layout: /var/lib/mira/apt-disabled/...
        main_disabled = self.DISABLED_DIR / "sources.list"
        if main_disabled.is_file():
            pairs.append((self.APT_MAIN_SOURCES, main_disabled))
            seen_originals.add(self.APT_MAIN_SOURCES)
        parts_dir = self.DISABLED_DIR / "sources.list.d"
        if parts_dir.is_dir():
            for path in sorted(parts_dir.iterdir()):
                if not path.is_file():
                    continue
                if path.suffix not in {".list", ".sources"}:
                    continue
                original = self.APT_SOURCE_PARTS / path.name
                pairs.append((original, path))
                seen_originals.add(original)

        # Legacy layout: rename in place with .mira-disabled suffix
        if self.APT_MAIN_SOURCES.parent.is_dir():
            legacy_main = self.APT_MAIN_SOURCES.parent / f"sources.list{self.DISABLED_SUFFIX}"
            if legacy_main.is_file() and self.APT_MAIN_SOURCES not in seen_originals:
                pairs.append((self.APT_MAIN_SOURCES, legacy_main))
                seen_originals.add(self.APT_MAIN_SOURCES)
        if self.APT_SOURCE_PARTS.is_dir():
            for path in self.APT_SOURCE_PARTS.glob(f"*{self.DISABLED_SUFFIX}"):
                if not path.is_file():
                    continue
                original = path.with_name(path.name[: -len(self.DISABLED_SUFFIX)])
                if original.suffix not in {".list", ".sources"}:
                    continue
                if original in seen_originals:
                    continue
                pairs.append((original, path))
                seen_originals.add(original)

        return sorted(pairs, key=lambda pair: str(pair[0]))

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
        components = " ".join(self._components())
        keyring = self._archive_keyring()
        if not self._archive_keyring_available():
            raise ProviderError(f"Required APT archive keyring is missing: {keyring}")
        content = f"""# Written by Mira - do not edit manually unless you know what you are doing
Types: deb
URIs: {url}
Suites: {codename}
Components: {components}
Architectures: {arch}
Signed-By: {keyring}
"""
        active_sources = self._active_source_files()
        disabled_sources = [(source, self._disabled_path_for(source)) for source in active_sources]
        conflicts = [str(disabled) for _, disabled in disabled_sources if disabled.exists()]
        if conflicts:
            raise ProviderError(
                "Cannot safely disable APT sources because Mira's saved source file already exists: "
                + ", ".join(conflicts)
                + ". Run 'mira debian reset' or inspect those files first."
            )
        summary = {
            "provider": "debian",
            "mirror_id": mirror.get("id"),
            "url": url,
            "path": str(self.MIRA_SOURCES),
            "codename": codename,
            "dry_run": dry_run,
            "action": "disable existing APT sources and write mira.sources",
            "disabled_sources": [str(source) for source, _ in disabled_sources],
            "disabled_stash": str(self.DISABLED_DIR),
        }
        if dry_run:
            summary["content_preview"] = content
            return summary

        try:
            for source, _ in disabled_sources:
                self.backup.create_backup(source, provider="debian", operation="set-source")
        except OSError as e:
            raise ProviderError(f"Could not back up active APT source files; nothing was changed: {e}") from e
        previous_mira: bytes | None = None
        previous_mode: int | None = None
        if self.MIRA_SOURCES.exists():
            self.backup.create_backup(self.MIRA_SOURCES, provider="debian", operation="set")
            previous_mira = self.MIRA_SOURCES.read_bytes()
            previous_mode = stat.S_IMODE(self.MIRA_SOURCES.stat().st_mode)
        moved: list[tuple[Path, Path]] = []
        try:
            self.MIRA_SOURCES.parent.mkdir(parents=True, exist_ok=True)
            self.DISABLED_DIR.mkdir(parents=True, exist_ok=True)
            (self.DISABLED_DIR / "sources.list.d").mkdir(parents=True, exist_ok=True)
            for source, disabled in disabled_sources:
                disabled.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, disabled)
                moved.append((source, disabled))
            atomic_write(self.MIRA_SOURCES, content)
            os.chmod(self.MIRA_SOURCES, 0o644)
            summary["status"] = "applied"
        except OSError as e:
            for source, disabled in reversed(moved):
                if disabled.exists() and not source.exists():
                    os.replace(disabled, source)
            if previous_mira is None:
                self.MIRA_SOURCES.unlink(missing_ok=True)
            else:
                atomic_write(self.MIRA_SOURCES, previous_mira)
                if previous_mode is not None:
                    os.chmod(self.MIRA_SOURCES, previous_mode)
            if isinstance(e, PermissionError):
                raise ProviderError(
                    f"Permission denied updating APT sources.\n"
                    "  Linux:   sudo mira debian set\n"
                    "  Mira needs elevated privileges to manage system APT source files."
                ) from e
            raise ProviderError(
                f"Could not safely update APT sources: {e}"
            ) from e
        return summary

    def reset(self, *, dry_run: bool = False) -> dict[str, Any]:
        summary = {
            "provider": "debian",
            "path": str(self.MIRA_SOURCES),
            "dry_run": dry_run,
            "action": "remove mira.sources and restore previous APT sources",
        }
        disabled_sources = self._disabled_source_pairs()
        if not self.MIRA_SOURCES.exists() and not disabled_sources:
            summary["status"] = "nothing to reset"
            return summary
        conflicts = [str(original) for original, _ in disabled_sources if original.exists()]
        if conflicts:
            raise ProviderError(
                "Cannot restore saved APT sources because these paths are already occupied: "
                + ", ".join(conflicts)
                + ". Move or merge those files, then run 'mira debian reset' again."
            )
        if dry_run:
            summary["restore_sources"] = [str(original) for original, _ in disabled_sources]
            return summary
        try:
            for _, disabled in disabled_sources:
                self.backup.create_backup(disabled, provider="debian", operation="reset-source")
            if self.MIRA_SOURCES.exists():
                self.backup.create_backup(self.MIRA_SOURCES, provider="debian", operation="reset")
        except OSError as e:
            raise ProviderError(f"Could not back up APT sources before reset; nothing was changed: {e}") from e
        mira_data = self.MIRA_SOURCES.read_bytes() if self.MIRA_SOURCES.exists() else None
        mira_mode = stat.S_IMODE(self.MIRA_SOURCES.stat().st_mode) if self.MIRA_SOURCES.exists() else None
        removed_mira = False
        restored: list[tuple[Path, Path]] = []
        try:
            self.MIRA_SOURCES.unlink(missing_ok=True)
            removed_mira = True
            for original, disabled in disabled_sources:
                os.replace(disabled, original)
                restored.append((original, disabled))
            summary["status"] = "removed"
        except OSError as e:
            for original, disabled in reversed(restored):
                if original.exists() and not disabled.exists():
                    os.replace(original, disabled)
            if removed_mira and mira_data is not None:
                atomic_write(self.MIRA_SOURCES, mira_data)
                if mira_mode is not None:
                    os.chmod(self.MIRA_SOURCES, mira_mode)
            if isinstance(e, PermissionError):
                raise ProviderError("Permission denied restoring APT source files; run 'sudo mira debian reset'.") from e
            raise ProviderError(f"Could not safely restore APT sources: {e}") from e
        return summary
