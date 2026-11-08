"""npm provider and CLI tests (no network)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mira.cli import build_parser
from mira.core.registry import MirrorRegistry
from mira.providers.npm import NpmProvider


class NpmProviderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.npmrc = self.root / ".npmrc"
        self.provider = NpmProvider(MirrorRegistry(self.root / "database"))
        self.paths = mock.patch.object(self.provider, "_npmrc_paths", side_effect=lambda scope="user": [self.npmrc])
        self.paths.start()
        self.addCleanup(self.paths.stop)

    def test_apply_preserves_other_npmrc_settings_and_replaces_registry(self):
        self.npmrc.write_text("//registry.npmjs.org/:_authToken=secret\n@acme:registry=https://packages.example/\nregistry=https://registry.npmjs.org/\n", encoding="utf-8")
        mirror = {"id": "test-npm", "url": "https://npm.example/"}
        result = self.provider.apply(mirror)
        text = self.npmrc.read_text(encoding="utf-8")
        self.assertEqual(result["status"], "applied")
        self.assertIn("//registry.npmjs.org/:_authToken=secret", text)
        self.assertIn("@acme:registry=https://packages.example/", text)
        self.assertEqual(text.count("registry="), 2)
        self.assertIn("registry=https://npm.example/", text)

    def test_dry_run_does_not_write(self):
        result = self.provider.apply({"url": "https://npm.example/"}, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertFalse(self.npmrc.exists())

    def test_rejects_non_https_registry(self):
        from mira.exceptions import ProviderError
        with self.assertRaises(ProviderError):
            self.provider.apply({"url": "http://npm.example/"})

    def test_reset_removes_only_default_registry(self):
        self.npmrc.write_text("registry=https://npm.example/\n@acme:registry=https://private.example/\n//private.example/:_authToken=secret\n", encoding="utf-8")
        result = self.provider.reset()
        text = self.npmrc.read_text(encoding="utf-8")
        self.assertEqual(result["status"], "removed registry")
        self.assertNotIn("registry=https://npm.example/", text)
        self.assertIn("@acme:registry=https://private.example/", text)
        self.assertIn("_authToken=secret", text)

    def test_check_requires_npm_package_metadata(self):
        payload = json.dumps({"name": "express", "versions": {"1.0.0": {}}}).encode()
        with mock.patch("mira.providers.npm.fetch_url", return_value=(200, {"content-type": "application/json"}, payload, 12.0)) as fetch:
            result = self.provider.check_mirror({"url": "https://npm.example/"})
        self.assertTrue(result["available"])
        self.assertTrue(result["valid"])
        fetch.assert_called_once_with("https://npm.example/express", timeout=8.0, max_size=1024 * 1024)

    def test_check_rejects_unrelated_json(self):
        with mock.patch("mira.providers.npm.fetch_url", return_value=(200, {}, b'{"ok":true}', 3.0)):
            result = self.provider.check_mirror({"url": "https://npm.example"})
        self.assertTrue(result["available"])
        self.assertFalse(result["valid"])

    def test_cli_exposes_npm_provider_commands(self):
        args = build_parser().parse_args(["npm", "set", "--scope", "project", "--dry-run"])
        self.assertEqual(args.command, "npm")
        self.assertEqual(args.scope, "project")
        self.assertTrue(args.dry_run)
        check = build_parser().parse_args(["check", "npm"])
        self.assertEqual(check.provider, "npm")
        reset = build_parser().parse_args(["npm", "reset", "--scope", "project"])
        self.assertEqual(reset.scope, "project")


if __name__ == "__main__":
    unittest.main()
