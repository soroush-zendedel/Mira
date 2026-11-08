"""Tests for AppUpgrader: source vs binary asset choice and pacman guard."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mira.core.upgrader import AppUpgrader
from mira.exceptions import UpdateError


class TestAssetSelection(unittest.TestCase):
    def _release(self, assets=None, zipball="https://api.github.com/zipball/v9.9.9"):
        return {
            "tag_name": "v9.9.9",
            "zipball_url": zipball,
            "assets": assets or [],
        }

    def test_source_install_prefers_source_zip(self):
        assets = [
            {
                "name": "mira-linux-x86_64",
                "browser_download_url": "https://example.com/mira-linux-x86_64",
            },
            {
                "name": "mira-9.9.9-source.zip",
                "browser_download_url": "https://example.com/mira-9.9.9-source.zip",
            },
        ]
        up = AppUpgrader(install_root=Path("/tmp/fake-mira-user"))
        up.frozen = False
        with mock.patch.object(up, "_looks_like_binary_install", return_value=False):
            url, kind = up._asset_url_for_platform(self._release(assets))
        self.assertEqual(kind, "source")
        self.assertIn("source.zip", url)

    def test_frozen_prefers_binary(self):
        assets = [
            {
                "name": "mira-linux-x86_64",
                "browser_download_url": "https://example.com/mira-linux-x86_64",
            },
            {
                "name": "mira-9.9.9-source.zip",
                "browser_download_url": "https://example.com/mira-9.9.9-source.zip",
            },
        ]
        up = AppUpgrader(install_root=Path("/tmp/fake-mira-user"))
        up.frozen = True
        with mock.patch("mira.core.upgrader.is_windows", return_value=False):
            url, kind = up._asset_url_for_platform(self._release(assets))
        self.assertEqual(kind, "binary")
        self.assertIn("mira-linux-x86_64", url)

    def test_source_falls_back_to_zipball(self):
        up = AppUpgrader(install_root=Path("/tmp/fake-mira-user"))
        up.frozen = False
        with mock.patch.object(up, "_looks_like_binary_install", return_value=False):
            url, kind = up._asset_url_for_platform(self._release(assets=[]))
        self.assertEqual(kind, "source")
        self.assertIn("zipball", url)


class TestPacmanGuard(unittest.TestCase):
    def test_pacman_managed_refuses_upgrade(self):
        up = AppUpgrader(install_root=Path("/usr/lib/mira"))
        with mock.patch.object(up, "_is_pacman_managed", return_value=True):
            with self.assertRaises(UpdateError) as cm:
                up.upgrade(dry_run=False)
            self.assertIn("pacman", str(cm.exception).lower())

    def test_pacman_managed_dry_run_does_not_raise(self):
        up = AppUpgrader(install_root=Path("/usr/lib/mira"))
        with mock.patch.object(up, "_is_pacman_managed", return_value=True):
            ver = up.upgrade(dry_run=True)
            self.assertIsInstance(ver, str)

    def test_is_pacman_managed_false_without_pacman(self):
        up = AppUpgrader(install_root=Path("/home/user/.local/share/mira"))
        with mock.patch("mira.core.upgrader.shutil.which", return_value=None):
            with mock.patch("mira.core.upgrader.subprocess.run") as run:
                run.side_effect = FileNotFoundError("pacman")
                self.assertFalse(up._is_pacman_managed())


if __name__ == "__main__":
    unittest.main()
