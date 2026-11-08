"""Registry tests using local mirrors/ fixtures."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mira.core.registry import MirrorRegistry


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.db = ROOT / "mirrors"
        self.reg = MirrorRegistry(self.db)

    def test_manifest(self):
        m = self.reg.load_manifest()
        self.assertEqual(m["schema_version"], 1)
        self.assertIn("pypi", m["providers"])
        self.assertIn("ir", m["countries"])

    def test_list_pypi(self):
        mirrors = self.reg.list_mirrors(provider="pypi")
        self.assertGreater(len(mirrors), 0)
        for m in mirrors:
            self.assertEqual(m["provider"], "pypi")
            self.assertTrue(m["url"].startswith("https://"))

    def test_list_npm_by_country(self):
        mirrors = self.reg.list_mirrors(provider="npm", countries=["ir"])
        self.assertGreaterEqual(len(mirrors), 1)
        self.assertTrue(any(m["id"] == "runflare-npm" for m in mirrors))
        self.assertTrue(all(m["provider"] == "npm" and m["country"] == "ir" for m in mirrors))

    def test_country_filter(self):
        mirrors = self.reg.list_mirrors(provider="pypi", countries=["ir"])
        for m in mirrors:
            self.assertEqual(m["country"], "ir")


if __name__ == "__main__":
    unittest.main()
