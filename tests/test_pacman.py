"""Pacman provider behavior tests (network and host paths are mocked)."""

import tempfile
import unittest
import re
from pathlib import Path
from unittest.mock import Mock, patch

from mira.exceptions import MiraError
from mira.cli import _should_run_pacman_passthrough, build_parser
from mira.providers.pacman import PacmanProvider


class PacmanProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "mirrorlist"
        self.backup = Mock()
        self.provider = PacmanProvider(None, self.backup)
        self.provider.mirrorlist_path = self.path

    @patch("mira.providers.pacman.is_linux", return_value=True)
    def test_apply_prepends_managed_https_block_and_backs_up(self, _linux):
        self.path.write_text("## existing\nServer = https://old.example/$repo/os/$arch\n", encoding="utf-8")
        result = self.provider.apply({"id": "new", "name": "New", "url": "https://new.example/arch"})
        text = self.path.read_text(encoding="utf-8")
        self.assertEqual(result["status"], "configured")
        self.assertLess(text.index("Mira managed mirrors"), text.index("old.example"))
        self.assertIn("Server = https://new.example/arch/$repo/os/$arch", text)
        self.backup.create_backup.assert_called_once()

    @patch("mira.providers.pacman.is_linux", return_value=True)
    def test_reset_removes_only_managed_block(self, _linux):
        original = "# >>> Mira managed mirrors >>>\nServer = https://new/$repo/os/$arch\n# <<< Mira managed mirrors <<<\n# keep me\nServer = https://old/$repo/os/$arch\n"
        self.path.write_text(original, encoding="utf-8")
        result = self.provider.reset()
        self.assertEqual(result["status"], "restored previous mirrorlist entries")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "# keep me\nServer = https://old/$repo/os/$arch\n")

    @patch("mira.providers.pacman.is_linux", return_value=True)
    def test_dry_run_does_not_write(self, _linux):
        result = self.provider.apply({"url": "https://mirror.example/arch"}, dry_run=True)
        self.assertEqual(result["status"], "dry-run")
        self.assertFalse(self.path.exists())
        self.backup.create_backup.assert_not_called()

    @patch("mira.providers.pacman.is_linux", return_value=True)
    def test_rejects_non_https_mirror(self, _linux):
        with self.assertRaises(MiraError):
            self.provider.apply({"url": "http://mirror.example/arch"})

    @patch("mira.providers.pacman.is_linux", return_value=True)
    @patch("mira.providers.pacman.fetch_url", return_value=(200, {}, b"1", 12.5))
    @patch("mira.providers.pacman.time.time", return_value=1)
    def test_health_check_requires_recent_lastsync(self, _now, fetch, _linux):
        result = self.provider.check_mirror({"url": "https://mirror.example/arch"})
        fetch.assert_called_once()
        self.assertTrue(result["available"])
        self.assertTrue(result["valid"])

    @patch("mira.providers.pacman.is_linux", return_value=False)
    def test_configuration_is_linux_only(self, _linux):
        with self.assertRaises(MiraError):
            self.provider.reset()

    def test_cli_management_actions_and_passthrough_boundary(self):
        parser = build_parser()
        self.assertEqual(parser.parse_args(["pacman", "set"]).prov_cmd, "set")
        self.assertEqual(parser.parse_args(["check", "pacman"]).provider, "pacman")
        self.assertFalse(_should_run_pacman_passthrough(["pacman", "list"]))
        self.assertFalse(_should_run_pacman_passthrough(["pacman", "--help"]))
        self.assertTrue(_should_run_pacman_passthrough(["pacman", "-Syu"]))

    def test_ephemeral_sync_redirects_only_the_mirrorlist(self):
        from mira.services import ephemeral

        original_read_text = Path.read_text
        observed = {}
        system_config = "[options]\nSigLevel = Required DatabaseOptional\n\n[core]\nInclude = /etc/pacman.d/mirrorlist\n"

        def read_text(path, *args, **kwargs):
            if str(path) == "/etc/pacman.conf":
                return system_config
            return original_read_text(path, *args, **kwargs)

        def run_command(command, **kwargs):
            observed["config"] = original_read_text(Path(command[2]), encoding="utf-8")
            match = re.search(r"Include = (.+)", observed["config"])
            observed["mirrorlist"] = original_read_text(Path(match.group(1)), encoding="utf-8")
            return 0

        with patch("mira.services.ephemeral.Path.read_text", new=read_text), \
             patch("mira.services.ephemeral.shutil.which", return_value="/usr/bin/pacman"), \
             patch("mira.services.ephemeral._run", side_effect=run_command), \
             patch("mira.services.ephemeral._run_with_mirror_retry", side_effect=lambda cfg, reg, name, term, attempt: attempt({"mirror": {"url": "https://mirror.example/arch", "name": "Example"}}, 1, 1)):
            code = ephemeral.run_pacman(None, None, ["-Syu"], None)
        self.assertEqual(code, 0)
        self.assertIn("SigLevel = Required DatabaseOptional", observed["config"])
        self.assertIn("Server = https://mirror.example/arch/$repo/os/$arch", observed["mirrorlist"])



if __name__ == "__main__":
    unittest.main()
