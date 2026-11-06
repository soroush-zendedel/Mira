"""Configuration backup service."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from mira.utils.filesystem import safe_copy
from mira.utils.platform import get_user_data_dir, ensure_dir
from mira.constants import BACKUPS_DIR_NAME


class BackupService:
    def __init__(self, backups_dir: Path | None = None):
        self.backups_dir = backups_dir or (get_user_data_dir() / BACKUPS_DIR_NAME)
        ensure_dir(self.backups_dir)

    def create_backup(self, source: Path, *, provider: str, operation: str) -> Path:
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError(str(source))
        ts = time.strftime("%Y%m%dT%H%M%S")
        name = f"{provider}_{operation}_{source.name}_{ts}"
        dest = self.backups_dir / name
        safe_copy(source, dest)
        # also write a small meta sidecar
        meta = dest.with_suffix(dest.suffix + ".meta")
        meta.write_text(
            f"source={source}\nprovider={provider}\noperation={operation}\ntimestamp={ts}\n",
            encoding="utf-8",
        )
        return dest

    def list_backups(self, provider: str | None = None) -> list[Path]:
        items = sorted(self.backups_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if provider:
            items = [p for p in items if p.name.startswith(provider + "_")]
        return [p for p in items if not p.name.endswith(".meta")]