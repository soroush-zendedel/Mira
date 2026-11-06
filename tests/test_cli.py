"""CLI smoke tests (no network for most)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# ensure src on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mira.cli import main, build_parser


class TestCLI(unittest.TestCase):
    def test_version(self):
        parser = build_parser()
        with self.assertRaises(SystemExit) as cm:
            parser.parse_args(["--version"])
        self.assertEqual(cm.exception.code, 0)

    def test_help(self):
        parser = build_parser()
        with self.assertRaises(SystemExit) as cm:
            parser.parse_args(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_status_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            # isolate config
            with mock.patch.dict(os.environ, {
                "XDG_CONFIG_HOME": tmp,
                "XDG_DATA_HOME": tmp,
                "APPDATA": tmp,
                "LOCALAPPDATA": tmp,
            }):
                code = main(["status"])
                self.assertEqual(code, 0)

    def test_config_show(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {
                "XDG_CONFIG_HOME": tmp,
                "XDG_DATA_HOME": tmp,
                "APPDATA": tmp,
                "LOCALAPPDATA": tmp,
            }):
                code = main(["config", "show"])
                self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()