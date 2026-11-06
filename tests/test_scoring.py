"""Unit tests for scoring (no network)."""

import unittest

from mira.core.scoring import score_mirror


class TestScoring(unittest.TestCase):
    def test_unhealthy_zero(self):
        self.assertEqual(score_mirror({"available": False, "valid": True}), 0.0)
        self.assertEqual(score_mirror({"available": True, "valid": False}), 0.0)

    def test_healthy_high(self):
        r = {
            "available": True,
            "valid": True,
            "latency_ms": 50.0,
            "stability": 0.9,
            "priority": 90,
        }
        s = score_mirror(r)
        self.assertGreater(s, 80.0)

    def test_slow_lower(self):
        fast = score_mirror({
            "available": True, "valid": True,
            "latency_ms": 20.0, "stability": 0.5, "priority": 50,
        })
        slow = score_mirror({
            "available": True, "valid": True,
            "latency_ms": 2000.0, "stability": 0.5, "priority": 50,
        })
        self.assertGreater(fast, slow)

    def test_strategy_fastest(self):
        r = {
            "available": True, "valid": True,
            "latency_ms": 10.0, "stability": 0.1, "priority": 10,
        }
        s = score_mirror(r, strategy="fastest")
        self.assertGreater(s, 50.0)


if __name__ == "__main__":
    unittest.main()