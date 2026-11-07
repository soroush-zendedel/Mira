# Mira

**Universal Software Repository Mirror Manager**

One CLI. Multiple ecosystems. Intelligent repository mirror management.

Mira discovers, evaluates, selects, and configures software repository mirrors for:

- **PyPI** (pip)
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
mira config set countries ir,de
```

### Docker / APT (need elevation)

```bash
mira docker set --dry-run
sudo mira docker set
sudo systemctl restart docker   # Mira does not restart Docker for you

mira debian set --dry-run
sudo mira debian set
```

See [docs/privileges.md](docs/privileges.md).

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
