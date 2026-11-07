"""Tests for post-apply verification helpers."""

from __future__ import annotations

import unittest
from unittest import mock

from mira.services import verify as v


class VerifyHelpersTest(unittest.TestCase):
    def test_network_failure_patterns(self):
        sample = (
            'WARNING: Retrying (Retry(total=4, connect=None, read=None, redirect=None, status=None)) '
            'after connection broken by \'NameResolutionError("HTTPSConnection(host=\'files.pythonhosted.org\', '
            'port=443): Failed to resolve \'files.pythonhosted.org\' ([Errno 11001] getaddrinfo failed)")\''
        )
        self.assertTrue(v._looks_like_network_failure(sample, 1))
        self.assertTrue(v._looks_like_network_failure("TIMEOUT", 124))
        self.assertFalse(v._looks_like_network_failure("Successfully installed pip-26.0", 0))

    def test_verify_debian_success(self):
        body = b"Origin: Debian\nSuite: stable\nComponents: main\n"
        with mock.patch.object(
            v, "fetch_url", return_value=(200, {"Content-Type": "text/plain"}, body, 12)
        ):
            r = v.verify_debian({"url": "https://deb.example/debian"})
        self.assertTrue(r["ok"])

    def test_verify_docker_401_ok(self):
        with mock.patch.object(
            v,
            "fetch_url",
            return_value=(401, {"Docker-Distribution-Api-Version": "registry/2.0"}, b"", 8),
        ):
            r = v.verify_docker({"url": "https://registry.example"})
        self.assertTrue(r["ok"])

    def test_verify_pypi_index_ok(self):
        with mock.patch.object(v, "_run", return_value=(0, "pip (26.0)\nAvailable versions: 26.0, 25.0")):
            r = v.verify_pypi({"url": "https://pypi.example/simple"})
        self.assertTrue(r["ok"])
        self.assertIn("pip index", r["method"])

    def test_verify_pypi_retries_then_fail(self):
        fail = (
            "WARNING: Retrying (Retry(total=0)) after connection broken by "
            "'NameResolutionError(\"Failed to resolve\")'"
        )
        with mock.patch.object(v, "_run", return_value=(1, fail)):
            r = v.verify_pypi({"url": "https://bad.example/simple"})
        self.assertFalse(r["ok"])
