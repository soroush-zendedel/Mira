"""Tests for ephemeral mirror-backed package commands."""

from __future__ import annotations

import unittest

from mira.services.ephemeral import _rewrite_docker_image, _rewrite_docker_args, _strip_double_dash


class EphemeralDockerRewriteTest(unittest.TestCase):
    def test_official_short_name(self):
        self.assertEqual(
            _rewrite_docker_image("nginx", "docker.arvancloud.ir"),
            "docker.arvancloud.ir/library/nginx",
        )

    def test_user_repo(self):
        self.assertEqual(
            _rewrite_docker_image("library/python:3.12", "docker.arvancloud.ir"),
            "docker.arvancloud.ir/library/python:3.12",
        )

    def test_leave_ghcr(self):
        self.assertEqual(
            _rewrite_docker_image("ghcr.io/foo/bar", "docker.arvancloud.ir"),
            "ghcr.io/foo/bar",
        )

    def test_pull_args(self):
        out = _rewrite_docker_args(["pull", "nginx"], "m.example")
        self.assertEqual(out, ["pull", "m.example/library/nginx"])

    def test_run_args_with_flags(self):
        out = _rewrite_docker_args(["run", "--rm", "-it", "python:3.12", "python", "-V"], "m.example")
        self.assertEqual(out[0], "run")
        self.assertEqual(out[3], "m.example/library/python:3.12")

    def test_strip_dd(self):
        self.assertEqual(_strip_double_dash(["--", "install", "x"]), ["install", "x"])


class EphemeralCliTest(unittest.TestCase):
    def test_parser_has_pip_apt(self):
        from mira.cli import build_parser
        p = build_parser()
        args = p.parse_args(["pip", "install", "django"])
        self.assertEqual(args.command, "pip")
        self.assertEqual(args.pip_args, ["install", "django"])
        args2 = p.parse_args(["apt", "install", "nginx"])
        self.assertEqual(args2.command, "apt")
        self.assertEqual(args2.apt_args, ["install", "nginx"])
