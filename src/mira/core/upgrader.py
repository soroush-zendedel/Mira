"""Application self-upgrade from GitHub Releases (no pip)."""

from __future__ import annotations

import json
import os
import shutil
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
from mira.utils.platform import get_user_data_dir
from mira.utils.terminal import Terminal


class AppUpgrader:
    """
    Upgrade Mira application files from the latest GitHub Release.

    Strategy:
    - Query GitHub Releases API for the latest release.
    - Prefer a source zipball / attached asset named mira-*.zip or source code zip.
    - Extract into a staging directory, swap into the installed source tree.
    - Preserve user config, database, cache, backups.
    """

    def __init__(self, install_root: Path | None = None, term: Terminal | None = None):
        self.term = term or Terminal()
        # Heuristic: installed layout is <root>/src/mira
        if install_root is None:
            # When running as python -m mira from repo or install
            this = Path(__file__).resolve()
            # .../src/mira/core/upgrader.py -> install root is parents[3] for installed, or parents[3] for repo
            candidates = [
                this.parents[3],  # install: root/src/mira/core -> root
                this.parents[2],  # repo: src/mira/core -> src parent = repo root? parents[2]=src, parents[3]=repo
            ]
            install_root = candidates[0]
        self.install_root = Path(install_root)
        self.src_dir = self.install_root / "src" / "mira"
        if not self.src_dir.exists():
            # fallback: running from editable/repo layout
            repo_src = Path(__file__).resolve().parents[2]  # mira package dir's parent = src
            if (repo_src / "mira").exists():
                self.install_root = repo_src.parent
                self.src_dir = repo_src / "mira"

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
        """Return (needs_upgrade, current_version, remote_version)."""
        try:
            rel = self._latest_release()
        except (NetworkError, UpdateError) as e:
            raise UpdateError(str(e)) from e
        remote = (rel.get("tag_name") or "").lstrip("v")
        current = __version__
        return remote != current and bool(remote), current, remote or "unknown"

    def _pick_asset_url(self, release: dict[str, Any]) -> str:
        assets = release.get("assets") or []
        for a in assets:
            name = (a.get("name") or "").lower()
            if name.endswith(".zip") and "mira" in name:
                return a["browser_download_url"]
        # GitHub source zipball
        zipball = release.get("zipball_url")
        if zipball:
            return zipball
        raise UpdateError("No downloadable zip asset found on the latest release.")

    def upgrade(self, *, dry_run: bool = False) -> str:
        self.term.info("Checking latest GitHub Release...")
        release = self._latest_release()
        remote = (release.get("tag_name") or "").lstrip("v")
        current = __version__
        self.term.info(f"Installed: {current}  |  Latest: {remote or 'unknown'}")
        if remote and remote == current:
            self.term.info("Already up to date.")
            return current

        url = self._pick_asset_url(release)
        self.term.info(f"Downloading: {url}")
        if dry_run:
            self.term.info("(dry-run — download and replace skipped)")
            return remote or current

        status, headers, body, _ = fetch_url(url, timeout=60.0, max_size=50 * 1024 * 1024)
        if status != 200:
            raise NetworkError(f"Download failed HTTP {status}")
        digest = sha256_bytes(body)
        self.term.info(f"Downloaded {len(body)} bytes (sha256={digest[:16]}...)")

        with tempfile.TemporaryDirectory(prefix="mira_upgrade_") as tmp:
            tmp_path = Path(tmp)
            zip_path = tmp_path / "release.zip"
            zip_path.write_bytes(body)
            extract_dir = tmp_path / "extract"
            extract_dir.mkdir()
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            # Find package root containing src/mira or mira/
            package_src = None
            for candidate in extract_dir.rglob("mira"):
                if candidate.is_dir() and (candidate / "__init__.py").exists() and (candidate / "cli.py").exists():
                    package_src = candidate
                    break
            if package_src is None:
                raise UpdateError("Could not locate mira package inside the release archive.")

            target = self.src_dir
            backup = target.with_name("mira.bak")
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            if target.exists():
                target.rename(backup)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(package_src, target)
            except Exception as e:
                if backup.exists():
                    if target.exists():
                        shutil.rmtree(target, ignore_errors=True)
                    backup.rename(target)
                raise UpdateError(f"Failed to replace application files: {e}") from e
            finally:
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)

        self.term.success(f"Upgraded application to {remote or 'latest'}.")
        self.term.info("User configuration, database, cache and backups were preserved.")
        return remote or current
