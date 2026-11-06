"""Mira command-line interface (argparse only)."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from mira import __version__
from mira.config import Config
from mira.constants import APP_DESCRIPTION, APP_NAME
from mira.core.cache import HealthCache
from mira.core.checker import MirrorChecker
from mira.core.registry import MirrorRegistry
from mira.core.selector import MirrorSelector
from mira.core.updater import DatabaseUpdater
from mira.core.upgrader import AppUpgrader
from mira.exceptions import MiraError, NoHealthyMirrorError
from mira.providers.debian import DebianProvider
from mira.providers.docker import DockerProvider
from mira.providers.pypi import PyPIProvider
from mira.services.backup import BackupService
from mira.utils.terminal import Terminal
from mira.utils.path_setup import maybe_offer_path_setup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=APP_DESCRIPTION,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--quiet", "-q", action="store_true", help="Minimal output")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors")

    sub = parser.add_subparsers(dest="command", help="Command")

    # status / update / upgrade
    sub.add_parser("status", help="Show Mira status")
    p_upd = sub.add_parser("update", help="Update local mirror database from GitHub")
    p_upd.add_argument("--force", action="store_true", help="Force re-download")
    sub.add_parser("upgrade", help="Upgrade Mira application from GitHub Releases")

    # check
    p_check = sub.add_parser("check", help="Check mirror health")
    p_check.add_argument("provider", nargs="?", choices=["pypi", "debian", "docker"], help="Limit to one provider")
    p_check.add_argument("--refresh", action="store_true", help="Ignore cache and re-check")

    # config
    p_cfg = sub.add_parser("config", help="Manage Mira configuration")
    cfg_sub = p_cfg.add_subparsers(dest="config_cmd")
    cfg_sub.add_parser("show", help="Show full configuration")
    p_get = cfg_sub.add_parser("get", help="Get a configuration value")
    p_get.add_argument("key")
    p_set = cfg_sub.add_parser("set", help="Set a configuration value")
    p_set.add_argument("key")
    p_set.add_argument("value")

    # provider commands factory
    for prov in ("pypi", "debian", "docker"):
        p = sub.add_parser(prov, help=f"{prov} provider commands")
        ps = p.add_subparsers(dest="prov_cmd")
        ps.add_parser("list", help="List known mirrors")
        pc = ps.add_parser("check", help="Check mirrors")
        pc.add_argument("--refresh", action="store_true")
        ps.add_parser("current", help="Show current configuration")
        pset = ps.add_parser("set", help="Select and apply best mirror")
        pset.add_argument("--dry-run", action="store_true")
        pset.add_argument("--scope", choices=["user", "project", "system"], default="user", help="PyPI scope")
        ps.add_parser("reset", help="Reset configuration").add_argument("--dry-run", action="store_true")

    return parser


def _make_providers(cfg: Config, registry: MirrorRegistry, backup: BackupService):
    return {
        "pypi": PyPIProvider(registry, backup),
        "debian": DebianProvider(registry, backup),
        "docker": DockerProvider(registry, backup),
    }


def cmd_status(term: Terminal, cfg: Config, registry: MirrorRegistry) -> int:
    from mira.utils.path_setup import is_mira_on_path, resolve_mira_bin_dir, default_bin_dir
    term.header("MIRA STATUS")
    term.info(f"Version:        {__version__}")
    term.info(f"Config dir:     {cfg.config_dir}")
    term.info(f"Data dir:       {cfg.data_dir}")
    term.info(f"Database dir:   {cfg.database_dir}")
    on_path = is_mira_on_path()
    term.info(f"On PATH:        {'yes' if on_path else 'no'}")
    if not on_path:
        term.info(f"Suggested bin:  {resolve_mira_bin_dir() or default_bin_dir()}")
    if registry.exists():
        try:
            m = registry.load_manifest()
            term.info(f"DB version:     {m.get('database_version')}")
            term.info(f"Countries:      {', '.join(m.get('countries', []))}")
            term.info(f"Providers:      {', '.join(m.get('providers', []))}")
            term.info(f"Filter:         {cfg.countries()}")
        except Exception as e:
            term.warning(f"Database present but invalid: {e}")
    else:
        term.warning("Mirror database not installed. Run: mira update")
    return 0


def cmd_update(term: Terminal, cfg: Config, force: bool = False) -> int:
    updater = DatabaseUpdater(cfg.database_dir, term=term)
    try:
        updater.update(force=force)
        return 0
    except MiraError as e:
        term.error(str(e))
        return e.code


def cmd_check(
    term: Terminal,
    cfg: Config,
    registry: MirrorRegistry,
    provider: str | None,
    refresh: bool,
) -> int:
    if not registry.exists():
        term.error("Mirror database missing. Run 'mira update' first.")
        return 1
    backup = BackupService(cfg.backups_dir)
    providers = _make_providers(cfg, registry, backup)
    cache = HealthCache(cfg.cache_dir, ttl=cfg.get("health_cache_ttl", 900))
    checker = MirrorChecker(cache=cache, max_workers=int(cfg.get("max_workers", 8)), term=term)
    countries = cfg.countries()
    targets = [provider] if provider else list(providers.keys())
    total = healthy = 0
    term.header("Checking mirrors")
    for name in targets:
        prov = providers[name]
        mirrors = prov.list_mirrors(countries=countries)
        if not mirrors:
            term.info(f"{name}: no mirrors found for selected countries")
            continue
        term.print(term.bold(name.upper()))
        results = checker.check_many(mirrors, prov.check_mirror, refresh=refresh)
        for r in results:
            total += 1
            m = r["mirror"]
            ok = r.get("available") and r.get("valid")
            if ok:
                healthy += 1
            detail = ""
            if r.get("latency_ms") is not None:
                detail = f"{r['latency_ms']:.0f} ms"
            if r.get("from_cache"):
                detail += " (cached)" if detail else "(cached)"
            if not ok and r.get("error"):
                detail = r["error"][:40]
            term.status_line(bool(ok), m.get("name") or m.get("id"), detail)
        term.print()
    term.info(f"Summary: {healthy}/{total} healthy")
    return 0 if healthy > 0 or total == 0 else 7


def cmd_provider(
    term: Terminal,
    cfg: Config,
    registry: MirrorRegistry,
    provider_name: str,
    action: str,
    args: argparse.Namespace,
) -> int:
    if not registry.exists() and action != "current":
        term.error("Mirror database missing. Run 'mira update' first.")
        return 1
    backup = BackupService(cfg.backups_dir)
    providers = _make_providers(cfg, registry, backup)
    prov = providers[provider_name]
    countries = cfg.countries()

    if action == "list":
        mirrors = prov.list_mirrors(countries=countries)
        term.header(f"{provider_name.upper()} mirrors")
        rows = []
        for m in mirrors:
            rows.append([
                m.get("id", ""),
                m.get("country", ""),
                m.get("name", "")[:40],
                m.get("url", "")[:50],
                str(m.get("priority", "")),
            ])
        term.table(["ID", "CC", "Name", "URL", "Prio"], rows)
        return 0

    if action == "check":
        return cmd_check(term, cfg, registry, provider_name, getattr(args, "refresh", False))

    if action == "current":
        cur = prov.get_current()
        if cur:
            term.info(str(cur))
        else:
            term.info("No Mira-managed configuration detected.")
        return 0

    if action == "set":
        mirrors = prov.list_mirrors(countries=countries)
        if not mirrors:
            term.error("No mirrors available.")
            return 7
        cache = HealthCache(cfg.cache_dir, ttl=cfg.get("health_cache_ttl", 900))
        checker = MirrorChecker(cache=cache, max_workers=int(cfg.get("max_workers", 8)), term=term)
        term.info(f"Checking {len(mirrors)} mirrors...")
        results = checker.check_many(mirrors, prov.check_mirror, refresh=True)
        selector = MirrorSelector(strategy=cfg.get("strategy", "balanced"))
        try:
            best = selector.select(results)
        except NoHealthyMirrorError:
            term.error("No healthy mirror found.")
            return 7
        m = best["mirror"]
        term.success(
            f"Selected: {m.get('name')} ({m.get('id')}) "
            f"score={best['score']} latency={best.get('latency_ms')}ms"
        )
        dry = getattr(args, "dry_run", False)
        opts: dict[str, Any] = {"dry_run": dry}
        if provider_name == "pypi":
            opts["scope"] = getattr(args, "scope", "user")
        try:
            summary = prov.apply(m, **opts)
            term.info(str(summary))
            if dry:
                term.info("(dry-run — no changes written)")
            return 0
        except MiraError as e:
            term.error(str(e))
            return e.code

    if action == "reset":
        dry = getattr(args, "dry_run", False)
        try:
            summary = prov.reset(dry_run=dry)
            term.info(str(summary))
            return 0
        except MiraError as e:
            term.error(str(e))
            return e.code

    term.error(f"Unknown action: {action}")
    return 1


def cmd_config(term: Terminal, cfg: Config, args: argparse.Namespace) -> int:
    sub = getattr(args, "config_cmd", None)
    if sub == "show" or sub is None:
        for k, v in sorted(cfg.data.items()):
            term.info(f"{k}: {v}")
        return 0
    if sub == "get":
        term.info(str(cfg.get(args.key)))
        return 0
    if sub == "set":
        try:
            cfg.set(args.key, args.value)
            term.success(f"Set {args.key} = {cfg.get(args.key)}")
            return 0
        except MiraError as e:
            term.error(str(e))
            return e.code
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    term = Terminal(
        use_color=not getattr(args, "no_color", False),
        quiet=getattr(args, "quiet", False),
        verbose=getattr(args, "verbose", False),
    )
    cfg = Config()
    try:
        cfg.load()
    except MiraError as e:
        term.error(str(e))
        return e.code

    # Offer permanent PATH setup when `mira` is not on PATH (interactive only)
    try:
        maybe_offer_path_setup(cfg, term)
    except Exception:
        pass

    registry = MirrorRegistry(cfg.database_dir)
    cmd = args.command

    if cmd is None:
        parser.print_help()
        return 0
    if cmd == "status":
        return cmd_status(term, cfg, registry)
    if cmd == "update":
        return cmd_update(term, cfg, force=getattr(args, "force", False))
    if cmd == "upgrade":
        upgrader = AppUpgrader(term=term)
        try:
            upgrader.upgrade(dry_run=False)
            return 0
        except MiraError as e:
            term.error(str(e))
            return e.code
        except Exception as e:
            term.error(str(e))
            return 8
    if cmd == "check":
        return cmd_check(term, cfg, registry, getattr(args, "provider", None), getattr(args, "refresh", False))
    if cmd == "config":
        return cmd_config(term, cfg, args)
    if cmd in ("pypi", "debian", "docker"):
        action = getattr(args, "prov_cmd", None)
        if not action:
            parser.parse_args([cmd, "--help"])
            return 0
        return cmd_provider(term, cfg, registry, cmd, action, args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())