"""Health check result cache."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from mira.constants import DEFAULT_HEALTH_CACHE_TTL
from mira.utils.filesystem import atomic_write_json, read_json
from mira.utils.platform import ensure_dir


class HealthCache:
    """Simple JSON file based cache for mirror health results."""

    def __init__(self, cache_dir: Path, ttl: float = DEFAULT_HEALTH_CACHE_TTL):
        self.cache_dir = Path(cache_dir)
        self.ttl = ttl
        self.path = self.cache_dir / "health_cache.json"
        self._data: dict[str, Any] = {}
        self._loaded = False

    def _key(self, provider: str, mirror_id: str) -> str:
        return f"{provider}:{mirror_id}"

    def load(self) -> None:
        ensure_dir(self.cache_dir)
        if self.path.exists():
            try:
                self._data = read_json(self.path)
                if not isinstance(self._data, dict):
                    self._data = {}
            except Exception:
                self._data = {}
        else:
            self._data = {}
        self._loaded = True

    def save(self) -> None:
        ensure_dir(self.cache_dir)
        # prune expired
        now = time.time()
        pruned = {
            k: v
            for k, v in self._data.items()
            if isinstance(v, dict) and (now - v.get("timestamp", 0)) < self.ttl * 2
        }
        self._data = pruned
        atomic_write_json(self.path, self._data)

    def get(self, provider: str, mirror_id: str) -> dict[str, Any] | None:
        if not self._loaded:
            self.load()
        key = self._key(provider, mirror_id)
        entry = self._data.get(key)
        if not entry or not isinstance(entry, dict):
            return None
        if time.time() - entry.get("timestamp", 0) > self.ttl:
            return None
        return entry

    def set(self, provider: str, mirror_id: str, result: dict[str, Any]) -> None:
        if not self._loaded:
            self.load()
        key = self._key(provider, mirror_id)
        entry = dict(result)
        entry["timestamp"] = time.time()
        entry["provider"] = provider
        entry["mirror_id"] = mirror_id
        self._data[key] = entry

    def clear(self) -> None:
        self._data = {}
        self.save()