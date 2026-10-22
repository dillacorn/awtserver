# awtserver implementation and acceptance checklist

This is the development coverage checklist, not a claim that a complete installer exists. Each milestone needs its own evidence. The working OMV host is excluded from automatic changes.

## A. Debian Stable VM bootstrap

- [x] Package profiles, read-only doctor and CLI plan
- [x] Root/VM/Debian-13 guarded package install; APT removals prohibited
- [x] Offline tests and Debian 13 APT package-resolution CI
- [ ] Clean Debian 13 VM: full package installation, service startup and reboot
- [ ] Docker provider policy: Debian packages versus Docker official APT repository, Compose v2, containerd and firewall interactions
- [ ] Repeat install, update, interruption, failed dependency and rollback tests
- [ ] Installer distribution/update/uninstall commands with pinned sources and version tracking

## B. Native services and application parity

- [ ] SSH keys, LAN/Tailscale recovery, Fail2ban and firewall ordering
- [ ] DNS bootstrap with alternate resolver, Pi-hole integration, stable networking and Tailscale connectivity
- [x] Read-only lsblk/findmnt device + mergerfs views and statvfs 80% capacity threshold
- [ ] Disk UUID/by-id mount editing, ext4/mergerfs configuration, ACLs, ownership and mount ordering
- [x] VM-only reviewed AIO v3.4 script checksum staging, root-cron preview and separate enable/disable
- [ ] SnapRAID parity/data/content validation, AIO scheduling and thresholds actually tested on disposable disks
- [ ] Docker Compose project creation, configuration/secrets, bind mounts, named volumes, sidecars and VPN namespace dependencies
- [ ] FTP/ProFTPD with TLS, user directories and passive ports; opt-in Samba/WSDD share profile
- [ ] SMART monitoring, email alerts, APC UPS shutdown, time sync and service recovery
- [ ] Consistent database/application backups, off-host backups and verified restores
- [ ] All selected Docker services from the current OMV inventory, validated independently

## C. Scheduling, CLI and terminal UI

- [x] Declarative job schedules, enable/disable state and read-only preview
- [x] VM-only managed cron file generation, conflict guards and atomic synchronization
- [ ] Real cron execution on Debian 13 VM: user identity, enable/disable, reboot, missed runs, schedule overlap
- [ ] Job edits, locking, timeouts, logs, failed-job alerts and recovery
- [x] Read-only keyboard TUI using the same backend as CLI
- [x] Executable launcher dispatches CLI, compact TUI and offline categorized guides; VM-only first-install command
- [ ] Command updater/uninstaller with version detection, safe replacement, explicit rollback and tested ownership
- [ ] Interactive profile choices, job configuration/toggles, previews, confirmation and transactions
- [ ] SSH/TTY visual and input validation: resize, minimal size, keyboard handling, unsupported terminal, interrupted session

## D. End-to-end verification and conversion

- [ ] Repeatable full VM bootstrap with simulated disks, Docker workloads, backup restore and functional acceptance
- [ ] Distinguish package installed, service enabled, service active and service working
- [ ] Sanitized inventory/export manifest, private secrets and disaster recovery checklist
- [ ] Dry-run in-place OMV adoption on a clone, with package dependency simulation and rollback
- [ ] Preserve known-good access, mounts and backups before retiring individual OMV components
- [ ] Never disable/purge OMV on the real NAS until dependency and recovery checks have passed

## Invariants

- Default read-only. Every mutation has a narrow target, preflight and explicit apply.
- No automatic disk reformat, parity initialization, data/volume deletion, unreviewed network or DNS changes, or blanket OMV package purge.
- No credentials or private inventories in public Git, CI output or development logs.
- A VM cannot prove hardware UPS shutdown, production disk identity, VPN connectivity or actual restore quality.
- The TUI is optional. Equivalent CLI actions and noninteractive commands remain available.

References: [OMV 7 features](https://docs.openmediavault.org/en/7.x/features.html), [Debian cron](https://manpages.debian.org/trixie/cron/crontab.5.en.html), [Debian policy](https://www.debian.org/doc/debian-policy/ch-opersys.html), [Docker on Debian](https://docs.docker.com/engine/install/debian/), [migration requirements](../migration/debian/restore-manifest.md).

Only check a box after supporting evidence exists.
