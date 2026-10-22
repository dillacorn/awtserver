# OMV capability snapshot | 2026-10-22

**Source:** User-supplied output from `migration/debian/feature_probe.py` executed read-only as root on the active OpenMediaVault server. This is a dated observation, **not** a usable backup, a fresh Debian VM test or authorization to modify the host. No private IPs, commands, filesystem identifiers, usernames or credentials are retained here.

## Confirmed

| Area | Observed | awtserver consequence |
| --- | --- | --- |
| OS | Debian 12 with OMV present | No production adoption or uninstall; Debian 13 only on disposable VMs |
| Docker | `docker-ce` installed; `docker.io` not installed; Docker daemon active | Respect existing **official Docker package provider**. Current prototype `docker` profile is Debian packages and is not equivalent |
| OMV custom cron | Seven definitions; three enabled | Preserve enabled/disabled distinction, original timing and mail settings before translating to managed jobs |
| System cron | 16 cron.d files, 15 daily, 3 weekly, 2 monthly | Inspect job ownership and deduplicate before introducing competing schedulers |
| Relevant timers | anacron, APT daily/update, certbot, dpkg-db-backup, OMV Docker upgrade recovery, Pi-hole/Tailscale DNS guard, Watchtower fork verification | Preserve service-specific timers and their behavior; **do not move them into generic cron blindly** |
| Backup tooling | `borgbackup`, `timeshift`, `rsync` installed; `restic` absent | Inspect **active configuration and restoreability** before selecting Borg/Timeshift/Restic, or assuming any installed tool runs |
| Removable media | One USB disk detected, unmounted | Identity, filesystem, capacity, intended use and independent backup integrity **unknown**. No automatic mount/format/backup |
| Storage | `snapraid`, `mergerfs`, OMV SnapRAID plugin installed | Existing parity and mount configurations take priority over templates |
| AIO probe | No script at the probe's three conventional paths | **Inconclusive**: may be elsewhere or run as a differently named file |
| System health | apcupsd, smartd/smartmontools, Postfix, fail2ban active | Preserve UPS power policy, SMART by-id tests and working mail transport; delivery not yet independently tested |
| Sharing | ProFTPD and Samba active | Preserve FTP/SSH access. Samba remains optional for future Debian installations |
| Access | SSH, host Tailscale, pihm-web active | Preserve remote administration and DNS access when adopting native configuration |
| Available disk tools | gdu, ncdu, duf, btop packages absent | Optional UI tools, not required for the base system |
| Other installed packages | ClamAV, unattended-upgrades present | Existence alone does not establish scheduled scan health or package-update success |

## Important distinctions

- `docker-ce` is a confirmed installed package, not proof of exact Compose plugin version, package repository key or complete service sources.
- Installed BorgBackup/Timeshift packages do **not** prove existing backups; distinguish configured jobs, successful snapshots and verified test restores.
- The unmounted USB could be a separate purpose. **Do not assume it is the intended recovery disk** or that it matches the earlier unmounted block device.
- SMART services may expose aliases; both showing active does not necessarily mean two independent monitoring daemons.
- The old OMV scheduled-task database contains both enabled and disabled records. Its CLI may rely on privileged wrappers, special timing syntaxes and root-user execution. Existing prototype non-root job records must not silently replace them.
- Systemd timer/cron time zones, random delays, backup locks, retry policies and failure alert routing must be preserved in native implementations.
- No file paths, partition identifiers, real Docker container identities, secrets or production schedules are assumed from repo examples.

## Next read-only evidence

Use existing `migration/debian/jobs_audit.py` for sanitized OMV job schedules, labels and rsync policy flags. Use a **separate bounded discovery** to find only the category of AIO installation, how Borg/Timeshift/USB backup is scheduled, and Docker package-provider metadata. Do not export raw job command strings or private backup destination paths. Confirm backup/restore status with private checks before changing anything.

See [implementation gates](../../docs/IMPLEMENTATION.md), [prior host evidence](host-findings-2026-10-20.md) and [restore requirements](restore-manifest.md).
