# Mira Architecture

## Layers

1. **CLI** (`cli.py`) – argparse only, dispatches to commands.
2. **Config** – user preferences, paths, strategy.
3. **Registry** – local mirror database loaded from `database/`.
4. **Updater** – downloads and validates database from GitHub.
5. **Checker** – concurrent provider-specific health checks + cache.
6. **Scoring / Selector** – ranks healthy mirrors.
7. **Providers** – PyPI, npm, Debian, Docker (apply/reset/list/check).
8. **Services** – backup, configuration helpers.
9. **Utils** – network, terminal, filesystem, platform, validation.

## Design constraints

- Zero third-party runtime dependencies.
- Atomic database replacement.
- Never modify system config during `check`.
- Backups before any write.
- HTTPS-only mirror URLs.
- Provider interface isolation.

## Data flow (set)

```
mira pypi set
  → load config & registry
  → list mirrors (country filter)
  → concurrent check_mirror()
  → score & select best
  → backup existing config
  → apply (dry-run optional)
```
