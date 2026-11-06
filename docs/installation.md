# Installation

## Requirements

- Python 3.10+ for source and `.deb` installs
- Standalone binaries embed a Python runtime (no system Python required)

## Recommended: GitHub Release assets

See the [latest Release](https://github.com/soroush-zendedel/Mira/releases/latest).

| Platform | Asset |
|----------|--------|
| Windows | `mira-windows-x86_64.exe` |
| Linux | `mira-linux-x86_64` |
| Debian/Ubuntu | `mira_*_amd64.deb` |

Always verify with `SHA256SUMS` from the same release.

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

## Uninstall

```bash
bash installers/uninstall.sh
# Windows:
# powershell -File .\installers\uninstall.ps1
```

User configuration and mirror databases are kept unless you remove them manually.
