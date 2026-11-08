# Agent Guide for Mira

This file describes the repository conventions for agents and contributors.
Read it before changing application code, mirror data, tests, or release files.

## Project overview

Mira is a Python command-line application for discovering, checking, ranking,
and configuring software repository mirrors. It supports PyPI, npm, Debian APT,
and Docker Engine. The application targets Python 3.10+ and has no third-party
Python runtime dependencies; build tools such as PyInstaller are build-time
dependencies only.

The application uses a provider interface so ecosystem-specific behavior stays
separate from shared database, health-check, scoring, backup, and CLI code.
Start with `docs/architecture.md` for the high-level flow and `README.md` for
user-facing behavior.

## Repository map

- `src/mira/cli.py` — argparse commands, provider registration, dispatch, and
  command orchestration.
- `src/mira/providers/` — provider implementations. Each provider implements
  `RepositoryProvider` from `providers/base.py`.
- `src/mira/core/registry.py` — reads and filters the local mirror database.
- `src/mira/core/checker.py` — concurrent checks and health-result caching.
- `src/mira/core/scoring.py`, `selector.py` — mirror ranking and selection.
- `src/mira/core/updater.py` — fetches, validates, checksum-checks, and
  atomically installs the mirror database.
- `src/mira/services/backup.py` — backups before configuration writes.
- `src/mira/services/verify.py` — functional verification after a provider's
  `set` operation.
- `src/mira/services/ephemeral.py` — package-manager commands that use ranked
  mirrors without persistent configuration changes. Repository-dependent
  operations retry full mirror cycles until success or `Ctrl+C` cancellation.
- `mirrors/` — source mirror database shipped and fetched by the updater.
- `tests/` — standard-library `unittest` tests.
- `.github/workflows/ci.yml` — test matrix.
- `.github/workflows/release.yml`, `scripts/`, `packaging/` — release builds.

## Design rules

- Keep Python runtime dependencies at zero unless a change explicitly requires
  and justifies a new dependency.
- Use HTTPS mirror URLs. `validate_mirrors_file` enforces this requirement.
- Health checks must be read-only. They must never alter package-manager or
  system configuration.
- Provider `apply` methods must honor `dry_run`, preserve unrelated settings,
  and create a backup before writing an existing configuration file.
- Debian APT `set` intentionally takes exclusive control of active source
  inputs: back up and disable `/etc/apt/sources.list` and active `.list` and
  `.sources` files, then write the Mira Deb822 source. Keep disabled copies
  recoverable for `reset`, refuse restore-path conflicts, and use an explicit
  installed archive keyring with `Signed-By`; never modify or weaken APT trust.
- Provider `reset` methods should remove only Mira's relevant setting and
  preserve other configuration where possible.
- Do not silently disable TLS or signature verification to make a mirror work.
- Use `fetch_url` and the existing network/error abstractions for HTTP checks.
  Return the common health fields: `available`, `valid`, `latency_ms`,
  `error`, and optionally `stability`.
- Use protocol-aware probes. A successful HTTP response alone may be
  insufficient; validate ecosystem-specific metadata or repository structure.
- Keep mirror selection in the shared checker/scorer/selector. Do not duplicate
  scoring rules in a provider.
- Update user documentation and tests with behavior changes.

## Adding another ecosystem provider

For an ecosystem such as pacman, follow this checklist. Adapt configuration and
health checks to the actual package manager instead of copying another
provider's protocol details verbatim.

1. **Research candidate mirrors.** Confirm the official configuration URL and
   protocol from the mirror operator or authoritative project documentation.
   Record the source URL alongside each mirror entry when practical. Do not
   infer hosting country from a domain name. Mark a shared upstream as a global
   registry rather than claiming it is a country-local mirror.
2. **Add mirror data.** Create
   `mirrors/<country>/<provider>/mirrors.json` with `schema_version: 1`, the
   matching `country` and `provider`, and mirror records containing unique
   `id`, `name`, HTTPS `url`, `enabled`, and `priority`. Use the conventions in
   neighboring provider files.
3. **Update `mirrors/manifest.json`.** Add the provider to `providers`, bump
   `database_version`, update `updated_at`, and add SHA-256 values for every
   changed or new mirror file under `integrity.files`. Hash the exact bytes
   written to disk, including the final newline. Check every listed digest
   after editing. The updater downloads `<country>/<provider>/mirrors.json` for
   each manifest country/provider pair and skips absent remote files.
4. **Implement the provider.** Add `src/mira/providers/<provider>.py` and
   implement `list_mirrors`, `check_mirror`, `get_current`, `apply`, and
   `reset`. Use a minimal, read-only, protocol-valid health probe. Make paths
   platform-aware and give clear errors for unsupported platforms or
   insufficient privileges. Pacman usually configures `/etc/pacman.conf` or
   mirror-list files and is Linux-specific; preserve unrelated repository and
   signing settings, make backups, and never disable package signature checks.
5. **Register it throughout the application.** Update
   `SUPPORTED_PROVIDERS` in `constants.py`, the provider factory
   `_make_providers`, the provider choices for `check`, provider command
   registration in `build_parser`, and `cmd_reset`'s provider list. Add a
   `verify_<provider>` function and route to it in `verify_provider` if `set`
   uses post-apply verification. Check status/help text and docs for hard-coded
   provider lists.
6. **Decide whether one-shot dispatch is in scope.** Persistent management
   (`list/check/current/set/reset`) does not automatically imply one-shot
   package-manager passthrough. If adding passthrough, register the provider in
   the provider maps in `services/ephemeral.py`, implement a runner that passes
   the registry only to the child process, and add an early CLI dispatch
   branch before argparse. For repository-dependent operations, cycle through
   ranked mirrors, refresh the ranking after exhausting a cycle, and stop only
   on success or `Ctrl+C` (exit code 130). Avoid modifying persistent
   configuration for these commands. Keep local and Mira management commands
   outside the retry loop.
7. **Add tests.** Cover data loading and country filtering, protocol-valid and
   invalid health responses, URL and configuration parsing, `dry_run`, backup
   and preservation behavior, reset behavior, CLI parsing/dispatch, and
   functional verification. Mock `fetch_url`, subprocess calls, platform
   detection, and filesystem paths; tests should not depend on live mirrors or
   mutate the host's real configuration.
8. **Document usage and risk.** Explain required privileges, supported
   platforms, scope behavior, commands to manually test each registry, and
   limitations such as private/scoped registries or lockfiles where relevant.

## CLI dispatch and avoiding command collisions

`build_parser()` owns Mira's management interface. Provider commands currently
use the shape `mira <provider> list|check|current|status|set|reset`.

Some package managers also need direct commands under the `mira` prefix. Mira
handles these before `argparse`:

- Docker uses an explicit set of Docker CLI verbs in `main()`. Mira provider
  actions such as `mira docker list` and `mira docker set` remain argparse
  commands; Docker operations such as `mira docker pull nginx` are sent to the
  retrying runner for `docker pull`.
- npm uses `_should_run_npm_passthrough()`. The reserved management actions
  (`list`, `check`, `current`, `status`, `set`, `reset`) stay with Mira; other
  npm commands such as `mira npm view express version` go to the npm runner.
  The runner supplies ranked registries with a command-line option and retries
  full cycles until success or cancellation; it does not change `.npmrc`. An
  explicit npm `--registry` is preserved and bypasses selection.
- `mira pip ...` and `mira apt ...` have dedicated top-level parsers and
  dispatch paths.

When extending dispatch, define the command ownership first. Choose how to
resolve overlaps (for example, npm's own `list` overlaps Mira's `list`), keep
Mira management actions reserved, and route package-manager commands before
argparse rejects them. Prefer explicit verb sets when the external CLI has
stable, known verbs; use a tested predicate if passthrough intentionally accepts
the external CLI's full command surface. Do not accidentally capture global
Mira options, `--help`, or `--version`. Test both sides of the boundary:
management commands stay in Mira and ordinary package-manager commands reach
the child process. Preserve argument order and the child's exit code.

## Tests and local development

Run tests from the repository root:

```bash
export PYTHONPATH=src
python -m mira --version
python -m unittest discover -s tests -v
```

In PowerShell, set the module path before running them:

```powershell
$env:PYTHONPATH = "src"
python -m mira --version
python -m unittest discover -s tests -v
```

The CI workflow runs these tests on Python 3.10, 3.11, and 3.12 on Ubuntu. Keep
tests deterministic: mock network probes and subprocesses rather than requiring
public internet, npm, Docker, root access, or a live package manager. When
testing code paths that write configuration, use a temporary directory or
patch the relevant path helper.

## Build and release

Source development uses `PYTHONPATH=src`; `python -m mira` runs the CLI without
installing it. `pyproject.toml` uses setuptools and exposes the `mira` console
script. Standalone builds use PyInstaller and have no runtime package install
step beyond the bundled interpreter.

Local optional build commands:

```bash
bash scripts/build_standalone.sh
bash scripts/build_deb.sh 1.0.0
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_standalone.ps1
```

Pushing a version tag matching `v*` triggers `.github/workflows/release.yml`.
CI builds a Linux standalone executable and `.deb`, a Windows standalone
executable, an Arch Linux package (on an Arch container), a source ZIP, and
`SHA256SUMS`, then attaches them to a GitHub Release. The build tools are
installed by CI and are not runtime dependencies. The source archive uses
`git archive HEAD`, so only committed files in the tagged commit are included.

`mira upgrade` fetches the release **source** archive for user/source installs
and replaces the package tree. For pacman-managed (Arch) installs it refuses to
overwrite files and tells the user to upgrade with pacman.

Before a release, use the helper scripts in `scripts/` to synchronize
`VERSION`, `src/mira/__init__.py`, `src/mira/constants.py`, and
`pyproject.toml`; then review the resulting changes, run tests, commit, tag, and
push according to `scripts/README.md`. Do not create or push a release tag
unless the user explicitly requests publishing.
