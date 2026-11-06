# Release & versioning guide

This folder contains helper scripts for **Semantic Versioning** and for preparing a GitHub Release.  
Actual binaries (Windows `.exe`, Linux binary, Debian `.deb`) are built by **GitHub Actions** when you push a version tag.

---

## Versioning rules (SemVer)

Mira uses [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`

| Change type | Example | When to bump |
|-------------|---------|----------------|
| Patch | `1.0.0` → `1.0.1` | Bug fixes only |
| Minor | `1.0.1` → `1.1.0` | New features, backward compatible |
| Major | `1.1.0` → `2.0.0` | Breaking changes |

### Single source of truth

| Location | Role |
|----------|------|
| `VERSION` (repo root) | Canonical version string |
| `src/mira/__init__.py` → `__version__` | Runtime (`mira --version`) |
| `src/mira/constants.py` → `APP_VERSION` | Internal constant |
| `pyproject.toml` → `version` | Packaging metadata |
| Git tag `vX.Y.Z` | Triggers the Release workflow |

Always change the version with the helper scripts below so all of these stay in sync.

---

## Automated GitHub Releases

Workflow file: `.github/workflows/release.yml`

### What triggers a build?

A **git tag** matching `v*`, for example:

```text
v1.0.0
v1.2.3
v2.0.0-rc.1
```

Pushing commits to `main` alone does **not** publish a Release.

### What gets published?

| Asset | Description |
|-------|-------------|
| `mira-windows-x86_64.exe` | Standalone Windows binary (PyInstaller) |
| `mira-linux-x86_64` | Standalone Linux binary (PyInstaller) |
| `mira_<ver>_amd64.deb` | Debian / Ubuntu package |
| `mira-<ver>-source.zip` | Source archive |
| `SHA256SUMS` | Checksums for verification |

### Repository settings (one-time)

In the GitHub repository:

1. **Settings → Actions → General**
2. Enable Actions (allow workflows).
3. **Workflow permissions**: set **Read and write permissions** so the workflow can create the Release and upload assets.

---

## Publish a release

### 1) Bump version (sync all version fields)

**Linux / macOS**

```bash
bash scripts/make_release_tag.sh 1.0.1
```

**Windows (PowerShell)**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\make_release_tag.ps1 1.0.1
```

### 2) Commit, tag, and push

**Linux / macOS**

```bash
git add -A
git commit -m "Release v1.0.1"
git tag -a v1.0.1 -m "Mira v1.0.1"
git push origin main
git push origin v1.0.1
```

**Windows (PowerShell)**

```powershell
git add -A
git commit -m "Release v1.0.1"
git tag -a v1.0.1 -m "Mira v1.0.1"
git push origin main
git push origin v1.0.1
```

### 3) Wait for Actions

1. Open the repository on GitHub → **Actions**.
2. Open the **Release** workflow run for your tag.
3. When it finishes (green), open **Releases** and download the assets.

---

## Scripts in this folder

| Script | Platform | Purpose |
|--------|----------|---------|
| `make_release_tag.sh` | Linux / macOS | Write `VERSION`, sync metadata, print git commands |
| `make_release_tag.ps1` | Windows | Same as above |
| `build_standalone.sh` | Linux / macOS | Optional local binary via PyInstaller |
| `build_standalone.ps1` | Windows | Optional local `mira.exe` via PyInstaller |
| `build_deb.sh` | Linux (or WSL) | Optional local `.deb` (needs `dpkg-deb`) |
| `build_deb.ps1` | Windows | Explains that `.deb` is built on Linux / CI |

### Local builds (optional)

You do **not** need these for a normal GitHub Release. CI builds everything.

**Windows EXE locally**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_standalone.ps1
# Output: dist\mira.exe
```

**Linux binary locally**

```bash
bash scripts/build_standalone.sh
# Output: dist/mira
```

**Debian package locally**

```bash
bash scripts/build_deb.sh 1.0.1
# Output: packaging/out/mira_1.0.1_amd64.deb
```

On Windows, use WSL if you really need a local `.deb`:

```powershell
wsl bash scripts/build_deb.sh 1.0.1
```

---

## End-user install from a Release

After assets exist on the Releases page:

**Windows**

- Download `mira-windows-x86_64.exe`, rename to `mira.exe`, put it on `PATH`  
  **or** run `installers\install.ps1 -FromRelease`

**Linux**

```bash
curl -fsSL -o mira https://github.com/soroush-zendedel/Mira/releases/latest/download/mira-linux-x86_64
chmod +x mira
mv mira ~/.local/bin/mira
```

**Debian / Ubuntu**

```bash
curl -fsSL -O https://github.com/soroush-zendedel/Mira/releases/latest/download/mira_1.0.1_amd64.deb
sudo dpkg -i mira_*_amd64.deb
```

Verify downloads with `SHA256SUMS` from the same release.

---

## Troubleshooting

| Problem | What to check |
|---------|----------------|
| No Release after push | Did you push the **tag** (`git push origin v1.0.1`)? |
| Actions tab empty / blocked | Enable Actions and write permissions in repo Settings |
| Tag name rejected by workflow | Tag must start with `v` (e.g. `v1.0.0`) |
| Workflow failed | Open the failed job log under **Actions** |
| Version mismatch | Always use `make_release_tag` so `VERSION` and package files stay aligned |

---

## Related files

- `.github/workflows/release.yml` — build & publish pipeline  
- `.github/workflows/ci.yml` — tests on push / pull request  
- `installers/install.sh` / `installers/install.ps1` — user installers (source or release binary)  
- Root `README.md` — project overview and install instructions

---

## Line endings (Windows)

The repository includes a root `.gitattributes` file that forces **LF** in Git for source files. That stops warnings like:

```text
warning: LF will be replaced by CRLF the next time Git touches it
```

After pulling this change on Windows, refresh the index once if warnings persist:

```powershell
git add --renormalize .
git status
```

---

## Uninstall

**Windows**

```powershell
powershell -ExecutionPolicy Bypass -File .\installers\uninstall.ps1
# also delete config/cache/database:
powershell -ExecutionPolicy Bypass -File .\installers\uninstall.ps1 -PurgeData
```

**Linux / macOS**

```bash
bash installers/uninstall.sh
bash installers/uninstall.sh --purge-data
```

These remove application files and clean PATH entries added by the installer / `mira` path helper.
