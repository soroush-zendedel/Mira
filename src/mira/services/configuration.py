"""Shared configuration helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mira.utils.filesystem import atomic_write, read_json


def read_json_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def write_json_config(path: Path, data: dict[str, Any]) -> None:
    import json
    atomic_write(path, json.dumps(data, indent=2) + "\n")