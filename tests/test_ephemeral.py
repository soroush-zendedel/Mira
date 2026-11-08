"""Tests for ephemeral mirror-backed package commands."""

from __future__ import annotations

import unittest
from unittest import mock

from mira.services.ephemeral import (
    _inject_npm_registry_args,
    _rewrite_docker_image,
    _rewrite_docker_args,
    _strip_double_dash,
    run_npm,
)


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


class PipInjectTest(unittest.TestCase):
    def test_index_after_subcommand(self):
        from mira.services.ephemeral import _inject_pip_index_args
        out = _inject_pip_index_args(["install", "django"], "https://m.example/simple", "m.example")
        self.assertEqual(
            out,
            ["install", "--index-url", "https://m.example/simple", "--trusted-host", "m.example", "django"],
        )

    def test_respect_user_index(self):
        from mira.services.ephemeral import _inject_pip_index_args
        out = _inject_pip_index_args(
            ["install", "--index-url", "https://other/simple", "x"],
            "https://m.example/simple",
            "m.example",
        )
        self.assertEqual(out.count("--index-url"), 1)
        self.assertIn("https://other/simple", out)


class NpmPassthroughTest(unittest.TestCase):
    def test_registry_injected_before_subcommand(self):
        self.assertEqual(
            _inject_npm_registry_args(["view", "express", "version"], "https://mirror.example/"),
            ["--registry", "https://mirror.example/", "view", "express", "version"],
        )

    def test_respect_explicit_registry(self):
        args = ["view", "--registry=https://custom.example/", "express"]
        self.assertEqual(_inject_npm_registry_args(args, "https://mirror.example/"), args)

    def test_run_uses_selected_mirror_and_forwards_exit_code(self):
        with mock.patch("mira.services.ephemeral._select_best", return_value={"url": "https://mirror.example/"}) as select, \
             mock.patch("mira.services.ephemeral.shutil.which", return_value="npm"), \
             mock.patch("mira.services.ephemeral._run", return_value=0) as run:
            code = run_npm(object(), object(), ["view", "express", "version"], None)
        self.assertEqual(code, 0)
        select.assert_called_once()
        run.assert_called_once_with(["npm", "--registry", "https://mirror.example/", "view", "express", "version"])

    def test_management_actions_are_not_forwarded(self):
        from mira.cli import _should_run_npm_passthrough
        self.assertFalse(_should_run_npm_passthrough(["npm", "list"]))
        self.assertFalse(_should_run_npm_passthrough(["npm", "set", "--dry-run"]))
        self.assertTrue(_should_run_npm_passthrough(["npm", "view", "express", "version"]))
