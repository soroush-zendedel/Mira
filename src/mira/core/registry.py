"""Local mirror database registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from mira.constants import SCHEMA_VERSION
from mira.exceptions import ValidationError
from mira.utils.filesystem import read_json
from mira.utils.validation import validate_manifest, validate_mirrors_file


class MirrorRegistry:
    """Loads and queries the local mirror database."""

    def __init__(self, database_dir: Path):
        self.database_dir = Path(database_dir)
        self.manifest_path = self.database_dir / "manifest.json"
        self._manifest: dict[str, Any] | None = None

    def exists(self) -> bool:
        return self.manifest_path.exists()

    def load_manifest(self, force: bool = False) -> dict[str, Any]:
        if self._manifest is not None and not force:
            return self._manifest
        if not self.manifest_path.exists():
            raise ValidationError(
                "Mirror database not found. Run 'mira update' first."
            )
        data = read_json(self.manifest_path)
        self._manifest = validate_manifest(data)
        return self._manifest

    def countries(self) -> list[str]:
        return list(self.load_manifest().get("countries", []))

    def providers(self) -> list[str]:
        return list(self.load_manifest().get("providers", []))

    def database_version(self) -> str:
        return str(self.load_manifest().get("database_version", "0.0.0"))

    def iter_mirrors(
        self,
        provider: str | None = None,
        countries: list[str] | None = None,
        enabled_only: bool = True,
    ) -> Iterator[dict[str, Any]]:
        """Yield mirror dicts enriched with country and provider."""
        manifest = self.load_manifest()
        allowed_countries = countries or ["*"]
        all_countries = manifest.get("countries", [])
        if "*" in allowed_countries:
            target_countries = all_countries
        else:
            target_countries = [c for c in all_countries if c in allowed_countries]
            # Worldwide mirrors are valid fallback candidates regardless of the
            # user's country filter (for example, GeoIP-backed Arch endpoints).
            if "ww" in all_countries and "ww" not in target_countries:
                target_countries.append("ww")

        target_providers = [provider] if provider else manifest.get("providers", [])

        for country in target_countries:
            for prov in target_providers:
                path = self.database_dir / country / prov / "mirrors.json"
                if not path.exists():
                    continue
                try:
                    data = read_json(path)
                    data = validate_mirrors_file(data, expected_country=country, expected_provider=prov)
                except Exception:
                    continue
                for m in data.get("mirrors", []):
                    if enabled_only and not m.get("enabled", True):
                        continue
                    entry = dict(m)
                    entry["country"] = country
                    entry["provider"] = prov
                    yield entry

    def list_mirrors(
        self,
        provider: str | None = None,
        countries: list[str] | None = None,
        enabled_only: bool = True,
    ) -> list[dict[str, Any]]:
        return list(self.iter_mirrors(provider=provider, countries=countries, enabled_only=enabled_only))
