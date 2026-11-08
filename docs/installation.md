# Installation

## Requirements

- Python 3.10+ for source, `.deb`, and Arch package installs
- Standalone binaries embed a Python runtime (no system Python required)

## Recommended: GitHub Release assets

See the [latest Release](https://github.com/soroush-zendedel/Mira/releases/latest).

| Platform | Asset |
|----------|--------|
| Windows | `mira-windows-x86_64.exe` |
| Linux | `mira-linux-x86_64` |
| Debian/Ubuntu | `mira_*_amd64.deb` |
| Arch Linux | `mira-*-any.pkg.tar.zst` |

Always verify with `SHA256SUMS` from the same release.

The Arch package is built by the Release workflow on an Arch Linux environment and attached to the GitHub Release.

## Installer scripts

```bash
# Linux — prefer release binary
bash installers/install.sh --from-release

# Linux — from local clone
bash installers/install.sh

# Windows — from local clone (no irm)
powershell -ExecutionPolicy Bypass -File .\installers\install.ps1

# Windows — download EXE from Releases
powershell -ExecutionPolicy Bypass -File .\installers\install.ps1 -FromRelease
```

## Upgrading Mira itself

| Install type | How to upgrade |
|--------------|----------------|
| User / source (`~/.local/share/mira`, installer scripts) | `mira upgrade` — fetches the new GitHub release **source** archive and replaces the package tree |
| Standalone binary | `mira upgrade` — replaces the binary from the release |
| Arch (pacman package) | `sudo pacman -Syu` or `sudo pacman -U mira-*-any.pkg.tar.zst` — **do not** use `mira upgrade` (it refuses to overwrite pacman-owned files) |
| Debian `.deb` | Reinstall a newer `.deb` with `dpkg -i` / `apt` |

`mira upgrade` intentionally leaves pacman-managed installs alone so it never bypasses package ownership.

## Uninstall

```bash
bash installers/uninstall.sh
# Windows:
# powershell -File .\installers\uninstall.ps1
```

User configuration and mirror databases are kept unless you remove them manually.
