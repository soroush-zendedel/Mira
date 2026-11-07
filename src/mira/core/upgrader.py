"""Application self-upgrade from GitHub Releases (no pip)."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from mira import __version__
from mira.constants import GITHUB_API_BASE, GITHUB_OWNER, GITHUB_REPO
from mira.exceptions import NetworkError, UpdateError
from mira.utils.filesystem import sha256_bytes
from mira.utils.network import fetch_url
from mira.utils.platform import get_user_data_dir, is_windows
from mira.utils.terminal import Terminal


class AppUpgrader:
    """
    Upgrade Mira from the latest GitHub Release.

    - Frozen binary (PyInstaller): replace the executable itself.
    - Source install: replace the src/mira package tree the launcher uses.
    """

    def __init__(self, install_root: Path | None = None, term: Terminal | None = None):
        self.term = term or Terminal()
        self.frozen = bool(getattr(sys, "frozen", False))
        self.executable = Path(sys.executable).resolve() if self.frozen else None

        if install_root is not None:
            self.install_root = Path(install_root)
            self.src_dir = self.install_root / "src" / "mira"
        else:
            self.install_root, self.src_dir = self._detect_source_layout()

    def _detect_source_layout(self) -> tuple[Path, Path]:
        """Find the source install tree that should be replaced."""
        this = Path(__file__).resolve()
        # Package dir: .../mira
        pkg = this.parents[1]
        # Prefer user install location
        home = Path.home()
        candidates = [
            home / ".local" / "share" / "mira" / "src" / "mira",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Mira" / "src" / "mira",
            Path("/usr/lib/mira/src/mira"),
            pkg,  # currently running package
        ]
        for c in candidates:
            if c and c.is_dir() and (c / "cli.py").exists() and (c / "__init__.py").exists():
                # install root is parent of src/mira or parent of mira if layout is root/src/mira
                if c.parent.name == "src":
                    return c.parent.parent, c
                return c.parent, c
        # Fallback
        if pkg.parent.name == "src":
            return pkg.parent.parent, pkg
        return pkg.parent, pkg

    def _latest_release(self) -> dict[str, Any]:
        url = f"{GITHUB_API_BASE}/releases/latest"
        status, _, body, _ = fetch_url(
            url,
            headers={"Accept": "application/vnd.github+json"},
            timeout=15.0,
        )
        if status == 404:
            raise UpdateError(
                "No GitHub Release found yet. Publish a release on "
                f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
            )
        if status != 200:
            raise NetworkError(f"GitHub API HTTP {status}")
        return json.loads(body.decode("utf-8"))

    def check(self) -> tuple[bool, str, str]:
        rel = self._latest_release()
        remote = (rel.get("tag_name") or "").lstrip("v")
        current = __version__
        return remote != current and bool(remote), current, remote or "unknown"

    def _asset_url_for_platform(self, release: dict[str, Any]) -> tuple[str, str]:
        """
        Return (url, kind) where kind is 'binary' or 'source'.
        Prefer platform binary for frozen installs; source zip otherwise.
        """
        assets = release.get("assets") or []
        names = {((a.get("name") or "").lower()): a for a in assets}

        if self.frozen or self._looks_like_binary_install():
            if is_windows():
                for key in ("mira-windows-x86_64.exe", "mira.exe", "mira-windows.exe"):
                    if key in names:
                        return names[key]["browser_download_url"], "binary"
            else:
                for key in ("mira-linux-x86_64", "mira-linux", "mira"):
                    if key in names:
                        return names[key]["browser_download_url"], "binary"

        # Source zip assets
        for a in assets:
            name = (a.get("name") or "").lower()
            if name.endswith(".zip") and "mira" in name and "source" in name:
                return a["browser_download_url"], "source"
        for a in assets:
            name = (a.get("name") or "").lower()
            if name.endswith(".zip") and "mira" in name and "windows" not in name:
                return a["browser_download_url"], "source"

        zipball = release.get("zipball_url")
        if zipball:
            return zipball, "source"
        raise UpdateError("No downloadable upgrade asset found on the latest release.")

    def _looks_like_binary_install(self) -> bool:
        """True when argv0 / which mira is a single-file binary, not a .cmd/.sh launcher."""
        try:
            exe = shutil.which("mira")
            if not exe:
                return self.frozen
            p = Path(exe).resolve()
            if p.suffix.lower() in {".cmd", ".bat", ".ps1"}:
                return False
            # Shell script launcher?
            try:
                head = p.read_bytes()[:64]
                if head.startswith(b"#!") and b"python" in head:
                    return False
            except OSError:
                pass
            return True
        except Exception:
            return self.frozen

    def _replace_binary(self, data: bytes, remote: str) -> None:
        target = self.executable
        if target is None:
            which = shutil.which("mira")
            if which:
                target = Path(which).resolve()
        if target is None:
            raise UpdateError("Cannot locate mira executable to replace.")

        self.term.info(f"Replacing binary: {target}")
        # Write to temp next to target then replace
        tmp = target.with_name(target.name + ".new")
        try:
            tmp.write_bytes(data)
            if not is_windows():
                tmp.chmod(tmp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError as e:
            raise UpdateError(f"Cannot write new binary: {e}") from e

        if is_windows():
            # Running exe may be locked — stage rename + schedule
            old = target.with_name(target.name + ".old")
            try:
                if old.exists():
                    old.unlink()
                if target.exists():
                    target.rename(old)
                tmp.rename(target)
                try:
                    old.unlink(missing_ok=True)
                except OSError:
                    pass
            except OSError:
                # Delayed replace via cmd after exit
                script = Path(os.environ.get("TEMP", ".")) / f"mira_upgrade_{os.getpid()}.cmd"
                lines = [
                    "@echo off",
                    "timeout /t 2 /nobreak >nul",
                    f'move /y "{tmp}" "{target}"',
                    f'if exist "{old}" del /f /q "{old}"',
                    'del "%~f0"',
                ]
                script.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
                subprocess.Popen(
                    ["cmd.exe", "/c", "start", "/min", "", str(script)],
                    close_fds=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.term.warning("Binary is locked; replacement scheduled after process exit.")
                return
        else:
            # Atomic-ish replace on Unix
            try:
                os.replace(str(tmp), str(target))
            except OSError as e:
                # /usr/local/bin may need sudo
                if not os.access(target.parent, os.W_OK):
                    self.term.info("Write permission denied; trying sudo...")
                    r = subprocess.run(
                        ["sudo", "mv", "-f", str(tmp), str(target)],
                        check=False,
                    )
                    if r.returncode != 0:
                        raise UpdateError(
                            f"Failed to replace {target}. Re-run with sudo or install to a user path."
                        ) from e
                else:
                    raise UpdateError(f"Failed to replace binary: {e}") from e

        self.term.success(f"Binary upgraded to {remote}.")
        self.term.info("Run `mira --version` again (new process) to confirm.")

    def _replace_source(self, data: bytes, remote: str) -> None:
        with tempfile.TemporaryDirectory(prefix="mira_upgrade_") as tmp:
            tmp_path = Path(tmp)
            zip_path = tmp_path / "release.zip"
            zip_path.write_bytes(data)
            extract_dir = tmp_path / "extract"
            extract_dir.mkdir()
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            package_src = None
            for candidate in extract_dir.rglob("mira"):
                if (
                    candidate.is_dir()
                    and (candidate / "__init__.py").exists()
                    and (candidate / "cli.py").exists()
                ):
                    package_src = candidate
                    break
            if package_src is None:
                raise UpdateError("Could not locate mira package inside the release archive.")

            target = self.src_dir
            self.term.info(f"Replacing source package: {target}")
            backup = target.with_name("mira.bak")
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            if target.exists():
                target.rename(backup)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(package_src, target)
                # Sync VERSION next to install root when present
                ver_file = self.install_root / "VERSION"
                try:
                    ver_file.write_text(remote + "\n", encoding="utf-8")
                except OSError:
                    pass
            except Exception as e:
                if backup.exists():
                    if target.exists():
                        shutil.rmtree(target, ignore_errors=True)
                    backup.rename(target)
                raise UpdateError(f"Failed to replace application files: {e}") from e
            finally:
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)

        self.term.success(f"Source install upgraded to {remote}.")
        self.term.info("Run `mira --version` again to confirm.")

    def upgrade(self, *, dry_run: bool = False) -> str:
        self.term.info("Checking latest GitHub Release...")
        release = self._latest_release()
        remote = (release.get("tag_name") or "").lstrip("v")
        current = __version__
        self.term.info(f"Installed: {current}  |  Latest: {remote or 'unknown'}")
        if remote and remote == current:
            self.term.info("Already up to date.")
            return current

        url, kind = self._asset_url_for_platform(release)
        self.term.info(f"Downloading ({kind}): {url}")
        if dry_run:
            self.term.info("(dry-run - download and replace skipped)")
            return remote or current

        status, _, body, _ = fetch_url(url, timeout=120.0, max_size=80 * 1024 * 1024)
        if status != 200:
            raise NetworkError(f"Download failed HTTP {status}")
        digest = sha256_bytes(body)
        self.term.info(f"Downloaded {len(body)} bytes (sha256={digest[:16]}...)")

        if kind == "binary":
            self._replace_binary(body, remote or "latest")
        else:
            # If we are frozen but only source is available, warn clearly
            if self.frozen:
                self.term.warning(
                    "Only a source archive is available; cannot fully upgrade a frozen binary."
                )
            self._replace_source(body, remote or "latest")

        self.term.info("User configuration, database, cache and backups were preserved.")
        return remote or current
