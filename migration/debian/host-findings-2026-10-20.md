# Headless Debian: observed host dependencies (October 20, 2026)

**Source:** user's private, live read-only OMV inventory review.
**Scope:** documentation of categories and software only. Do not commit private
inventory JSON, hostname-specific IPs, disk serials, filesystem UUIDs, user
identities, secret-bearing config files, actual SSH security settings or
full Docker Compose paths to this public repository.

**No server changes were made** by the inventory.

## User-confirmed future service choices

- **Keep:** SSH/TTY, FTP/ProFTPD and matching Fail2ban jails, Docker Compose,
  existing storage/backup/UPS/SMART/DNS/network dependencies.
- **Optional:** Samba/SMB (and WSDD for Windows share discovery). Preserve
  share configuration privately; install or enable only on user request after
  Debian cutover. User reports rarely using SMB.
- **Omit:** NetBird, Podman, Podman auto-update/restart timer units.
- **Current OMV host:** do not stop, remove or modify any of the above during
  discovery.

## Confirmed running services to preserve or deliberately replace

- Debian 12 Bookworm, UEFI boot. Future target is stable minimal Debian
  with SSH/TTY and no OMV service dependency.
- Docker: 55 *running* containers in 55 individually identifiable Compose
  services/projects, plus 12 named Docker volumes (some may belong to
  previously deployed stacks; usage not established). All inspected containers
  reported Compose project, service and configuration provenance.
- Host services observed active: OpenSSH, Fail2ban, Docker, cron, Samba,
  `apcupsd`, host `tailscaled`, `pihm-web`, unattended upgrades.
- Fail2ban currently has jails for SSH, FTP and OMV's web UI. Native Debian
  retains a verified SSH jail; OMV UI jail must be retired when OMV is gone;
  FTP jail only if FTP itself is retired after confirming use.
- One Samba share consumes the mergerfs data directory. No active NFS exports
  were reported. User rarely uses SMB and explicitly wants it **optional** on
  future Debian, not a mandatory running service. Preserve the share's private
  configuration and identity/ownership data for opt-in restoration only.
- Four 8 TB ext4 array disks (three SnapRAID data + one parity) and an
  independent 240 GB SSD OS disk were observed. A separate approximately
  64 GB block device has a filesystem but was *not mounted*; establish its
  purpose before any new OS installation.
- SnapRAID reports no pending/incomplete sync in this captured inventory,
  following the user's successful prehashed sync and scrub.
- The second live read-only audit **confirmed mergerfs mounted** at the
  Samba data-share target and its parent, with the systemd mount unit active
  and enabled. The initial blank listing was an inventory traversal limitation.
- Host UPS identifies an APC Back-UPS model with online status. Preserve
  shutdown thresholds and daemon configuration independently of OMV.
- Tailscale host daemon is running, alongside numerous application Tailscale
  sidecars. Preserve host and container-level network/identity distinctions.

## Enabled services whose *purpose and runtime usage* require verification

- ClamAV (`clamav-daemon`, `clamav-freshclam`)
- Chrony, Avahi/mDNS, collectd
- NetBird daemon active, Podman unit/timer configured but **zero Podman
  containers** discovered. User explicitly does not use either: omit both
  from the replacement Debian OS; do not modify current OMV.
- Postfix for mail/alerts
- ProFTPD and associated Fail2ban jail: **retain** on future Debian; user
  confirms FTP is one of the two primary access methods (alongside SSH).
- RPC bind, wsdd-server
- NVIDIA CDI refresh (GPU-dependent applications may need equivalent support)
- systemd-networkd and systemd-resolved: critical for the network bootstrap
- smartmontools/smartd and SMART mail monitoring: the inventory summary
  probed the `smartd` name, which is insufficient to establish whether
  `smartmontools.service` or an alias performs actual monitoring
- `netfilter-persistent`: existing firewall includes Docker-managed chains;
  do NOT naively restore every iptables rule from the old OS
- OMV-specific nginx, PHP-FPM, management services and web Fail2ban jail:
  candidate removals after migration, not before
- Various installed OMV plugins for backup, ClamAV, FTP, filebrowser,
  SnapRAID, mergerfs, Timeshift and USB backup; installation does not
  establish actual use. BorgBackup is installed as well.

## Security / access migration gate (private evidence only)

The private report reveals an SSH authentication baseline that requires
an explicit reviewed hardening plan. Do not mirror current potentially
unsafe settings into public repo examples or change live SSH settings
mid-discovery.

New Debian must start with **verified LAN and Tailscale key-based SSH
access**, plus an accessible local TTY before changing the login policy.
Test new settings using a second concurrent connection; retain console
recovery. Reconcile Fail2ban jail names, firewall backend, log source,
Tailscale interface policies, forwarded service ports and Docker rules.

## Filesystems / snapshot / backup migration gate

- Recreate ext4 mounts by **exact UUID checked at cutover**, never by
  volatile `/dev/sdX`; identify OS SSD by model/serial before installation.
- Preserve existing SnapRAID content and parity files. Do not initialize,
  reformat, resync or modify disk identifiers as part of discovery.
- Mergerfs is verified active. Preserve the mergerfs branch sources,
  mount ordering and dependent Docker/FTP paths. Samba is optional and
  must not dictate whether mergerfs itself is mounted.
- Check the currently unmounted device's purpose before selecting a new
  installation target. Existing data/parity drives must not be included in
  a scripted destructive installer.
- Inventory is **not** a backup. Existing backups, backup jobs and restore
  procedures must be independently verified, including OMV-managed tasks
  and application databases.

## Docker / application migration gate

- Compose service provenance is present for all 55 running containers, but
  source files, env secrets, bind-mount data, Docker volumes and actual
  application backups are not captured by the inventory tool.
- Twelve named volumes exist; **do not prune** volumes that appear orphaned
  until backup/recovery use has been checked.
- Multiple service stacks still refer to `compose.freshdock.yml` overlays
  even though the Freshdock daemon has been retired. Preserve each original
  Compose source path until a separate validated label/overlay cleanup.
- Preserve Pi-hole DNS and upstream resolver access for LAN and Tailscale;
  avoid circular DNS dependencies during host bootstrap.
- Preserve VPN isolation group including Gluetun, Transmission and Mullvad
  Browser. Do not split/recreate a network namespace group accidentally.
- Preserve host `pihm-web`, Watchtower's independent verification timer,
  Tailscale/DNS guard, Docker upgrade recovery service and certificate
  renewal jobs after auditing their actual source paths.

## Follow-up evidence needed (read only)

1. Inspect *live* mergerfs target and backing filesystem type, root/network
   mount units, and whether the unmounted ~64 GB device is backup/recovery.
2. Latest live probe confirmed active ProFTPD, ClamAV, collectd, SMART, mail,
   Chrony, nginx/PHP and NetBird, with zero Podman containers. Confirm whether
   optional active utilities have dependencies on Docker/FTP; omit NetBird and
   Podman in the future OS by explicit user choice.
3. Inventory actual OMV plugin settings and scheduled jobs separately from
   systemd timers and root crontab: a zero root cron count does not mean
   there are no automated tasks.
4. Trace fail2ban jail configuration origin, SSH policy, login methods and
   persistent firewall rule ownership in a *private* review. Do not publish
   allowlists, credentials or authentication details in this repository.
5. Identify verified off-OS-SSD backups and test a restore before authoring
   installation/restore automation.

**Status:** first private inventory reviewed. Migration scripting awaits
these dependency and backup gates. No live server changes authorized.

## Post-inventory operational cleanup (October 20, 2026)

The user explicitly requested disabling unused NetBird and Podman on the
**current** OMV host. Their root terminal reported successful stop/disable
operations and follow-up verification:

- `netbird.service`: inactive, disabled.
- `podman.service`, `podman.socket`, `podman-auto-update.service`,
  `podman-auto-update.timer`: inactive, disabled.
- `podman-restart.service`: **failed** (not running), disabled.
  This is a residual failed unit state, **not evidence that Podman is active**.
  `systemctl reset-failed podman-restart.service` was suggested solely to
  clear the failed indicator; execution is **not confirmed**.
- Existing Docker container inventory unchanged; checks confirmed SSH,
  host Tailscale, Docker, Pi-hole and Gluetun remained running.
- No APT packages, Podman volumes, Docker applications, or persistent
  configs were deleted. This cleanup is reversible.

This supersedes the earlier inventory's *running NetBird* and *enabled
Podman* states. Do not assume future service status without fresh host
evidence. No other services were changed.

