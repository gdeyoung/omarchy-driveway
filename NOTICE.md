# Vendored code provenance (gdeyoung.driveway)

House policy: vendor community code into fleet-canonical copies, never
symlink or depend on upstream; record source + commit + date; verify every
command against the live CLI before shipping. All sources are MIT.

| Module | Source | Commit | Date | What was taken |
|---|---|---|---|---|
| `lib/driveway/lister.py` | github.com/jgarza9788/drives | `255609e` | 2026-10-17 | Near-whole `bin/drives-list`: lsblk/findmnt/sysfs/gvfs enumeration, bounded statvfs children, rclone rc pending logic, kind classification. Driveway changes: `collect()` refactor, System row, internal ESP filter, unix-socket rc endpoints. |
| `lib/driveway/actions.py` | github.com/jgarza9788/drives | `255609e` | 2026-10-17 | Near-whole `bin/drives-action`: udisks mount/unlock/lock, eject chains (udisks/loop/fuse/gio), busy-process finder with pidfd-safe terminate. Driveway changes: HANDLERS export, notify app name. |
| `Model.js` | github.com/jgarza9788/drives | `255609e` | 2026-10-17 | icons/kind tables, humanBytes, usageText, infoRows, sameDrives. Driveway additions: system kind, cloud state labels, filterDrives, barState. |
| `DriveRow.qml` (layout ideas) | github.com/jgarza9788/drives | `255609e` | 2026-10-17 | Card information architecture (usage bar, badges, busy/kill flow). |
| `systemd/driveway-cloud@.service` | github.com/bmaltais/StartDrive | `2760a4d` | 2026-10-17 | Unit pattern: RCLONE_* env defaults + per-drive EnvironmentFile override, 0700 RuntimeDirectory rc socket, fusermount3/sandbox notes. |
| Supervision model (no user network-online, infinite restart) | github.com/jonspinks/omarchy-rclone | `2a3a9fc` | 2026-10-17 | Design: restart loop as network gate, StartLimitIntervalSec=0, per-instance rc socket. |
| Tab pattern, Panel/Service split | gdeyoung.tailfin (house, MIT) | local | 2026-10-17 | TabButton component, tab switching, PanelKeyCatcher wiring, IPC verbs. |

## Planned v0.2 vendors (not yet included)

- Account lifecycle (OAuth in-widget, rc-channel secrets):
  github.com/TiniTinyTerminator/ODrive `c17c421` — `lib/odrive/rclone_rc.py`,
  `providers.py`, `bounded.py` wholesale.
- Fault classifier (13-state, auth latch, one-remedy buttons):
  github.com/jonspinks/omarchy-rclone `scripts/rclone-status`.
- SMB/NFS persistence (systemd units, LoadCredentialEncrypted):
  github.com/sjmaquina/netdrives `459e156`.
