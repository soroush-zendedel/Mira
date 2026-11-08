# Mira

**Universal Software Repository Mirror Manager**

One CLI. Multiple ecosystems. Intelligent repository mirror management.

Mira discovers, evaluates, selects, and configures software repository mirrors for:

- **PyPI** (pip)
- **npm** (npm CLI)
- **Debian APT**
- **Docker Engine** registry mirrors

Zero third-party Python **runtime** dependencies (stdlib only).

Repository: https://github.com/soroush-zendedel/Mira

---

## Install

Pick one method. Standalone binaries and `.deb` are produced automatically by GitHub Actions when a version tag is pushed.

### Windows — standalone EXE (recommended)

1. Open [Releases](https://github.com/soroush-zendedel/Mira/releases/latest)
2. Download **`mira-windows-x86_64.exe`**
3. Rename to `mira.exe` and place it on your PATH  
   (for example `%LOCALAPPDATA%\Programs\Mira\bin\`)

Or from PowerShell (downloads the release binary):

```powershell
powershell -ExecutionPolicy Bypass -File .\installers\install.ps1 -FromRelease
```

### Linux — standalone binary

```bash
curl -fsSL -o /tmp/mira https://github.com/soroush-zendedel/Mira/releases/latest/download/mira-linux-x86_64
chmod +x /tmp/mira
sudo mv /tmp/mira /usr/local/bin/mira
mira --version
mira update
```

`/usr/local/bin` is on PATH by default. No extra PATH setup needed.

Or:

```bash
bash installers/install.sh --from-release
```

### Debian / Ubuntu — `.deb` package

Wildcards do **not** work inside the download URL. Resolve the latest asset name first:

```bash
# 1) Find the exact .deb name from the latest release
DEB_URL=$(curl -fsSL https://api.github.com/repos/soroush-zendedel/Mira/releases/latest \
  | grep -oE 'https://[^"]+/mira_[0-9.]+_amd64\.deb' | head -n1)

# 2) Download and install
curl -fsSL -o /tmp/mira.deb "$DEB_URL"
sudo dpkg -i /tmp/mira.deb
mira --version
mira update
```

Or with a known version (example):

```bash
curl -fsSL -o /tmp/mira.deb \
  https://github.com/soroush-zendedel/Mira/releases/latest/download/mira_1.0.6_amd64.deb
sudo dpkg -i /tmp/mira.deb
```

Requires `python3 >= 3.10`. The package installs to `/usr/bin/mira` (already on PATH).

### From source (no pip, works offline after clone)

**Linux**

```bash
git clone https://github.com/soroush-zendedel/Mira.git
cd Mira
bash installers/install.sh
```

**Windows** (no `irm` required)

```powershell
git clone https://github.com/soroush-zendedel/Mira.git
cd Mira
powershell -ExecutionPolicy Bypass -File .\installers\install.ps1
```

Or download the ZIP from GitHub → extract → run the same installer script.

### Verify downloads

Each Release includes **`SHA256SUMS`**. Example:

```bash
sha256sum -c SHA256SUMS
```

---

## Quick start

```bash
mira update          # refresh mirror database from GitHub
mira status
mira check           # all providers
mira check pypi
mira pypi list
mira pypi set --dry-run
mira pypi set        # apply best healthy mirror (user scope)
mira npm list
mira npm set --dry-run
mira npm view express version  # retry mirrors until the command succeeds
mira config set countries ir,de
```

## npm commands and mirror selection

Mira keeps npm's own commands available behind the `mira npm` prefix:

- Mira management actions: `mira npm list`, `check`, `current`, `status`, `set`, and `reset`.
- Other commands are passed to the installed npm CLI. For example,
  `mira npm view express version` or `mira npm install lodash`.

For registry-dependent npm commands, Mira checks the configured npm mirrors
for the selected countries, ranks healthy ones using the configured strategy,
and adds each URL as a command-line `--registry` option. If a command fails on
every candidate, Mira waits three seconds, checks the mirrors again, and
repeats until it succeeds. Press `Ctrl+C` to cancel. This applies to that
invocation only; it does not edit `.npmrc`. An explicit `--registry` supplied
by the user is preserved and bypasses Mira's retry loop. The native `npm`
command must be installed separately. Run `mira update` before the first
Mira-managed npm command so the mirror database is present.

The same retry behavior applies to Mira-managed `pip` package retrieval,
APT commands that need repository indexes (`update`, `install`, `upgrade`,
`download`, `source`, and `build-dep`), and `docker pull`. A command that keeps
failing will keep retrying, including when the cause is a missing package/image
or an invalid argument; cancel it with `Ctrl+C` and correct the command. Local
package-manager operations and Mira management commands are not wrapped in the
retry loop.

To change npm's persistent default, use Mira's provider action instead:

```sh
mira npm list
mira npm check --refresh
mira npm set --dry-run
mira npm set --scope user       # writes the user .npmrc, after backup
npm config get registry         # inspect npm's effective default
mira npm reset --scope user
```

`--scope` supports `user` (default), `project` (the current directory's
`.npmrc`), and `system`. Mira preserves authentication and per-scope registry
entries. Persistent registry settings also affect publishing; target the
intended writable registry explicitly when publishing. npm can also use a
registry assigned to a package scope (such as `@company`); those entries are
preserved and may take precedence for matching packages. Lockfiles can contain
resolved tarball URLs from the registry used when they were created; inspect
`resolved` fields if an install still contacts a different host.

`mira reset --provider npm` resets npm's user and project settings;
`mira reset --dry-run` previews a reset for all providers.

### Manually test each configured npm registry

The health checker requests the public `express` package metadata at
`<registry>/express`, then confirms the response names `express` and contains
versions. These `npm view` commands query that same package metadata endpoint.
Each command bypasses automatic selection and tests only the specified URL:

| Country | Registry | Manual test |
|---|---|---|
| Iran | Runflare | `npm view express version --registry="https://mirror-npm.runflare.com/"` |
| Iran | Novin Cloud | `npm view express version --registry="https://mirror.novin.cloud/artifactory/api/npm/npm/"` |
| Iran | Kargadan | `npm view express version --registry="https://mirror.kargadan.ir/nexus/repository/npm-group/"` |
| Iran | npmjs public registry | `npm view express version --registry="https://registry.npmjs.org/"` |
| US, Switzerland, Germany | npmjs public registry (global option) | `npm view express version --registry="https://registry.npmjs.org/"` |

A successful command prints an Express version. To ask Mira to probe and
display all configured mirrors for your country filter, run:

```sh
mira npm check --refresh
```

To let Mira select a healthy one and make the same query, run:

```sh
mira npm view express version
```

Mira's current registry list and detailed npm notes are in [docs/npm.md](docs/npm.md).

### Docker / APT (need elevation)

```bash
mira docker set --dry-run
sudo mira docker set
sudo systemctl restart docker   # Mira does not restart Docker for you

mira debian set --dry-run
sudo mira debian set
```

See [docs/privileges.md](docs/privileges.md).

### Everyday provider workflow

The same management actions are available for `pypi`, `npm`, `debian`, and
`docker`:

```sh
mira <provider> list
mira <provider> check --refresh
mira <provider> current
mira <provider> set --dry-run
mira <provider> set
mira <provider> reset
```

`set --dry-run` previews the chosen mirror and configuration change. A normal
`set` backs up the destination configuration and verifies the selected mirror
after applying it. `check` only checks health; it does not change package
manager settings. The checker caches results for a while; use `--refresh` to
force a new check.

For APT, `mira debian set` takes exclusive control of active source inputs:
`/etc/apt/sources.list` and active `.list` and `.sources` files in
`/etc/apt/sources.list.d/` are backed up and renamed with a
`.mira-disabled` suffix before Mira writes its own Deb822 source file. This
temporarily disables third-party repositories as well as distribution
repositories. `mira debian reset` restores the original filenames and content;
it stops safely if a path has since been recreated. Mira does not edit or
delete keyring files. Its source uses the installed Debian or Ubuntu archive
keyring through `Signed-By`, and `set` refuses to proceed if that keyring is
missing. Review `mira debian set --dry-run` before applying the change.

Mira uses all countries by default. Narrow the candidate list with
`mira config set countries ir` or a comma-separated list such as
`mira config set countries ir,de`; use `*` to return to all countries. Mirror
ranking can be tuned with `mira config set strategy balanced` (or `fastest` or
`reliability`). Run `mira config show` to inspect these settings and
`mira status` to see the database version and configured country filter.

APT and Docker write system-level configuration and usually require elevation
for `set`. Mira backs up files before writing and does not restart Docker
automatically; see [docs/privileges.md](docs/privileges.md).

---

## How releases are built

On every version tag (`v1.2.3`), GitHub Actions (`.github/workflows/release.yml`) builds:

| Asset | Platform |
|-------|----------|
| `mira-linux-x86_64` | Linux standalone (PyInstaller) |
| `mira-windows-x86_64.exe` | Windows standalone (PyInstaller) |
| `mira_<ver>_amd64.deb` | Debian package |
| `mira-<ver>-source.zip` | Source archive |
| `SHA256SUMS` | Checksums |

**Publish a release (maintainers):**

```bash
bash scripts/make_release_tag.sh 1.0.0
# review version bump, then:
git commit -m "Release v1.0.0"
git tag -a v1.0.0 -m "Mira v1.0.0"
git push origin main
git push origin v1.0.0
```

CI builds the assets and attaches them to the GitHub Release. No manual upload required.

Local optional builds:

```bash
bash scripts/build_standalone.sh              # Linux binary (pyinstaller)
powershell -File .\scripts\build_standalone.ps1   # Windows mira.exe
bash scripts/build_deb.sh 1.0.0                 # .deb (Linux/WSL only)
```

---

## Configuration

- Linux: `~/.config/mira/config.json` — data under `~/.local/share/mira/`
- Windows: `%APPDATA%\Mira\` — data under `%LOCALAPPDATA%\Mira\`

---



## Versioning

Mira uses [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`).

| File | Role |
|------|------|
| `VERSION` | Single source of truth |
| `src/mira/__init__.py` → `__version__` | Runtime (`mira --version`) |
| `pyproject.toml` | Packaging metadata |
| Git tag `vX.Y.Z` | Triggers GitHub Actions release build |

Bump and publish:

**Linux / macOS**

```bash
bash scripts/make_release_tag.sh 1.0.1
git add -A && git commit -m "Release v1.0.1"
git tag -a v1.0.1 -m "Mira v1.0.1"
git push origin main && git push origin v1.0.1
```

**Windows (PowerShell)**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\make_release_tag.ps1 1.0.1
git add -A
git commit -m "Release v1.0.1"
git tag -a v1.0.1 -m "Mira v1.0.1"
git push origin main
git push origin v1.0.1
```

## PATH during install

Installers ask interactively whether to add the launcher directory to your PATH:

- Linux: appends to `~/.bashrc` / `~/.zshrc` / fish config (only if you answer yes)
- Windows: updates the **user** PATH environment variable (only if you answer yes)

Non-interactive / CI:

```bash
bash installers/install.sh --yes
# or
MIRA_INSTALL_NONINTERACTIVE=1 bash installers/install.sh
```

```powershell
powershell -ExecutionPolicy Bypass -File .\installers\install.ps1 -Yes
```

## Development

```bash
export PYTHONPATH=src
python -m mira --version
python -m unittest discover -s tests -v
```

## License

MIT
