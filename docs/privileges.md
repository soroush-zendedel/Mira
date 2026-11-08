# Privileges and elevated operations

Mira runs as a normal user for almost everything:

- `mira update`, `mira check`, `mira status`, `mira config`
- `mira pypi set` with `--scope user` or `--scope project`
- Listing and dry-run of all providers

Only **system-level** configuration writes need elevation.

When a system write is required and the process is not already root,
Mira re-launches itself with `sudo` so the password prompt appears once
(`mira debian set`, `mira docker set`, `mira pacman set` / `reset`, and
`mira pypi set --scope system`). Dry-runs never elevate. On Windows, run
an elevated shell instead — automatic UAC elevation is not used.

## Docker Engine (`/etc/docker/daemon.json`)

| Platform | How to elevate |
|----------|----------------|
| Linux | `sudo mira docker set` |
| Linux (alternative) | `sudo -E mira docker set` if you need the same user env |
| Windows | Docker Engine on Windows Server / Docker Desktop config is different; current provider targets Linux daemon.json. Run PowerShell **as Administrator** only if you later extend Windows Docker Desktop support. |

After a successful `mira docker set`:

```bash
sudo systemctl restart docker
# or
sudo service docker restart
```

Mira **never** restarts Docker automatically. Confirm the change and restart yourself.

Dry-run first:

```bash
mira docker set --dry-run
sudo mira docker set
```

## Debian APT (`/etc/apt/sources.list.d/mira.sources`)

```bash
mira debian set --dry-run
sudo mira debian set
# optional metadata refresh (not done automatically):
sudo apt-get update
```

`set` backs up and disables the active `/etc/apt/sources.list` plus `.list` and
`.sources` files under `/etc/apt/sources.list.d/`, including third-party
sources, then writes Mira's Deb822 source with an explicit distro archive
`Signed-By` keyring. The disabled files remain beside the originals with a
`.mira-disabled` suffix. `mira debian reset` restores them; it refuses to
overwrite any original path that has been recreated. Keyring files are not
changed. Review the `set --dry-run` output before applying this system-wide
source switch.

## Arch Linux pacman (`/etc/pacman.d/mirrorlist`)

```bash
mira pacman set --dry-run
sudo mira pacman set
mira pacman -Syu
```

Persistent `set` backs up the current mirrorlist and adds a Mira-managed HTTPS
server block at the top; `reset` removes that block while preserving other
entries. `mira pacman -S...` uses a temporary copy of `/etc/pacman.conf` that
redirects its mirrorlist include for that invocation. It preserves pacman's
repository configuration and signature policy. Root privileges are still
required for package operations that write system files.

## PyPI

| Scope | Elevation |
|-------|-----------|
| `user` (default) | None |
| `project` (venv / cwd) | None |
| `system` | May need `sudo` on Linux |

```bash
mira pypi set --scope user
mira pypi set --scope project
sudo mira pypi set --scope system   # only if you really need system-wide pip
```

## Windows summary

- Install Mira **without** Administrator (user install under `%LOCALAPPDATA%\Programs\Mira`).
- Everyday commands: normal PowerShell or cmd.
- Only if a future Windows system-wide provider needs it: open **PowerShell as Administrator** and run the specific `mira ... set` command there. Do **not** run the whole daily workflow elevated.

## Safety rules (unchanged)

- Health checks never write system files.
- Backups are created before any write.
- Unrelated settings are preserved.
- Signature verification for APT is never disabled.
