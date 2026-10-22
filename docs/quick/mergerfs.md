# mergerfs | Pool tools

Quick checks: `awtserver storage pools` and `awtserver storage usage`. For the underlying mount options, use `findmnt -t fuse.mergerfs`.

- `duf` shows filesystem space; `gdu` and `ncdu` browse directory sizes.
- The TUI starts **gdu with deletion and shell disabled**, or **ncdu -rr** (read-only). Scanning large disks takes time; exit when finished.
- [mergerfs-tools](https://github.com/trapexit/mergerfs-tools) includes `mergerfs.ctl` for pool inspection, `mergerfs.balance` for moving files, and duplicate tools.
- **Never run balancing, deduplication, branch removal or a mount edit automatically.** Such tools can move or delete data. Verify source mounts, backup and SnapRAID sync state first.

No reliable standalone mergerfs TUI is assumed; awtserver presents safe inspections directly. [Upstream tooling](https://trapexit.github.io/mergerfs/latest/tooling/).
