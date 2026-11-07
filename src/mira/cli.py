"""Mira command-line interface (argparse only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
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
from mira.services.uninstaller import uninstall as run_uninstall
from mira.services.verify import verify_provider
from mira.services.ephemeral import run_pip, run_apt, run_docker


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
    p_un = sub.add_parser("uninstall", help="Remove Mira completely from this user account")
    p_pip = sub.add_parser("pip", help="Run pip via best mirror (ephemeral, no permanent config)")
    p_pip.add_argument("pip_args", nargs=argparse.REMAINDER, help="Arguments passed to pip")
    p_apt = sub.add_parser("apt", help="Run apt-get via best mirror (ephemeral, no permanent config)")
    p_apt.add_argument("apt_args", nargs=argparse.REMAINDER, help="Arguments passed to apt-get")
    p_reset = sub.add_parser(
        "reset",
        help="Restore all providers (pypi/debian/docker) to default upstream configuration",
    )
    p_reset.add_argument("--dry-run", action="store_true", help="Show what would be changed")
    p_reset.add_argument(
        "--provider",
        choices=["pypi", "debian", "docker", "all"],
        default="all",
        help="Limit reset to one provider (default: all)",
    )
    p_un.add_argument("--yes", "-y", action="store_true", help="Do not ask for confirmation")
    p_un.add_argument("--keep-data", action="store_true", help="Keep config/cache/database")

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
        ranked = [r for r in selector.rank(results) if r.get("score", 0) > 0]
        if not ranked:
            term.error("No healthy mirror found.")
            return 7

        dry = getattr(args, "dry_run", False)
        opts: dict[str, Any] = {"dry_run": dry}
        if provider_name == "pypi":
            opts["scope"] = getattr(args, "scope", "user")

        if dry:
            best = ranked[0]
            m = best["mirror"]
            term.success(
                f"Selected: {m.get('name')} ({m.get('id')}) "
                f"score={best['score']} latency={best.get('latency_ms')}ms"
            )
            try:
                summary = prov.apply(m, **opts)
                term.info(str(summary))
                term.info("(dry-run - no changes written, verification skipped)")
                return 0
            except MiraError as e:
                term.error(str(e))
                return e.code

        # Try mirrors in rank order; keep the first that applies AND verifies.
        last_err = None
        for idx, cand in enumerate(ranked, 1):
            m = cand["mirror"]
            term.info(
                f"[{idx}/{len(ranked)}] Trying {m.get('name')} ({m.get('id')}) "
                f"score={cand['score']} latency={cand.get('latency_ms')}ms"
            )
            try:
                summary = prov.apply(m, **opts)
                term.info(str(summary))
            except MiraError as e:
                term.warning(f"Apply failed: {e}")
                last_err = str(e)
                continue

            term.info("Verifying mirror works for real operations...")
            v = verify_provider(provider_name, m)
            if v.get("ok"):
                term.success(
                    f"Verified OK via {v.get('method')} — using {m.get('name')} ({m.get('url')})"
                )
                return 0

            detail = (v.get("detail") or v.get("error") or "unknown failure")[-300:]
            term.warning(f"Verification failed: {detail}")
            last_err = detail
            term.info("Trying next mirror...")

        term.error("All candidate mirrors failed verification.")
        if last_err:
            term.error(str(last_err)[:400])
        return 7

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


def _sanitize_argv(argv: list[str] | None) -> list[str]:
    """Return CLI args without a duplicated program/module name (common on Windows)."""
    if argv is None:
        argv = sys.argv[1:]
    else:
        argv = list(argv)
    drop = {
        APP_NAME,
        f"{APP_NAME}.exe",
        f"{APP_NAME}.cmd",
        f"{APP_NAME}.ps1",
        "__main__.py",
        "-m",
        "mira.__main__",
    }
    # Strip leading junk that some launchers / frozen builds inject
    while argv and (argv[0] in drop or argv[0].lower().endswith("\\mira.exe")
                    or argv[0].lower().endswith("/mira.exe")
                    or Path(argv[0]).name.lower() in drop):
        argv = argv[1:]
    return argv


def cmd_reset(term: Terminal, cfg: Config, registry: MirrorRegistry, args: argparse.Namespace) -> int:
    """Reset one or all providers back to default upstream configuration."""
    dry = getattr(args, "dry_run", False)
    which = getattr(args, "provider", "all") or "all"
    targets = ["pypi", "debian", "docker"] if which == "all" else [which]

    backup = BackupService(cfg.backups_dir)
    providers = _make_providers(cfg, registry, backup)
    term.header("MIRA RESET")
    if dry:
        term.info("(dry-run - no changes will be written)")

    any_error = False
    for name in targets:
        prov = providers[name]
        term.info(f"Resetting {name}...")
        try:
            # PyPI: reset user scope (primary); also try project if present
            if name == "pypi":
                summary = prov.reset(dry_run=dry, scope="user")
                term.info(f"  pypi/user: {summary}")
                try:
                    summary_p = prov.reset(dry_run=dry, scope="project")
                    if summary_p.get("status") not in (None, "nothing to reset", "no index-url found"):
                        term.info(f"  pypi/project: {summary_p}")
                except Exception:
                    pass
            else:
                summary = prov.reset(dry_run=dry)
                term.info(f"  {name}: {summary}")
            term.success(f"{name}: restored to default upstream")
        except MiraError as e:
            any_error = True
            term.error(f"{name}: {e}")
        except Exception as e:
            any_error = True
            term.error(f"{name}: {e}")

    if any_error:
        term.warning("Finished with some errors.")
        return 1
    term.success("All requested providers reset to default configuration.")
    return 0



def main(argv: list[str] | None = None) -> int:
    raw = _sanitize_argv(argv)
    # Ephemeral docker: mira docker pull nginx  (not mira docker list/set/...)
    _docker_managed = {"list", "check", "current", "set", "reset", "-h", "--help"}
    if raw and raw[0] == "docker" and len(raw) > 1 and raw[1] not in _docker_managed:
        term = Terminal(use_color=True, quiet=False, verbose=False)
        cfg = Config()
        try:
            cfg.load()
        except MiraError as e:
            term.error(str(e))
            return e.code
        registry = MirrorRegistry(cfg.database_dir)
        try:
            return run_docker(cfg, registry, raw[1:], term)
        except NoHealthyMirrorError as e:
            term.error(str(e) or "No healthy docker mirror")
            return 7
        except MiraError as e:
            term.error(str(e))
            return e.code

    parser = build_parser()
    args = parser.parse_args(raw)
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

    cmd = args.command

    # Do not offer PATH install when the user is uninstalling
    if cmd != "uninstall":
        try:
            maybe_offer_path_setup(cfg, term)
        except Exception:
            pass

    registry = MirrorRegistry(cfg.database_dir)

    # First-run: if database is missing, fetch it automatically (except for update/uninstall/help-only)
    if (
        cmd not in (None, "update", "uninstall", "upgrade")
        and not registry.exists()
    ):
        term.info("Mirror database missing; running mira update once...")
        try:
            code = cmd_update(term, cfg, force=False)
            if code != 0:
                term.warning("Auto-update failed; run: mira update")
        except Exception as e:
            term.warning(f"Auto-update failed: {e}")

    if cmd is None:
        parser.print_help()
        return 0
    if cmd == "reset":
        return cmd_reset(term, cfg, registry, args)
    if cmd == "uninstall":
        return run_uninstall(
            purge_data=not getattr(args, "keep_data", False),
            assume_yes=getattr(args, "yes", False),
            term=term,
        )
    if cmd == "pip":
        try:
            return run_pip(cfg, registry, getattr(args, "pip_args", []) or [], term)
        except NoHealthyMirrorError as e:
            term.error(str(e) or "No healthy PyPI mirror")
            return 7
        except MiraError as e:
            term.error(str(e))
            return e.code
    if cmd == "apt":
        try:
            return run_apt(cfg, registry, getattr(args, "apt_args", []) or [], term)
        except NoHealthyMirrorError as e:
            term.error(str(e) or "No healthy Debian mirror")
            return 7
        except MiraError as e:
            term.error(str(e))
            return e.code
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