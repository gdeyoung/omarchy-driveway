# Driveway

Every drive in one place — the old Mac volume menu, rebuilt for Omarchy.

One bar icon opens a tabbed panel:

- **Drives** — the OG dropdown: a pinned read-only System row (the disk behind
  `/`), thumb drives, external/internal disks, SD cards, discs, disk images,
  network shares and rclone cloud mounts, all in one searchable list. Click a
  drive to open it in the file manager (mounting it first if needed); open a
  terminal at it; eject or power it off. Unmounting is refused while apps hold
  files open — with their names, and a "close apps & retry" that never touches
  the shell itself. LUKS volumes unlock in a terminal (passphrases never pass
  through the shell). Pending rclone uploads warn before an unmount.
- **Cloud** — rclone remotes (Google Drive, OneDrive, Dropbox, Nextcloud, S3,
  anything rclone speaks) on supervised systemd user units: mount/unmount,
  health states (`Mounted`, `Starting…`, `Stopped`, `Failed · retrying`,
  `Mounted (no unit)`), usage bars, pending-upload counts. The restart loop
  rides out dead networks; each mount gets a private 0700 rc socket. Add
  remotes via `rclone config` in a floating terminal.
- **Network** — live SMB/NFS/sshfs/WebDAV mounts with open/terminal/unmount.
  Persistent share creation (encrypted credentials, boot mounts) lands in v0.2.

## Requirements

- Omarchy (Quickshell bar), `python3`, `udisks2` (standard).
- Cloud tab: `rclone` (`sudo pacman -S rclone`) — the panel says so if missing.

## Install

```
omarchy plugin add https://github.com/gdeyoung/omarchy-driveway.git --enable
```

## Keyboard

`1`/`2`/`3` switch tabs · `←`/`→` cycle tabs · `/` search · `Esc` clear search
then close · `r` refresh. Right-click the bar icon to refresh.

## What the plugin runs

Every external command, for the security reviewer:

| Command | Why |
|---|---|
| `python3` (`bin/driveway`, stdlib only) | list/status/actions backend |
| `lsblk`, `findmnt`, `udevadm monitor` | block/volume enumeration + live events |
| `udisksctl mount/unmount/lock/unlock/power-off/loop-delete` | local disk actions (no root) |
| `fusermount3 -u [-z]`, `gio mount -u` | FUSE / gvfs unmounts |
| `rclone listremotes --long` | read remotes (never writes rclone config) |
| `systemctl --user show/start/stop/daemon-reload` | `driveway-cloud@.service` lifecycle |
| HTTP POST on a private unix socket | rclone rc `vfs/stats` (upload activity) |
| `xdg-open`, `foot --working-directory` | open in file manager / terminal |
| `omarchy-launch-floating-terminal-with-presentation` | LUKS unlock + `rclone config` |
| `notify-send -a Driveway` | action outcomes |

No secrets are stored by the plugin: credentials live in rclone's own config;
LUKS passphrases are typed straight into udisksctl's terminal prompt.

## Settings (bar widget settings)

`pollIntervalSec` (10) · `showNetwork` (true) · `showUnmounted` (true) ·
`thumbMaxGb` (256) · `minUnmountedMb` (64) · `fullWarnPct` (90).

## Development

```
node --test tests/test_model.mjs   # Model.js (pure logic)
python3 tests/test_driveway.py     # backend smoke tests
```

Source: `~/work/omarchy-driveway` → installed hot-reload clone at
`~/.config/omarchy/plugins/gdeyoung.driveway`.

## Credits

Vendored (MIT) with thanks — see NOTICE.md for module-level provenance:
jgarza9788/drives (enumeration + disk actions), bmaltais/StartDrive
(systemd unit pattern), jonspinks/omarchy-rclone (supervision model),
TiniTinyTerminator/ODrive and sjmaquina/netdrives (planned v0.2 vendors).
