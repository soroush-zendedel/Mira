"""Validation helpers."""

from __future__ import annotations

import re
from typing import Any

from mira.exceptions import ValidationError

COUNTRY_RE = re.compile(r"^[a-z]{2}$")
MIRROR_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


def validate_manifest(data: Any) -> dict:
    if not isinstance(data, dict):
        raise ValidationError("Manifest must be a JSON object")
    if data.get("schema_version") != 1:
        raise ValidationError(f"Unsupported manifest schema_version: {data.get('schema_version')}")
    if "database_version" not in data:
        raise ValidationError("Manifest missing database_version")
    if "countries" not in data or not isinstance(data["countries"], list):
        raise ValidationError("Manifest missing or invalid countries list")
    if "providers" not in data or not isinstance(data["providers"], list):
        raise ValidationError("Manifest missing or invalid providers list")
    for c in data["countries"]:
        if not isinstance(c, str) or not COUNTRY_RE.match(c):
            raise ValidationError(f"Invalid country code in manifest: {c!r}")
    return data


def validate_mirrors_file(data: Any, expected_country: str | None = None, expected_provider: str | None = None) -> dict:
    if not isinstance(data, dict):
        raise ValidationError("Mirrors file must be a JSON object")
    if data.get("schema_version") != 1:
        raise ValidationError(f"Unsupported mirrors schema_version: {data.get('schema_version')}")
    if expected_country and data.get("country") != expected_country:
        raise ValidationError(f"Country mismatch: expected {expected_country}, got {data.get('country')}")
    if expected_provider and data.get("provider") != expected_provider:
        raise ValidationError(f"Provider mismatch: expected {expected_provider}, got {data.get('provider')}")
    mirrors = data.get("mirrors")
    if not isinstance(mirrors, list):
        raise ValidationError("mirrors must be a list")
    ids = set()
    for i, m in enumerate(mirrors):
        if not isinstance(m, dict):
            raise ValidationError(f"Mirror entry {i} is not an object")
        mid = m.get("id")
        if not mid or not isinstance(mid, str) or not MIRROR_ID_RE.match(mid):
            raise ValidationError(f"Invalid or missing mirror id at index {i}")
        if mid in ids:
            raise ValidationError(f"Duplicate mirror id: {mid}")
        ids.add(mid)
        if "url" not in m or not isinstance(m["url"], str):
            raise ValidationError(f"Mirror {mid} missing url")
        if not m["url"].startswith("https://"):
            raise ValidationError(f"Mirror {mid} url must use https://")
        if "name" not in m:
            m["name"] = mid
        if "enabled" not in m:
            m["enabled"] = True
        if "priority" not in m:
            m["priority"] = 50
    return data


def validate_countries_config(value: Any) -> list[str]:
    if value == "*" or value == ["*"]:
        return ["*"]
    if isinstance(value, str):
        parts = [p.strip().lower() for p in value.split(",") if p.strip()]
    elif isinstance(value, list):
        parts = [str(p).strip().lower() for p in value if str(p).strip()]
    else:
        raise ValidationError("countries must be '*' or a list/comma-separated country codes")
    for p in parts:
        if p != "*" and not COUNTRY_RE.match(p):
            raise ValidationError(f"Invalid country code: {p}")
    return parts if parts else ["*"]