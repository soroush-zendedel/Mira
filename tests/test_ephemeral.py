"""Tests for ephemeral mirror-backed package commands."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from mira.services.ephemeral import (
    _inject_npm_registry_args,
    _rewrite_docker_image,
    _rewrite_docker_args,
    _strip_double_dash,
    run_apt,
    run_docker,
    run_npm,
    _run_with_mirror_retry,
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
        candidates = [{"mirror": {"url": "https://mirror.example/", "id": "m1"}}]
        with mock.patch("mira.services.ephemeral._rank_mirrors", return_value=candidates) as select, \
             mock.patch("mira.services.ephemeral.shutil.which", return_value="npm"), \
             mock.patch("mira.services.ephemeral._run", return_value=0) as run:
            code = run_npm(object(), object(), ["view", "express", "version"], None)
        self.assertEqual(code, 0)
        select.assert_called_once()
        run.assert_called_once_with(["npm", "--registry", "https://mirror.example/", "view", "express", "version"])

    def test_read_only_command_retries_next_registry(self):
        candidates = [
            {"mirror": {"id": "first", "url": "https://one.example/"}},
            {"mirror": {"id": "second", "url": "https://two.example/"}},
        ]
        with mock.patch("mira.services.ephemeral._rank_mirrors", return_value=candidates), \
             mock.patch("mira.services.ephemeral.shutil.which", return_value="npm"), \
             mock.patch("mira.services.ephemeral._run", side_effect=[1, 0]) as run:
            code = run_npm(object(), object(), ["view", "express", "version"], None)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[1].args[0][:3], ["npm", "--registry", "https://two.example/"])

    def test_management_actions_are_not_forwarded(self):
        from mira.cli import _should_run_npm_passthrough
        self.assertFalse(_should_run_npm_passthrough(["npm", "list"]))
        self.assertFalse(_should_run_npm_passthrough(["npm", "set", "--dry-run"]))
        self.assertTrue(_should_run_npm_passthrough(["npm", "view", "express", "version"]))


class PackageCommandFailoverTest(unittest.TestCase):
    def test_retries_full_mirror_cycle_until_command_succeeds(self):
        candidates = [{"mirror": {"id": "one", "url": "https://one.example"}}]
        with mock.patch("mira.services.ephemeral._rank_mirrors", return_value=candidates) as rank, \
             mock.patch("mira.services.ephemeral.time.sleep") as sleep:
            attempt = mock.Mock(side_effect=[1, 0])
            code = _run_with_mirror_retry(object(), object(), "npm", None, attempt)
        self.assertEqual(code, 0)
        self.assertEqual(rank.call_count, 2)
        self.assertEqual(attempt.call_count, 2)
        sleep.assert_called_once_with(3)

    def test_retry_loop_can_be_cancelled(self):
        candidates = [{"mirror": {"id": "one", "url": "https://one.example"}}]
        with mock.patch("mira.services.ephemeral._rank_mirrors", return_value=candidates), \
             mock.patch("mira.services.ephemeral.time.sleep", side_effect=KeyboardInterrupt):
            code = _run_with_mirror_retry(object(), object(), "npm", None, lambda *_: 1)
        self.assertEqual(code, 130)

    def test_apt_update_tries_next_suite_compatible_mirror(self):
        candidates = [
            {"mirror": {"id": "bad", "url": "https://bad.example/ubuntu"}},
            {"mirror": {"id": "good", "url": "https://good.example/ubuntu"}},
        ]
        seen_sources = []

        def fake_apt_run(cmd):
            source_option = next(arg for arg in cmd if arg.startswith("Dir::Etc::sourcelist="))
            seen_sources.append(Path(source_option.split("=", 1)[1]).read_text(encoding="utf-8"))
            return 100 if len(seen_sources) == 1 else 0

        with mock.patch("mira.services.ephemeral._rank_mirrors", return_value=candidates), \
             mock.patch("mira.services.ephemeral.DebianProvider._detect_codename", return_value="resolute"), \
             mock.patch("mira.services.ephemeral.DebianProvider._components", return_value=["main", "universe"]), \
             mock.patch("mira.services.ephemeral.DebianProvider._detect_arch", return_value="amd64"), \
             mock.patch("mira.services.ephemeral.DebianProvider._archive_keyring", return_value="/keys/archive.gpg"), \
             mock.patch("mira.services.ephemeral.DebianProvider._archive_keyring_available", return_value=True), \
             mock.patch("mira.services.ephemeral.shutil.which", return_value="apt-get"), \
             mock.patch("mira.services.ephemeral._run", side_effect=fake_apt_run) as run:
            code = run_apt(object(), object(), ["update"], None)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 2)
        self.assertIn("https://bad.example/ubuntu", seen_sources[0])
        self.assertIn("https://good.example/ubuntu", seen_sources[1])
        self.assertIn("signed-by=/keys/archive.gpg", seen_sources[0])

    def test_docker_pull_retries_next_registry(self):
        candidates = [
            {"mirror": {"id": "bad", "url": "https://bad.example"}},
            {"mirror": {"id": "good", "url": "https://good.example"}},
        ]
        with mock.patch("mira.services.ephemeral._rank_mirrors", return_value=candidates), \
             mock.patch("mira.services.ephemeral.shutil.which", return_value="docker"), \
             mock.patch("mira.services.ephemeral._run", side_effect=[1, 0]) as run:
            code = run_docker(object(), object(), ["pull", "nginx"], None)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 2)
        self.assertIn("bad.example/library/nginx", run.call_args_list[0].args[0])
        self.assertIn("good.example/library/nginx", run.call_args_list[1].args[0])
