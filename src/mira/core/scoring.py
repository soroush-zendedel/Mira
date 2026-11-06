"""Mirror scoring engine."""

from __future__ import annotations

from typing import Any

from mira.constants import MAX_LATENCY_MS, SCORE_WEIGHTS


def score_mirror(
    result: dict[str, Any],
    *,
    weights: dict[str, float] | None = None,
    strategy: str = "balanced",
) -> float:
    """
    Compute a 0-100 score for a health-check result.
    result keys expected:
      available: bool
      valid: bool
      latency_ms: float | None
      stability: float  (0-1, historical)
      priority: int/float (higher is better, typically 0-100)
    """
    w = dict(SCORE_WEIGHTS)
    if weights:
        w.update(weights)

    if strategy == "fastest":
        w = {"availability": 0.25, "validity": 0.25, "latency": 0.40, "stability": 0.05, "priority": 0.05}
    elif strategy == "reliability":
        w = {"availability": 0.30, "validity": 0.30, "latency": 0.10, "stability": 0.25, "priority": 0.05}

    if not result.get("available") or not result.get("valid"):
        return 0.0

    # availability & validity already required
    avail_score = 100.0
    valid_score = 100.0

    latency = result.get("latency_ms")
    if latency is None or latency < 0:
        lat_score = 0.0
    else:
        # linear decay from 0 ms = 100 to MAX_LATENCY_MS = 0
        lat_score = max(0.0, 100.0 * (1.0 - min(latency, MAX_LATENCY_MS) / MAX_LATENCY_MS))

    stability = float(result.get("stability", 0.5))
    stab_score = max(0.0, min(100.0, stability * 100.0))

    priority = float(result.get("priority", 50))
    prio_score = max(0.0, min(100.0, priority))

    total = (
        w["availability"] * avail_score
        + w["validity"] * valid_score
        + w["latency"] * lat_score
        + w["stability"] * stab_score
        + w["priority"] * prio_score
    )
    return round(total, 2)