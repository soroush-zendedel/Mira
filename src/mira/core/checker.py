"""Concurrent mirror health checker."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from mira.constants import DEFAULT_MAX_WORKERS
from mira.core.cache import HealthCache
from mira.utils.terminal import Terminal


class MirrorChecker:
    """Run provider-specific health checks concurrently with caching."""

    def __init__(
        self,
        cache: HealthCache | None = None,
        max_workers: int = DEFAULT_MAX_WORKERS,
        term: Terminal | None = None,
    ):
        self.cache = cache
        self.max_workers = max_workers
        self.term = term or Terminal()

    def check_one(
        self,
        mirror: dict[str, Any],
        check_fn: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        refresh: bool = False,
    ) -> dict[str, Any]:
        provider = mirror.get("provider", "")
        mid = mirror.get("id", "")
        if self.cache and not refresh:
            cached = self.cache.get(provider, mid)
            if cached is not None:
                out = dict(cached)
                out["from_cache"] = True
                out["mirror"] = mirror
                return out

        try:
            result = check_fn(mirror)
        except Exception as e:
            result = {
                "available": False,
                "valid": False,
                "latency_ms": None,
                "error": str(e),
                "stability": 0.0,
            }
        result.setdefault("available", False)
        result.setdefault("valid", False)
        result.setdefault("latency_ms", None)
        result.setdefault("error", None)
        result.setdefault("stability", 0.5)
        result["priority"] = mirror.get("priority", 50)
        result["mirror"] = mirror
        result["from_cache"] = False

        if self.cache:
            self.cache.set(provider, mid, {
                "available": result["available"],
                "valid": result["valid"],
                "latency_ms": result["latency_ms"],
                "error": result.get("error"),
                "stability": result.get("stability", 0.5),
                "priority": result["priority"],
            })
        return result

    def check_many(
        self,
        mirrors: list[dict[str, Any]],
        check_fn: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        refresh: bool = False,
    ) -> list[dict[str, Any]]:
        if not mirrors:
            return []
        results: list[dict[str, Any]] = []
        workers = min(self.max_workers, len(mirrors))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self.check_one, m, check_fn, refresh=refresh): m
                for m in mirrors
            }
            for fut in as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception as e:
                    m = futures[fut]
                    results.append({
                        "available": False,
                        "valid": False,
                        "latency_ms": None,
                        "error": str(e),
                        "stability": 0.0,
                        "priority": m.get("priority", 50),
                        "mirror": m,
                        "from_cache": False,
                    })
        if self.cache:
            self.cache.save()
        return results