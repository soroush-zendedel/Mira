"""Package-manager runs through ranked mirrors without persistent config."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mira.core.cache import HealthCache
from mira.core.checker import MirrorChecker
from mira.core.registry import MirrorRegistry
from mira.core.selector import MirrorSelector
from mira.exceptions import MiraError, NoHealthyMirrorError
from mira.providers.debian import DebianProvider
from mira.providers.docker import DockerProvider
from mira.providers.npm import NpmProvider
from mira.providers.pypi import PyPIProvider
from mira.services.backup import BackupService


def _select_best(cfg, registry: MirrorRegistry, provider_name: str, term) -> dict[str, Any]:
    if not registry.exists():
        raise MiraError("Mirror database missing. Run 'mira update' first.", code=1)
    backup = BackupService(cfg.backups_dir)
    providers = {
        "pypi": PyPIProvider(registry, backup),
        "npm": NpmProvider(registry, backup),
        "debian": DebianProvider(registry, backup),
        "docker": DockerProvider(registry, backup),
    }
    prov = providers[provider_name]
    countries = cfg.countries()
    mirrors = prov.list_mirrors(countries=countries)
    if not mirrors:
        raise NoHealthyMirrorError("No mirrors available.")
    cache = HealthCache(cfg.cache_dir, ttl=cfg.get("health_cache_ttl", 900))
    checker = MirrorChecker(cache=cache, max_workers=int(cfg.get("max_workers", 8)), term=term)
    if term and not getattr(term, "quiet", False):
        term.info(f"Selecting best {provider_name} mirror for this command only...")
    results = checker.check_many(mirrors, prov.check_mirror, refresh=True)
    selector = MirrorSelector(strategy=cfg.get("strategy", "balanced"))
    best = selector.select(results)
    m = best["mirror"]
    if term and not getattr(term, "quiet", False):
        term.success(
            f"Using {m.get('name')} ({m.get('id')}) "
            f"score={best.get('score')} latency={best.get('latency_ms')}ms "
            f"[ephemeral - no permanent config change]"
        )
    return m


def _rank_mirrors(cfg, registry: MirrorRegistry, provider_name: str, term) -> list[dict[str, Any]]:
    """Return healthy mirrors best-first (full rank list)."""
    if not registry.exists():
        raise MiraError("Mirror database missing. Run 'mira update' first.", code=1)
    backup = BackupService(cfg.backups_dir)
    providers = {
        "pypi": PyPIProvider(registry, backup),
        "npm": NpmProvider(registry, backup),
        "debian": DebianProvider(registry, backup),
        "docker": DockerProvider(registry, backup),
    }
    prov = providers[provider_name]
    countries = cfg.countries()
    mirrors = prov.list_mirrors(countries=countries)
    if not mirrors:
        raise NoHealthyMirrorError("No mirrors available.")
    cache = HealthCache(cfg.cache_dir, ttl=cfg.get("health_cache_ttl", 900))
    checker = MirrorChecker(cache=cache, max_workers=int(cfg.get("max_workers", 8)), term=term)
    if term and not getattr(term, "quiet", False):
        term.info(f"Selecting best {provider_name} mirror for this command only...")
    results = checker.check_many(mirrors, prov.check_mirror, refresh=True)
    selector = MirrorSelector(strategy=cfg.get("strategy", "balanced"))
    ranked = [r for r in selector.rank(results) if r.get("score", 0) > 0]
    if not ranked:
        raise NoHealthyMirrorError("No healthy mirror found.")
    return ranked


def _run_with_mirror_retry(cfg, registry: MirrorRegistry, provider_name: str, term, attempt) -> int:
    """Cycle through ranked mirrors until the package command succeeds or is cancelled."""
    cycle = 0
    while True:
        cycle += 1
        try:
            ranked = _rank_mirrors(cfg, registry, provider_name, term)
        except KeyboardInterrupt:
            if term:
                term.warning("Mirror retry cancelled by user.")
            return 130
        except NoHealthyMirrorError as exc:
            if term:
                term.warning(f"No healthy {provider_name} mirror right now ({exc}); retrying in 3 seconds. Press Ctrl+C to cancel.")
            try:
                time.sleep(3)
            except KeyboardInterrupt:
                if term:
                    term.warning("Mirror retry cancelled by user.")
                return 130
            continue

        if term and cycle > 1:
            term.info(f"Retrying {provider_name} mirror selection (cycle {cycle}). Press Ctrl+C to cancel.")
        for idx, candidate in enumerate(ranked, 1):
            code = attempt(candidate, idx, len(ranked))
            if code == 0:
                return 0
            if code == 130:
                if term:
                    term.warning("Mirror retry cancelled by user.")
                return code
        if term:
            term.warning(f"All {provider_name} mirrors failed this cycle; checking them again in 3 seconds. Press Ctrl+C to cancel.")
        try:
            time.sleep(3)
        except KeyboardInterrupt:
            if term:
                term.warning("Mirror retry cancelled by user.")
            return 130


def _strip_double_dash(args: list[str]) -> list[str]:
    if args and args[0] == "--":
        return args[1:]
    return args


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> int:
    try:
        p = subprocess.run(cmd, env=env, check=False)
        return int(p.returncode)
    except FileNotFoundError:
        print(f"Command not found: {cmd[0]}", file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        return 130



def _inject_pip_index_args(user_args: list[str], url: str, host: str) -> list[str]:
    """
    Build pip args with --index-url AFTER the subcommand.
    Correct:  pip install --index-url URL django
    Wrong:    pip --index-url URL install django  (breaks some pip/wrappers)
    """
    args = list(user_args)
    joined = " ".join(args)
    inject: list[str] = []
    if "--index-url" not in joined and "-i" not in args:
        inject.extend(["--index-url", url])
    if host and "--trusted-host" not in joined:
        inject.extend(["--trusted-host", host])
    if not inject:
        return args

    # Insert after first non-option token (the subcommand: install, download, ...)
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 1
    if i < len(args):
        i += 1  # after subcommand
    return args[:i] + inject + args[i:]


def run_pip(cfg, registry: MirrorRegistry, user_args: list[str], term) -> int:
    """mira pip install django  ->  pip with --index-url from best working mirror."""
    user_args = _strip_double_dash(list(user_args))
    if not user_args:
        print("Usage: mira pip <pip args...>", file=sys.stderr)
        return 2

    if any(
        arg == "--no-index"
        or arg in ("--index-url", "-i")
        or arg.startswith("--index-url=")
        or arg.startswith("-ihttps://")
        for arg in user_args
    ):
        return _run([sys.executable, "-m", "pip", *user_args])
    verb = next((arg.lower() for arg in user_args if not arg.startswith("-")), "")
    if verb not in {"install", "download", "wheel", "index"}:
        return _run([sys.executable, "-m", "pip", *user_args])

    def attempt(cand: dict[str, Any], idx: int, total: int) -> int:
        m = cand["mirror"]
        url = m["url"]
        host = urlparse(url).hostname or ""
        if term and not getattr(term, "quiet", False):
            term.info(
                f"[{idx}/{total}] Trying {m.get('name')} ({m.get('id')}) "
                f"score={cand.get('score')} url={url}"
            )

        pip_args = _inject_pip_index_args(user_args, url, host)
        cmd = [sys.executable, "-m", "pip", *pip_args]
        if term and getattr(term, "verbose", False):
            term.info(" ".join(cmd))

        code = _run(cmd)
        if code == 0 and term and not getattr(term, "quiet", False):
            term.success(f"Done using {m.get('name')}")
        if term:
            if code:
                term.warning(f"pip exited {code} with {m.get('id')}; trying the next mirror")
        return code

    return _run_with_mirror_retry(cfg, registry, "pypi", term, attempt)


def _inject_npm_registry_args(user_args: list[str], url: str) -> list[str]:
    """Pass the chosen npm registry to this invocation without editing npmrc."""
    args = list(user_args)
    if any(a == "--registry" or a.startswith("--registry=") for a in args):
        return args
    return ["--registry", url, *args]


def run_npm(cfg, registry: MirrorRegistry, user_args: list[str], term) -> int:
    """Run npm with a selected mirror for this command only."""
    user_args = _strip_double_dash(list(user_args))
    if not user_args:
        print("Usage: mira npm <npm args...>", file=sys.stderr)
        return 2

    # Help and version do not contact a registry and should work without a database.
    if any(arg in ("--help", "-h", "--version") for arg in user_args):
        npm = shutil.which("npm") or "npm"
        return _run([npm, *user_args])

    npm = shutil.which("npm") or "npm"
    if any(a == "--registry" or a.startswith("--registry=") for a in user_args):
        return _run([npm, *user_args])

    command_verbs = {
        "install", "i", "ci", "add", "update", "up", "uninstall", "remove", "rm",
        "view", "info", "show", "v", "s", "ping", "search", "outdated", "audit",
        "pack", "exec", "x", "publish", "login", "logout", "whoami", "config",
        "run", "test", "start", "stop", "restart", "list", "ls", "ll",
    }
    verb = next((arg.lower() for arg in user_args if arg.lower() in command_verbs), "")
    mirror_verbs = {
        "view", "info", "show", "v", "s", "ping", "search", "outdated", "audit",
        "install", "i", "ci", "add", "update", "up", "pack", "exec", "x",
    }
    if verb not in mirror_verbs:
        return _run([npm, *user_args])
    # npm package operations are idempotent enough to retry after a registry
    # failure; publish and commands that execute arbitrary scripts are excluded.
    retryable_verbs = {
        "view", "info", "show", "v", "s", "ping", "search", "outdated",
        "install", "i", "ci", "add", "update", "up", "pack",
    }
    if verb in retryable_verbs:
        def attempt(candidate: dict[str, Any], idx: int, total: int) -> int:
            mirror = candidate["mirror"]
            args = _inject_npm_registry_args(user_args, mirror["url"])
            if term and not getattr(term, "quiet", False):
                term.info(f"[{idx}/{total}] Trying npm registry {mirror['url']}")
            cmd = [npm, *args]
            if term and getattr(term, "verbose", False):
                term.info(" ".join(cmd))
            code = _run(cmd)
            if code and term:
                term.warning(f"npm exited {code} with {mirror.get('id')}; trying the next healthy mirror")
            return code

        return _run_with_mirror_retry(cfg, registry, "npm", term, attempt)

    mirror = _select_best(cfg, registry, "npm", term)
    args = _inject_npm_registry_args(user_args, mirror["url"])
    if term and getattr(term, "verbose", False):
        term.info(" ".join([npm, *args]))
    return _run([npm, *args])



def run_apt(cfg, registry: MirrorRegistry, user_args: list[str], term) -> int:
    """
    mira apt install nginx
    Uses a temporary sources.list pointing at the best mirror; does not touch system apt config.
    """
    user_args = _strip_double_dash(list(user_args))
    if not user_args:
        print("Usage: mira apt <apt-get args...>", file=sys.stderr)
        return 2

    prov = DebianProvider(registry)
    codename = prov._detect_codename()
    components = " ".join(prov._components())
    architecture = prov._detect_arch()
    keyring = prov._archive_keyring()
    if not prov._archive_keyring_available():
        raise MiraError(f"Required APT archive keyring is missing: {keyring}", code=1)
    apt_get = shutil.which("apt-get") or "apt-get"
    # Prefer running apt-get; prepend sudo when not root.
    prefix: list[str] = []
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        sudo = shutil.which("sudo")
        if sudo:
            prefix = [sudo]
        elif term:
            term.warning("Not root and sudo not found; apt may fail.")

    verb = user_args[0].lower()
    needs_update = verb in {
        "update", "install", "reinstall", "upgrade", "dist-upgrade",
        "full-upgrade", "build-dep", "download", "source",
    }

    if not needs_update:
        return _run(prefix + [apt_get, *user_args])

    def attempt(candidate: dict[str, Any], idx: int, total: int) -> int:
        mirror = candidate["mirror"]
        url = mirror["url"].rstrip("/")
        line = f"deb [arch={architecture} signed-by={keyring}] {url} {codename} {components}\n"
        with tempfile.TemporaryDirectory(prefix="mira-apt-") as td:
            src = Path(td) / "sources.list"
            src.write_text(line, encoding="utf-8")
            parts = Path(td) / "parts"
            parts.mkdir()
            base_opts = [
                "-o", f"Dir::Etc::sourcelist={src}",
                "-o", f"Dir::Etc::sourceparts={parts}",
                "-o", "APT::Get::List-Cleanup=0",
            ]

            if needs_update:
                upd = prefix + [apt_get, *base_opts, "update", "-qq"]
                if term and not getattr(term, "quiet", False):
                    term.info(f"[{idx}/{total}] Updating indexes from {mirror.get('name', url)}")
                if term and getattr(term, "verbose", False):
                    term.info(" ".join(upd))
                update_code = _run(upd)
                if update_code != 0:
                    if term:
                        term.warning(f"APT update failed with {mirror.get('id')}; trying the next compatible mirror")
                    return update_code
                if verb == "update":
                    return 0

            cmd = prefix + [apt_get, *base_opts, *user_args]
            if term and getattr(term, "verbose", False):
                term.info(" ".join(cmd))
            code = _run(cmd)
            if code and term:
                term.warning(f"APT command failed with {mirror.get('id')}; trying the next compatible mirror")
            return code

    return _run_with_mirror_retry(cfg, registry, "debian", term, attempt)


def _mirror_host(url: str) -> str:
    p = urlparse(url if "://" in url else "https://" + url)
    return p.hostname or url.replace("https://", "").replace("http://", "").split("/")[0]


def _rewrite_docker_image(image: str, mirror_host: str) -> str:
    """
    Map Docker Hub image refs onto a registry mirror host.
    nginx          -> host/library/nginx
    library/nginx  -> host/library/nginx
    user/repo      -> host/user/repo
    ghcr.io/x/y    -> left unchanged (not Docker Hub)
    host/foo       -> left unchanged if host looks like a registry
    """
    if not image or image.startswith("-"):
        return image
    # strip digest / keep tag
    # known non-hub registries
    known = (
        "ghcr.io/", "gcr.io/", "quay.io/", "mcr.microsoft.com/",
        "public.ecr.aws/", "registry.gitlab.com/",
    )
    if image.startswith(known):
        return image
    if image.startswith(mirror_host + "/"):
        return image
    # registry-like first component (has . or :)
    if "/" in image:
        first = image.split("/")[0]
        if "." in first or ":" in first:
            # already a registry host
            return image
        return f"{mirror_host}/{image}"
    # official short name
    return f"{mirror_host}/library/{image}"


def _rewrite_docker_args(args: list[str], mirror_host: str) -> list[str]:
    """Rewrite image references for pull/run/create/build."""
    if not args:
        return args
    out = list(args)
    cmd0 = out[0]

    def rewrite_at(idx: int) -> None:
        if 0 <= idx < len(out) and not out[idx].startswith("-"):
            out[idx] = _rewrite_docker_image(out[idx], mirror_host)

    if cmd0 == "pull":
        # docker pull [OPTIONS] NAME[:TAG|@DIGEST]
        i = 1
        while i < len(out) and out[i].startswith("-"):
            # options that take a value
            if out[i] in {"-a", "--all-tags", "--disable-content-trust", "--quiet", "-q", "--platform"}:
                if out[i] == "--platform" and i + 1 < len(out):
                    i += 2
                    continue
            if "=" not in out[i] and out[i] in {"--platform"}:
                i += 2
                continue
            i += 1
        rewrite_at(i)
    elif cmd0 in {"run", "create"}:
        # image is first non-option after command
        i = 1
        while i < len(out):
            a = out[i]
            if a == "--":
                i += 1
                break
            if a.startswith("-"):
                # boolean flags vs key value — heuristic
                if a in {
                    "-t", "--tty", "-i", "--interactive", "-d", "--detach",
                    "--rm", "--read-only", "--privileged", "-P", "--publish-all",
                    "--init", "--sig-proxy",
                } or a.startswith("-") and "=" in a:
                    i += 1
                    continue
                # option with separate value
                if a in {
                    "-e", "--env", "-p", "--publish", "-v", "--volume",
                    "-w", "--workdir", "-u", "--user", "--name", "--network",
                    "--platform", "--entrypoint", "--hostname", "-h",
                    "--memory", "-m", "--cpus", "--label", "-l",
                }:
                    i += 2
                    continue
                i += 1
                continue
            break
        rewrite_at(i)
    # leave build / other commands unchanged (FROM rewrite would need Dockerfile parsing)
    return out


def run_docker(cfg, registry: MirrorRegistry, user_args: list[str], term) -> int:
    """mira docker pull nginx  ->  docker pull <mirror>/library/nginx"""
    user_args = _strip_double_dash(list(user_args))
    if not user_args:
        print("Usage: mira docker <docker args...>", file=sys.stderr)
        return 2

    docker = shutil.which("docker") or "docker"
    if user_args[0].lower() == "pull":
        # Keep cycling because registry health probes cannot guarantee that a
        # particular image is present on every mirror.
        def attempt(candidate: dict[str, Any], idx: int, total: int) -> int:
            mirror = candidate["mirror"]
            host = _mirror_host(mirror["url"])
            rewritten = _rewrite_docker_args(user_args, host)
            cmd = [docker, *rewritten]
            if term and not getattr(term, "quiet", False):
                term.info(f"[{idx}/{total}] Pulling through {mirror.get('name', host)}")
            if term and getattr(term, "verbose", False):
                term.info("Rewritten command: " + " ".join(cmd))
            code = _run(cmd)
            if code and term:
                term.warning(f"Docker pull failed with {mirror.get('id')}; trying the next healthy mirror")
            return code

        return _run_with_mirror_retry(cfg, registry, "docker", term, attempt)

    # Registry selection is irrelevant for local inspection and commands that
    # do not fetch a Docker Hub image. Preserve Docker's own semantics directly.
    if user_args[0].lower() not in {"run", "create"}:
        return _run([docker, *user_args])

    mirror = _select_best(cfg, registry, "docker", term)
    host = _mirror_host(mirror["url"])
    rewritten = _rewrite_docker_args(user_args, host)
    cmd = [docker, *rewritten]
    if term and not getattr(term, "quiet", False) and rewritten != user_args:
        term.info("Rewritten command: " + " ".join(cmd))
    return _run(cmd)
