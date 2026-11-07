"""Tests for mira uninstall (uses isolated temp dirs via env + monkeypatch)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mira.services import uninstaller as u


class UninstallTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="mira-uninst-")
        self.config = Path(self.tmp) / "config" / "mira"
        self.data = Path(self.tmp) / "data" / "mira"
        self.bin = Path(self.tmp) / "bin"
        self.install = Path(self.tmp) / "share" / "mira"
        self.config.mkdir(parents=True)
        self.data.mkdir(parents=True)
        self.bin.mkdir(parents=True)
        self.install.mkdir(parents=True)
        (self.config / "config.json").write_text("{}", encoding="utf-8")
        (self.data / "cache").mkdir()
        (self.bin / "mira").write_text("#!/bin/sh\n", encoding="utf-8")
        (self.install / "src").mkdir()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_uninstall_removes_files_and_reports(self) -> None:
        # Point platform helpers at temp dirs
        with mock.patch.object(u, "get_user_config_dir", return_value=self.config), \
             mock.patch.object(u, "get_user_data_dir", return_value=self.data), \
             mock.patch.object(u, "is_windows", return_value=False), \
             mock.patch.object(u, "_install_roots", return_value=[self.install, self.bin]), \
             mock.patch.object(u, "_launcher_candidates", return_value=[self.bin / "mira"]), \
             mock.patch.object(u, "_bin_dirs_for_path_cleanup", return_value=[self.bin]), \
             mock.patch.object(u, "_clean_unix_path", return_value=[f"cleaned profile for {self.bin}"]):
            code = u.uninstall(purge_data=True, assume_yes=True, term=None)
        self.assertEqual(code, 0)
        self.assertFalse((self.bin / "mira").exists())
        self.assertFalse(self.install.exists())
        self.assertFalse(self.config.exists())
        self.assertFalse(self.data.exists())

    def test_uninstall_keep_data(self) -> None:
        with mock.patch.object(u, "get_user_config_dir", return_value=self.config), \
             mock.patch.object(u, "get_user_data_dir", return_value=self.data), \
             mock.patch.object(u, "is_windows", return_value=False), \
             mock.patch.object(u, "_install_roots", return_value=[self.install, self.bin]), \
             mock.patch.object(u, "_launcher_candidates", return_value=[self.bin / "mira"]), \
             mock.patch.object(u, "_bin_dirs_for_path_cleanup", return_value=[self.bin]), \
             mock.patch.object(u, "_clean_unix_path", return_value=[]):
            code = u.uninstall(purge_data=False, assume_yes=True, term=None)
        self.assertEqual(code, 0)
        self.assertFalse((self.bin / "mira").exists())
        self.assertTrue(self.config.exists())
        self.assertTrue(self.data.exists())

    def test_cli_has_uninstall(self) -> None:
        from mira.cli import build_parser
        p = build_parser()
        args = p.parse_args(["uninstall", "--yes"])
        self.assertEqual(args.command, "uninstall")
        self.assertTrue(args.yes)
