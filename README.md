# Mira

**Universal Software Repository Mirror Manager**

One CLI. Multiple ecosystems. Intelligent mirror discovery, health checks, ranking, and configuration.

Mira helps you find fast, healthy package mirrors and either apply them permanently or use them for a single command — without fighting slow or blocked upstream registries.

**Repository:** [github.com/soroush-zendedel/Mira](https://github.com/soroush-zendedel/Mira)

---

## Supported ecosystems

| Provider | Permanent config | One-shot / ephemeral commands |
|----------|------------------|-------------------------------|
| **PyPI** (pip) | `mira pypi set` | `mira pip install …` |
| **npm** | `mira npm set` | `mira npm install …` |
| **Debian / Ubuntu APT** | `mira debian set` | `mira apt install …` |
| **Arch Linux pacman** | `mira pacman set` | `mira pacman -S …` |
| **Docker Engine** | `mira docker set` | `mira docker pull …` |

---

## Highlights

- **Zero runtime dependencies** — pure Python 3.10+ stdlib (build tools like PyInstaller are CI-only).
- **Curated mirror database** — country-tagged HTTPS mirrors, versioned and checksum-verified from GitHub.
- **Concurrent health checks** — protocol-aware probes (not just HTTP 200), with local caching.
- **Smart ranking** — scores availability, validity, latency, stability, and priority; strategies: `balanced`, `fastest`, `reliability`.
- **Safe writes** — backups before changing system or user config; `--dry-run` previews without writing.
- **Ephemeral mode** — run package-manager commands through the best mirror *without* permanent config changes; retries across mirrors until success or `Ctrl+C`.
- **Self-update** — `mira update` refreshes the mirror DB; `mira upgrade` upgrades the app (source or binary installs).
- **Privilege-aware** — system operations re-launch with `sudo` when needed; dry-runs never elevate.
- **Cross-platform packaging** — Linux/Windows standalone binaries, `.deb`, Arch `.pkg.tar.zst`, and source installers.

---

## Install

Release assets are built by GitHub Actions when a `v*` tag is pushed. Always verify with `SHA256SUMS` from the same release.

### Windows (standalone EXE)

1. Download `mira-windows-x86_64.exe` from [Releases](https://github.com/soroush-zendedel/Mira/releases/latest)
2. Rename to `mira.exe` and put it on your PATH

```powershell
powershell -ExecutionPolicy Bypass -File .\installers\install.ps1 -FromRelease
```

### Linux (standalone binary)

```bash
curl -fsSL -o /tmp/mira https://github.com/soroush-zendedel/Mira/releases/latest/download/mira-linux-x86_64
chmod +x /tmp/mira
sudo mv /tmp/mira /usr/local/bin/mira
mira --version && mira update
```

### Debian / Ubuntu (`.deb`)

```bash
DEB_URL=$(curl -fsSL https://api.github.com/repos/soroush-zendedel/Mira/releases/latest \
  | grep -oE 'https://[^"]+/mira_[0-9.]+_amd64\.deb' | head -n1)
curl -fsSL -o /tmp/mira.deb "$DEB_URL"
sudo dpkg -i /tmp/mira.deb
mira --version && mira update
```

Requires `python3 >= 3.10`.

### Arch Linux (`.pkg.tar.zst`)

```bash
PKG_URL=$(curl -fsSL https://api.github.com/repos/soroush-zendedel/Mira/releases/latest \
  | grep -oE 'https://[^"]+/mira-[0-9.]+-[0-9]+-any\.pkg\.tar\.zst' | head -n1)
curl -fsSL -o /tmp/mira.pkg.tar.zst "$PKG_URL"
sudo pacman -U /tmp/mira.pkg.tar.zst
mira --version && mira update
```

The package is owned by **pacman**. Upgrade it with `sudo pacman -Syu` (or `-U`); do **not** use `mira upgrade` for pacman-managed installs.

### From source

```bash
git clone https://github.com/soroush-zendedel/Mira.git
cd Mira
bash installers/install.sh          # Linux
# powershell -ExecutionPolicy Bypass -File .\installers\install.ps1   # Windows
```

---

## Quick start

```bash
mira update                 # download / refresh mirror database
mira status                  # paths, DB version, countries, providers
mira check                   # health-check all providers
mira check pypi --refresh    # force re-check one provider

mira pypi list
mira pypi set --dry-run      # preview best mirror
mira pypi set                # apply best healthy mirror (user scope)

mira npm set
mira debian set              # may prompt for sudo
mira pacman set
mira docker set              # then restart Docker yourself if needed
```

---

## Command reference

### Global

| Command | Purpose |
|---------|---------|
| `mira status` | Installation paths, DB version, config summary |
| `mira update [--force]` | Refresh local mirror database from GitHub (single archive download) |
| `mira upgrade` | Upgrade Mira itself (binary or source install; refuses pacman-owned installs) |
| `mira check [provider] [--refresh]` | Concurrent mirror health checks |
| `mira config show \| get \| set` | View or change config (`countries`, `strategy`, timeouts, …) |
| `mira reset [provider] [--dry-run]` | Restore provider(s) to default upstream |
| `mira uninstall [--keep-data]` | Remove Mira from the user account |

### Per provider (`pypi` · `npm` · `debian` · `docker` · `pacman`)

| Action | Purpose |
|--------|---------|
| `list` | List known mirrors (respects country filter) |
| `check [--refresh]` | Health-check this provider’s mirrors |
| `current` / `status` | Show active Mira-managed configuration |
| `set [--dry-run]` | Rank healthy mirrors and apply the best |
| `reset [--dry-run]` | Remove Mira’s config / restore previous sources |

**PyPI / npm scopes:** `--scope user` (default), `project`, or `system`.

### Ephemeral package-manager passthrough

These use ranked mirrors for **this invocation only** (no permanent config). Failed mirrors are retried in cycles until success or `Ctrl+C` (exit `130`).

```bash
mira pip install requests
mira npm install lodash
mira apt install curl
mira pacman -S cowsay          # auto-adds -y to refresh DBs when needed
mira docker pull nginx
```

- Explicit user flags (e.g. npm `--registry`, pip `--index-url`) are preserved and skip Mira’s selection.
- Reserved management verbs (`list`, `check`, `set`, …) stay with Mira and are not forwarded.

---

## How ranking works

1. Load mirrors from the local database (optional country filter).
2. Run concurrent, **read-only**, provider-specific health probes.
3. Score each result: availability, validity, latency, stability, priority.
4. Select by strategy: `balanced` (default), `fastest`, or `reliability`.
5. On `set`, verify the chosen mirror with a real package-manager operation when applicable; try the next candidate if verification fails.

Health results are cached (default TTL 15 minutes). Use `--refresh` to force a new probe.

---

## Configuration

```bash
mira config show
mira config set countries ir,de,us     # or * for all
mira config set strategy fastest
mira config set timeout 5
```

| Key | Meaning |
|-----|---------|
| `countries` | ISO country codes or `*` |
| `strategy` | `balanced` · `fastest` · `reliability` |
| `timeout` / `read_timeout` | Network timeouts (seconds) |
| `max_workers` | Concurrent health-check workers |
| `health_cache_ttl` | Cache lifetime (seconds) |
| `prefer_countries` | Soft preference in ranking |

Config lives under the user config dir (`~/.config/mira` on Linux; `%APPDATA%\Mira` on Windows). Database, cache, and backups live under the user data dir.

---

## Provider notes

### PyPI
Writes `index-url` / `extra-index-url` for the chosen scope. Prefer `user` or `project` over `system`.

### npm
Permanent `set` updates `.npmrc`. Ephemeral `mira npm …` passes `--registry` and does not edit `.npmrc`.

### Debian / Ubuntu APT
`set` takes exclusive control of active APT sources: backs up and moves `/etc/apt/sources.list` and active `.list` / `.sources` files to `/var/lib/mira/apt-disabled/` (outside `sources.list.d`, so apt does not warn about unknown extensions), then writes Deb822 `mira.sources` with an explicit `Signed-By` keyring. `reset` restores previous sources. Keyrings are never weakened or removed.

### Arch pacman
`set` prepends a Mira-managed HTTPS server block in the mirrorlist. Ephemeral `mira pacman -S …` uses a temporary config + mirrorlist and refreshes package DBs (`-y`) when the user did not already request it.

### Docker
Updates registry mirrors in `daemon.json` (Linux). Restart Docker yourself after `set`. Ephemeral `pull`/`run` can rewrite image references through the selected registry mirror host.

---

## Privileges

| Operation | Elevation |
|-----------|-----------|
| `list` / `check` / `status` / `update` / dry-runs | None |
| `pypi`/`npm` set (`user` / `project`) | None |
| `debian` / `docker` / `pacman` set & reset | Root (auto `sudo` on Linux) |
| `pypi set --scope system` | Root when required |

On Linux, Mira re-runs itself via `sudo env MIRA_ELEVATED=1 …` when a system write is required (avoids `sudo -E` policy warnings). On Windows, use an elevated shell for system-level changes.

---

## Upgrading Mira

| Install type | Command |
|--------------|---------|
| User / source | `mira upgrade` (fetches release **source** archive) |
| Standalone binary | `mira upgrade` (replaces the binary) |
| Arch package | `sudo pacman -Syu` or `pacman -U` a newer `.pkg.tar.zst` |
| Debian `.deb` | Install a newer `.deb` with `dpkg` / `apt` |

`mira upgrade` refuses to overwrite pacman-managed files.

---

## Design principles

- HTTPS-only mirror URLs in the database.
- Health checks never mutate system configuration.
- Atomic mirror-database install with SHA-256 integrity from the manifest.
- Robust TLS on frozen binaries: system CA bundles are loaded explicitly (fixes common PyInstaller `CERTIFICATE_VERIFY_FAILED` cases).
- No telemetry; no third-party runtime network stacks.

---

## Development

```bash
export PYTHONPATH=src
python -m mira --version
python -m unittest discover -s tests -v
```

See `AGENTS.md` for contributor conventions, provider checklist, and release process. Pushing a `v*` tag runs `.github/workflows/release.yml` (Linux/Windows binaries, `.deb`, Arch package, source zip, `SHA256SUMS`).

---

## License

MIT — see [LICENSE](LICENSE).
