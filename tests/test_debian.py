"""Debian/Ubuntu mirror compatibility tests without network access."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mira.providers.debian import DebianProvider


class _Registry:
    def list_mirrors(self, **kwargs):
        return [{"id": "regional", "url": "https://regional.example/debian", "priority": 90}]


class DebianProviderCompatibilityTest(unittest.TestCase):
    def test_ubuntu_derivative_uses_base_codename(self):
        provider = DebianProvider(None)
        with mock.patch.object(provider, "_os_release", return_value={"UBUNTU_CODENAME": "jammy"}), \
             mock.patch("mira.providers.debian.subprocess.check_output", return_value="vera\n") as lsb:
            self.assertEqual(provider._detect_codename(), "jammy")
        lsb.assert_not_called()

    def setUp(self):
        self.provider = DebianProvider(_Registry())
        patches = [
            mock.patch.object(self.provider, "_detect_codename", return_value="resolute"),
            mock.patch.object(self.provider, "_components", return_value=["main", "universe"]),
            mock.patch.object(self.provider, "_detect_arch", return_value="amd64"),
            mock.patch.object(self.provider, "_distribution_family", return_value="ubuntu"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def release(codename="resolute", components="main universe", architectures="amd64 arm64"):
        return (
            f"Origin: Ubuntu\nSuite: {codename}\nCodename: {codename}\n"
            f"Architectures: {architectures}\nComponents: {components}\nSHA256:\n"
        ).encode()

    def test_checks_only_exact_release_suite_and_accepts_compatible_metadata(self):
        with mock.patch(
            "mira.providers.debian.fetch_url",
            return_value=(200, {}, self.release(), 8.0),
        ) as fetch:
            result = self.provider.check_mirror({"url": "https://mirror.example/ubuntu"})
        self.assertTrue(result["valid"])
        fetch.assert_called_once_with(
            "https://mirror.example/ubuntu/dists/resolute/InRelease",
            timeout=8.0,
            max_size=512 * 1024,
        )

    def test_rejects_other_release_even_when_repository_is_live(self):
        with mock.patch(
            "mira.providers.debian.fetch_url",
            return_value=(200, {}, self.release(codename="noble"), 8.0),
        ) as fetch:
            result = self.provider.check_mirror({"url": "https://mirror.example/ubuntu"})
        self.assertFalse(result["valid"])
        self.assertIn("does not match 'resolute'", result["error"])
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(all("/dists/resolute/" in call.args[0] for call in fetch.call_args_list))

    def test_rejects_missing_component_or_architecture(self):
        with mock.patch(
            "mira.providers.debian.fetch_url",
            return_value=(200, {}, self.release(components="main", architectures="arm64"), 8.0),
        ):
            result = self.provider.check_mirror({"url": "https://mirror.example/ubuntu"})
        self.assertFalse(result["valid"])
        self.assertIn("Missing components", result["error"])

    def test_adds_distribution_specific_global_fallback(self):
        mirrors = self.provider.list_mirrors(countries=["ir"])
        self.assertEqual(mirrors[-1]["url"], "https://archive.ubuntu.com/ubuntu")
        self.assertEqual(mirrors[-1]["country"], "global")


if __name__ == "__main__":
    unittest.main()
