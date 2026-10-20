# Debian restore manifest: service ownership and installation profiles

**Status:** migration planning, not an executable installer or a backup.
Derived from the October 20, 2026 live read-only audit and the user's
explicit priorities. No current OMV services have been changed.

## Day-one Debian profile (required)

| Area | Native Debian / Compose ownership | Prerequisites before enabling | Verification after restore |
|---|---|---|---|
| Base OS | Minimal stable Debian, UEFI, SSH and TTY | New OS SSD identified by stable hardware ID; other disks protected | Boot into correct root filesystem; local console and independent SSH connection |
| Networking | systemd-networkd or another **single** selected network manager, systemd-resolved, firewall | Verify NIC, static/reserved LAN IP, router, DNS bootstrap and Tailscale route plan | LAN and Tailscale login, package mirrors, Pi-hole DNS and external lookup |
| Host SSH | openssh-server | Preserve authorized public keys privately; design hardened policy with recovery console | Two independent key-based logins before closing password/root paths |
| Intrusion blocking | fail2ban, SSH and FTP jails | Examine actual OMV-generated jail/filter/backends and log locations | `fail2ban-client status`; confirm matching filters and firewall actions |
| FTP | ProFTPD | Preserve accounts, virtual directories, passive port policy, TLS and permissions | Authenticated transfer over intended LAN/Tailscale network |
| Storage | ext4 UUID mounts, mergerfs and systemd mount ordering | Verify physical disks and UUIDs; preserve all array metadata, parity, content and data | `findmnt`, read-only path and ownership checks, existing mergerfs branch mapping |
| Parity | SnapRAID and AIO v3.4 or reviewed successor | Existing parity/content files, exclusion list, safety thresholds, pause list | `snapraid status` read-only, `snapraid diff`; avoid an unreviewed forced sync |
| Docker | Docker Engine, Compose plugin and Dockge | Restore *verified* Compose files, secrets, bind mounts, named volumes, permissions and source-path identity | App health, port bindings, data access and complete VPN network namespace group |
| DNS | Existing Pi-hole Docker stack, Quad9 upstream and DNS guard | Keep alternate resolver during bootstrap to prevent DNS dependency cycle | LAN and Tailscale DNS, profile isolation, persistence through container recreation |
| Private connectivity | Host Tailscale daemon and app-specific sidecars | Preserve Tailscale auth/access strategy without publishing credentials | Host and per-app access plus Gluetun fail-closed checks |
| Application updates | Maintained Watchtower fork and independent 05:00 verifier | Preserve 02:45 schedule, allowlist and root-private SMTP data | Dry verification and next scheduled run, no app recreation in initial validation |
| App support | `pihm-web`, Docker engine upgrade recovery, cert renewal | Confirm source files and installed systemd units | Read-only functional checks and correct timer triggers |
| Health/UPS | smartmontools/smartd, `apcupsd`, Postfix or reviewed mail sender | Preserve UPS shutdown thresholds, SMART by-id paths, email credentials privately | UPS state and non-destructive email test without triggering shutdown |
| Scheduling/backups | systemd timers/cron or direct native replacements | Audit 7 OMV scheduled jobs (3 enabled), 2 enabled OMV rsync tasks, Compose backups, and data backup coverage | Compare actual schedule, latest results and verified restore of sample data |
| Account permissions | Native users/groups with intentional UIDs/GIDs | Preserve ownership across mounted ext4 disks and volume directories | Read/write tests under expected application/service users |

## Optional profile: SMB file sharing

The user **rarely uses Samba** but wants to keep the option. Do not
install or start Samba/WSDD as part of the mandatory new Debian profile.
Preserve the current single-share definition, permitted-user mappings,
passwords (privately, with appropriate permissions), and access policy in
backups. An optional scripted feature can later install/enable
`samba`/`smbd` and `wsdd-server` **only on explicit opt-in**.

Critically, the mergerfs mount and storage files remain part of the
**required** profile whether SMB is enabled or not.

## Deliberately omitted from new Debian

- OMV packages, OMV UI/engine, OMV-specific Nginx/PHP services and
  `omv-webgui` Fail2ban jail.
- NetBird client/service: user confirms no usage or future intention.
- Podman runtime/socket/restart and auto-update timer: user confirms no
  usage; native audit returned **zero Podman containers**.

Do **not** uninstall these from the existing functioning OMV system
during inventory. Their omission applies only to the rebuilt OS.

## Pending review before package list and installer can be finalized

- Determine purpose of currently active ClamAV, Avahi/mDNS, collectd,
  Chrony, rsyslog, ProFTPD TLS/passive ranges, RPC bind and current
  auxiliary PHP/Nginx use. Keep if another host workflow requires them.
- Verify whether BorgBackup, Timeshift, OMV USB-backup, OMV Compose
  backup, or OMV rsync actually protect data and the OS disk; do not
  remove until a replacement verified backup/restore path exists.
- Run [jobs_audit.py](jobs_audit.py) to classify OMV's enabled cron and
  rsync jobs without sharing job commands, credentials or target paths.
  Audit real schedules and destinations **privately** before migrating.
- Verify the separate, currently unmounted ~64 GB USB block device's
  intended purpose. Do not automatically repartition, mount or erase it.
- Reconstruct OMV-generated configurations using supported native
  services and tested files. Do not copy `/etc/openmediavault/config.xml`
  into the new Debian environment expecting it to configure services.
- Preserve Compose `compose.freshdock.yml` source overlays until they
  are explicitly removed under a separate tested change; watchtower
  does not rely on their historical labels.
- Determine which services should be installed on the new OS SSD, which
  data stays on the existing ext4 disks, and which secrets require
  separate encrypted backups.

## Dependency-safe installation stages (future implementation)

1. **Preflight only:** Verify known host topology, expected data drive
   signatures, intended new OS SSD, backup completeness and rollback.
   Default to no disk writes.
2. **Fresh OS:** Install Debian *only on verified new OS SSD*, ideally
   with old OS SSD and data/parity drives isolated for partitioning.
3. **Remote access:** Restore key-based SSH, host network, Tailscale,
   time sync, DNS bootstrap and carefully staged firewall/Fail2ban.
4. **Storage:** Attach/mount existing ext4 disks by verified UUID, create
   mergerfs mount, validate branch ownership and SnapRAID configuration.
   **Do not initialize parity or format array disks.**
5. **Applications:** Restore Docker engine and persistent data; import
   Compose stacks in dependency order, preserving Gluetun and Pi-hole.
6. **Reliability:** Restore UPS/SMART/mail, schedules, backups,
   Watchtower verification and Docker recovery services.
7. **Accept:** Test remote/TTY recovery, FTP transfers, container
   functionality, Pi-hole LAN/Tailscale DNS, array status and validated
   backup restoration. Keep original OS SSD as a fallback.

No actual install/restore script should be published as production-ready
until live config sources and backup recovery have been validated.
