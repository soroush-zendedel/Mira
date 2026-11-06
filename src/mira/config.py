"""Mira local configuration management."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from mira.constants import (
    CACHE_DIR_NAME,
    CONFIG_FILE_NAME,
    DATABASE_DIR_NAME,
    BACKUPS_DIR_NAME,
    DEFAULT_CONFIG,
)
from mira.exceptions import ConfigError, ValidationError
from mira.utils.filesystem import atomic_write_json, read_json
from mira.utils.platform import get_user_config_dir, get_user_data_dir, ensure_dir
from mira.utils.validation import validate_countries_config


class Config:
    """Load, validate and persist Mira configuration."""

    def __init__(self, config_dir: Path | None = None, data_dir: Path | None = None):
        self.config_dir = config_dir or get_user_config_dir()
        self.data_dir = data_dir or get_user_data_dir()
        self.config_path = self.config_dir / CONFIG_FILE_NAME
        self.database_dir = self.data_dir / DATABASE_DIR_NAME
        self.cache_dir = self.data_dir / CACHE_DIR_NAME
        self.backups_dir = self.data_dir / BACKUPS_DIR_NAME
        self._data: dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)

    def ensure_dirs(self) -> None:
        ensure_dir(self.config_dir)
        ensure_dir(self.database_dir)
        ensure_dir(self.cache_dir)
        ensure_dir(self.backups_dir)

    def load(self) -> dict[str, Any]:
        self.ensure_dirs()
        if self.config_path.exists():
            try:
                data = read_json(self.config_path)
                if not isinstance(data, dict):
                    raise ConfigError("config.json is not a JSON object")
                # merge with defaults
                merged = copy.deepcopy(DEFAULT_CONFIG)
                merged.update(data)
                self._data = merged
            except Exception as e:
                raise ConfigError(f"Failed to load config: {e}") from e
        else:
            self._data = copy.deepcopy(DEFAULT_CONFIG)
            self.save()
        return self._data

    def save(self) -> None:
        self.ensure_dirs()
        try:
            atomic_write_json(self.config_path, self._data)
        except Exception as e:
            raise ConfigError(f"Failed to save config: {e}") from e

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if key == "countries":
            value = validate_countries_config(value)
        elif key in ("timeout", "read_timeout", "health_cache_ttl"):
            try:
                value = float(value)
                if value <= 0:
                    raise ValueError("must be positive")
            except (TypeError, ValueError) as e:
                raise ValidationError(f"Invalid value for {key}: {e}") from e
        elif key == "max_workers":
            try:
                value = int(value)
                if value < 1 or value > 64:
                    raise ValueError("must be 1-64")
            except (TypeError, ValueError) as e:
                raise ValidationError(f"Invalid value for {key}: {e}") from e
        elif key == "strategy":
            if value not in ("balanced", "fastest", "reliability"):
                raise ValidationError("strategy must be one of: balanced, fastest, reliability")
        elif key in ("path_offer_declined", "path_configured"):
            if isinstance(value, str):
                value = value.strip().lower() in ("1", "true", "yes", "on")
            else:
                value = bool(value)
        self._data[key] = value
        self.save()

    def countries(self) -> list[str]:
        return list(self._data.get("countries", ["*"]))

    def is_country_allowed(self, country: str) -> bool:
        countries = self.countries()
        if "*" in countries:
            return True
        return country.lower() in countries