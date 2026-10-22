# OMV feature parity map for awtserver

**Scope:** Reproduce the capabilities actually used, using vanilla Debian components. OpenMediaVault's UI and configuration database are not part of awtserver. A package being installable does **not** mean a complete usable service has been provisioned.

| OMV capability | Native Debian / awtserver target | Prototype status |
| --- | --- | --- |
| Host management and updates | APT, unattended-upgrades, SSH, service status | Read-only doctor and basic package plans |
| Storage disks and filesystems | Stable UUID mounts, ext4, systemd ordering, permissions | Package planning only; no mount writes |
| SnapRAID / mergerfs | Native packages, existing parity/content metadata and pool branches | Package planning only; no array initialization |
| Docker and app management | Compose, Dockge optional; preserve stacks, binds, networks and data | Debian Docker packages opt-in; no app installation |
| FTP | ProFTPD, accounts, TLS, passive ports, Fail2ban jail | Package planning only |
| SMB/NFS sharing | Samba optional; NFS only when explicitly needed | Samba package opt-in; no share writes |
| DNS / remote connectivity | Pi-hole, Quad9, Gluetun, host/sidecar Tailscale | Existing service documentation only |
| Monitoring | smartmontools, SMART tests, email alerts, syslog | Package planning only |
| Power protection | apcupsd configuration and verified shutdown thresholds | Package planning only; no UPS policy |
| Jobs and maintenance | Cron or reviewed systemd timers, user scripts, alerts | Declarative schedules and VM-only managed cron synchronization; no production deployment |
| Users / groups and ACLs | Native user/group tools, ownership, POSIX ACLs | Not implemented |
| Notifications | SMTP/other explicitly configured sender, failures and thresholds | Not implemented |
| Backups and recovery | rsync/Borg where justified, tested application restores | rsync package planning; no backups performed |
| Optional legacy features | ClamAV, Avahi, Chrony, collectd as justified by actual dependencies | Pending inspection |
| OMV GUI/plugins | Not part of the Debian deployment | No purge or disable actions |

See the [categorized quick guides](quick/remote-tailscale.md) and [implementation and validation checklist](IMPLEMENTATION.md) for acceptance gates, the in-place OMV adoption plan and unresolved feature coverage.

## Design rules

- **Fresh install first:** Start in a fresh Debian Stable VM, package and service dependencies separated into small profiles.
- **No forced bundle:** Storage and Docker management are independent. Samba, FTP, UPS, cron, and application stacks must be selectable.
- **Apply after inspection:** Keep planning read-only; visible, explicit, guarded writes only. Never reformat disks, import OMV XML as configuration, or recreate existing Compose networks implicitly.
- **Existing host later:** An in-place migration from OMV is a separate, higher-risk adoption mode requiring live evidence and verified backups. It must not be enabled by a VM bootstrap flag.
- **Shared CLI/TUI backend:** Interactive key navigation (inspired by smtty) must invoke the same validated operations as the CLI, with no hidden mutations.
- **Scheduled job controls:** Eventually permit create/edit/delete/toggle, with preview and cron expression validation, managed-file ownership, known execution identity, locking, logs, and failure reporting before activation.
- **Security:** Never include secrets, raw private host inventory, disks UUIDs, current auth settings or other identifying infrastructure in public Git.

## Research references

- [OMV core feature inventory](https://www.openmediavault.org/?page_id=1562)
- [OMV 7 service and administration documentation](https://docs.openmediavault.org/en/7.x/features.html)
- [Debian SnapRAID package](https://packages.debian.org/trixie/snapraid)
- [Debian mergerfs package](https://packages.debian.org/trixie/mergerfs)
- [Debian Compose package](https://packages.debian.org/trixie/docker-compose)
- [Docker's official Debian installation documentation](https://docs.docker.com/engine/install/debian/)

See also the [host-derived restore requirements](../migration/debian/restore-manifest.md) and [historical migration operations](../migration/debian/OPERATIONS.md). Neither file proves present server state.
