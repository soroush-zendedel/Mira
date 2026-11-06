"""Mirror database updater from GitHub with integrity verification."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from mira.constants import GITHUB_RAW_BASE, MIRROR_MANIFEST_URL
from mira.exceptions import IntegrityError, NetworkError, UpdateError, ValidationError
from mira.utils.filesystem import atomic_write, atomic_write_json, read_json, sha256_bytes
from mira.utils.platform import ensure_dir
from mira.utils.network import fetch_url
from mira.utils.terminal import Terminal
from mira.utils.validation import validate_manifest, validate_mirrors_file


class DatabaseUpdater:
    """Download and atomically install the official mirror database."""

    def __init__(self, database_dir: Path, term: Terminal | None = None):
        self.database_dir = Path(database_dir)
        self.term = term or Terminal()
        self.raw_base = GITHUB_RAW_BASE

    def _fetch_json(self, url: str) -> dict[str, Any]:
        status, _, body, _ = fetch_url(url)
        if status != 200:
            raise NetworkError(f"HTTP {status} fetching {url}")
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON from {url}: {e}") from e

    def _fetch_bytes(self, url: str) -> bytes:
        status, _, body, _ = fetch_url(url)
        if status != 200:
            raise NetworkError(f"HTTP {status} fetching {url}")
        return body

    def check_for_update(self) -> tuple[bool, str, str]:
        """Return (needs_update, local_version, remote_version)."""
        remote = self._fetch_json(MIRROR_MANIFEST_URL)
        remote = validate_manifest(remote)
        remote_ver = str(remote.get("database_version", "0.0.0"))
        local_ver = "0.0.0"
        manifest_path = self.database_dir / "manifest.json"
        if manifest_path.exists():
            try:
                local = validate_manifest(read_json(manifest_path))
                local_ver = str(local.get("database_version", "0.0.0"))
            except Exception:
                local_ver = "0.0.0"
        return local_ver != remote_ver, local_ver, remote_ver

    def _verify_checksum(self, rel_path: str, body: bytes, expected: dict[str, str] | None) -> None:
        if not expected:
            return
        want = expected.get(rel_path)
        if not want:
            return
        got = sha256_bytes(body)
        if got.lower() != want.lower():
            raise IntegrityError(
                f"Checksum mismatch for {rel_path}: expected {want[:16]}..., got {got[:16]}..."
            )

    def update(self, force: bool = False) -> str:
        """
        Update local database. Returns the new database_version.
        Atomic: stages in temp dir then replaces.
        Verifies SHA-256 checksums from manifest.integrity.files when present.
        """
        self.term.info("Fetching remote manifest...")
        try:
            remote_manifest = self._fetch_json(MIRROR_MANIFEST_URL)
            remote_manifest = validate_manifest(remote_manifest)
        except (NetworkError, ValidationError) as e:
            raise UpdateError(str(e)) from e

        remote_ver = str(remote_manifest.get("database_version", "0.0.0"))
        needs, local_ver, _ = self.check_for_update()
        if not needs and not force and (self.database_dir / "manifest.json").exists():
            self.term.info(f"Database already up to date (v{local_ver}).")
            return local_ver

        countries = remote_manifest.get("countries", [])
        providers = remote_manifest.get("providers", [])
        integrity = remote_manifest.get("integrity") or {}
        checksums = integrity.get("files") if isinstance(integrity, dict) else None
        if isinstance(checksums, dict) and checksums:
            self.term.info(f"Integrity: {len(checksums)} file checksums in manifest.")

        with tempfile.TemporaryDirectory(prefix="mira_db_") as tmp:
            tmp_path = Path(tmp)
            atomic_write_json(tmp_path / "manifest.json", remote_manifest)

            for country in countries:
                for provider in providers:
                    rel = f"{country}/{provider}/mirrors.json"
                    url = f"{self.raw_base}/mirrors/{rel}"
                    dest = tmp_path / country / provider / "mirrors.json"
                    try:
                        self.term.info(f"  Downloading {country}/{provider}...")
                        body = self._fetch_bytes(url)
                        self._verify_checksum(rel, body, checksums)
                        data = json.loads(body.decode("utf-8"))
                        data = validate_mirrors_file(
                            data, expected_country=country, expected_provider=provider
                        )
                        ensure_dir(dest.parent)
                        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
                        atomic_write(dest, text)
                    except NetworkError:
                        self.term.warning(f"  Skipping missing {country}/{provider}")
                        continue
                    except IntegrityError:
                        raise
                    except (ValidationError, json.JSONDecodeError) as e:
                        raise UpdateError(f"Invalid mirrors file for {country}/{provider}: {e}") from e

            ensure_dir(self.database_dir.parent)
            backup = None
            if self.database_dir.exists():
                backup = self.database_dir.with_suffix(".bak")
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
                self.database_dir.rename(backup)

            try:
                shutil.copytree(tmp_path, self.database_dir)
            except Exception as e:
                if backup and backup.exists():
                    if self.database_dir.exists():
                        shutil.rmtree(self.database_dir, ignore_errors=True)
                    backup.rename(self.database_dir)
                raise UpdateError(f"Failed to install database: {e}") from e
            finally:
                if backup and backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)

        self.term.success(f"Mirror database updated to v{remote_ver}.")
        return remote_ver
