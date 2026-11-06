"""Mirror selection based on scores."""

from __future__ import annotations

from typing import Any

from mira.core.scoring import score_mirror
from mira.exceptions import NoHealthyMirrorError


class MirrorSelector:
    """Select the best healthy mirror from check results."""

    def __init__(self, strategy: str = "balanced"):
        self.strategy = strategy

    def select(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Return the best result dict (enriched with 'score').
        Raises NoHealthyMirrorError if none are healthy.
        """
        scored: list[dict[str, Any]] = []
        for r in results:
            s = score_mirror(r, strategy=self.strategy)
            entry = dict(r)
            entry["score"] = s
            if s > 0:
                scored.append(entry)

        if not scored:
            raise NoHealthyMirrorError()

        scored.sort(key=lambda x: (-x["score"], x.get("latency_ms") or 99999))
        best = scored[0]
        best["reason"] = (
            f"score={best['score']}, latency={best.get('latency_ms')}ms, "
            f"strategy={self.strategy}"
        )
        return best

    def rank(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ranked = []
        for r in results:
            s = score_mirror(r, strategy=self.strategy)
            entry = dict(r)
            entry["score"] = s
            ranked.append(entry)
        ranked.sort(key=lambda x: (-x["score"], x.get("latency_ms") or 99999))
        return ranked