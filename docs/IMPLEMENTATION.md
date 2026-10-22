# awtserver implementation and acceptance checklist

This is the development coverage checklist, not a claim that a complete installer exists. Each milestone needs its own evidence. The working OMV host is excluded from automatic changes.

## A. Debian Stable VM bootstrap

- [x] Package profiles, read-only doctor and CLI plan
- [x] Root/VM/Debian-13 guarded package install; APT removals prohibited
- [x] Offline tests and Debian 13 APT package-resolution CI
- [x] Actual Debian 12/OMV **read-only CLI** compatibility: 11 Python syntax checks and 10/10 integration checks passed (no permanent installation)
- [x] Automated fake-curses traversal of **every** TUI menu leaf, keyboard Back/Quit/scroll, minimum screen and guarded external disk-tool launches
- [x] Unprivileged CI tests of actual temporary job-state, cron-file, and installer writes, rollback/refusal and unchanged real write guards
- [x] Interactive disk-browser launch protected from root invocation; mocked gdu/ncdu execution only in tests
- [ ] Actual Debian 12/OMV **host** unprivileged TUI-backend and temp-write suite (operator run pending)
- [ ] Actual interactive SSH/TTY screen rendering and navigation (human visual validation)
- [ ] Clean Debian 13 VM: full package installation, service startup and reboot
- [x] Explicit `docker-debian` alternative instead of ambiguous provider-independent Docker install
- [ ] **Implement and validate official Docker CE/Compose plugin** as the default parity path for the existing OMV host; repository signing, conflict checks, firewall and idempotent upgrade behavior
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
- [x] Local disk/mount/fullness monitoring and VM-gated local-MTA email submission code
- [ ] SMART alerting, email delivery, deduplicated scheduled notification, APC UPS shutdown and time sync tested
- [x] VM-only UUID-checked restic OS config snapshot (existing encrypted repository)
- [ ] USB automated backup timers, boot/EFI and full OS recovery, application databases, off-host backups and verified restores
- [x] VM-gated restore-to-empty root-private staging path implemented (no in-place restore)
- [ ] VM staging restore **runtime test**: prove encrypted repository recovery succeeds without touching running root
- [ ] 80% alert schedule, deduplication, clear/recovery notification, SMTP transport verification and test mail delivery
- [ ] Identify real NAS AIO schedule/settings, script owner and USB backup mount by sanitized read-only live probe
- [x] Dated October 22 OMV capability report: 7 jobs (3 active), 8 relevant timers, Docker CE, Borg/Timeshift/rsync, 1 unmounted USB disk
- [x] October 22 read-only job audit: three enabled custom jobs, two enabled rsync jobs, four disabled custom jobs; sanitized schedule inventory and overlap reviewer
- [ ] Verify backup and SnapRAID durations, mutual exclusion, weekly cron expansion and rsync destination integrity before activating migrated jobs
- [ ] Verify installed Borg/Timeshift and actual restore success; package presence does not establish backups
- [ ] All selected Docker services from the current OMV inventory, validated independently

## C. Scheduling, CLI and terminal UI

- [x] Declarative job schedules, enable/disable state and read-only preview
- [x] VM-only managed cron file generation, conflict guards and atomic synchronization
- [ ] Real cron execution on Debian 13 VM: user identity, enable/disable, reboot, missed runs, schedule overlap
- [ ] Job edits, locking, timeouts, logs, failed-job alerts and recovery
- [x] Read-only keyboard TUI with Storage/SnapRAID/Maintenance submenus and read-only gdu/ncdu launches
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
