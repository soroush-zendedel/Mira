"""Debian/Ubuntu mirror compatibility tests without network access."""

from __future__ import annotations

import sys
import tempfile
import unittest
import os
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mira.providers.debian import DebianProvider
from mira.exceptions import ProviderError
from mira.services.backup import BackupService


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


class DebianSourceManagementTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name) / "apt"
        self.main = root / "sources.list"
        self.parts = root / "sources.list.d"
        self.parts.mkdir(parents=True)
        self.mira = self.parts / "mira.sources"
        self.old_sources = self.parts / "debian.sources"
        self.old_list = self.parts / "third-party.list"
        self.main.write_text("deb https://old.example/debian trixie main\n", encoding="utf-8")
        self.old_sources.write_text(
            "Types: deb\nURIs: https://deb.debian.org/debian\nSuites: trixie\n"
            "Components: main\nSigned-By: /usr/share/keyrings/debian-archive-keyring.gpg\n",
            encoding="utf-8",
        )
        self.old_list.write_text("deb [signed-by=/etc/apt/keyrings/vendor.gpg] https://vendor.example stable main\n", encoding="utf-8")
        self.provider = DebianProvider(None, BackupService(Path(self.temp.name) / "backups"))
        self.patches = [
            mock.patch.object(self.provider, "_detect_codename", return_value="trixie"),
            mock.patch.object(self.provider, "_components", return_value=["main", "contrib"]),
            mock.patch.object(self.provider, "_detect_arch", return_value="amd64"),
            mock.patch.object(self.provider, "_distribution_family", return_value="debian"),
            mock.patch.object(self.provider, "_archive_keyring", return_value="/usr/share/keyrings/debian-archive-keyring.gpg"),
            mock.patch.object(self.provider, "_archive_keyring_available", return_value=True),
            mock.patch("mira.providers.debian.is_linux", return_value=True),
            mock.patch.object(DebianProvider, "APT_MAIN_SOURCES", self.main),
            mock.patch.object(DebianProvider, "APT_SOURCE_PARTS", self.parts),
            mock.patch.object(DebianProvider, "MIRA_SOURCES", self.mira),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_set_disables_all_active_formats_and_reset_restores_exact_files(self):
        originals = {path: path.read_bytes() for path in (self.main, self.old_sources, self.old_list)}
        result = self.provider.apply({"id": "mirror", "url": "https://mirror.example/debian"})
        self.assertEqual(len(result["disabled_sources"]), 3)
        for path in (self.main, self.old_sources, self.old_list):
            self.assertFalse(path.exists())
            self.assertTrue(path.with_name(path.name + ".mira-disabled").exists())
        content = self.mira.read_text(encoding="utf-8")
        self.assertIn("Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg", content)
        self.assertEqual(self.provider.reset()["status"], "removed")
        for path, data in originals.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertFalse(self.mira.exists())

    def test_set_dry_run_does_not_disable_sources(self):
        result = self.provider.apply({"id": "mirror", "url": "https://mirror.example/debian"}, dry_run=True)
        self.assertEqual(len(result["disabled_sources"]), 3)
        self.assertTrue(self.main.exists())
        self.assertTrue(self.old_sources.exists())
        self.assertTrue(self.old_list.exists())
        self.assertFalse(self.mira.exists())

    def test_set_refuses_missing_archive_keyring(self):
        with mock.patch.object(self.provider, "_archive_keyring_available", return_value=False):
            with self.assertRaisesRegex(ProviderError, "keyring is missing"):
                self.provider.apply({"id": "mirror", "url": "https://mirror.example/debian"})
        self.assertTrue(self.main.exists())
        self.assertFalse(self.mira.exists())

    def test_reset_refuses_to_overwrite_new_active_source(self):
        self.provider.apply({"id": "mirror", "url": "https://mirror.example/debian"})
        self.main.write_text("deb https://new.example/debian trixie main\n", encoding="utf-8")
        with self.assertRaisesRegex(ProviderError, "already occupied"):
            self.provider.reset()
        self.assertTrue(self.mira.exists())
        self.assertTrue(self.main.with_name(self.main.name + ".mira-disabled").exists())

    def test_reset_rolls_back_if_restoring_a_source_fails(self):
        self.provider.apply({"id": "mirror", "url": "https://mirror.example/debian"})
        real_replace = os.replace
        calls = 0

        def fail_second_restore(source, target):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise PermissionError("simulated restore failure")
            return real_replace(source, target)

        with mock.patch("mira.providers.debian.os.replace", side_effect=fail_second_restore):
            with self.assertRaisesRegex(ProviderError, "Permission denied restoring"):
                self.provider.reset()
        self.assertTrue(self.mira.exists())
        self.assertFalse(self.main.exists())
        self.assertTrue(self.main.with_name(self.main.name + ".mira-disabled").exists())


if __name__ == "__main__":
    unittest.main()
