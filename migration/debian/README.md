# OMV -> minimal Debian migration

**Status: discovery / planning only.** No OS installation, disk migration, Docker
recreation, firewall change, fail2ban change or host deployment has been authorized
or performed by this folder.

**Goal:** When the existing Intel OS SSD eventually needs replacement, install
minimal, stable Debian with SSH/TTY as the authoritative administration interface.
Recreate existing services from documented source configuration, with no dependency
on OpenMediaVault's web interface or OMV's XML configuration database.

As of October 2026, Debian **13 (Trixie)** is the stable release. Recheck
support and packages when the actual SSD replacement occurs. No desktop
environment is required. A web UI is optional and subordinate to plain files
and systemd, not a second source of truth.

## Confirmed future Debian preferences

User-confirmed October 20, 2026:

- **Required:** SSH/TTY administration; Docker Compose and application data;
  existing Tailscale topology, Pi-hole DNS, Gluetun isolation, SnapRAID,
  mergerfs, FTP/ProFTPD and its Fail2ban protection, SMART/email monitoring,
  APC UPS shutdown safeguards and backup/scheduled-job continuity.
- **Optional only:** SMB/Samba. The user seldom uses it but wants it
  available. Preserve the existing share definition, credentials/identity
  mappings and access policy in private recovery material. Do not enable
  `smbd` or `wsdd-server` by default on new Debian; provide an opt-in
  native-service profile later. Do not remove mergerfs or its data.
- **Omit:** NetBird and Podman, including the Podman restart/auto-update
  units. The user does not use either and does not plan to.
- **Remove OMV-only functionality** after new Debian cutover: OMV GUI,
  engine and related web authentication jail. Do not disable on live OMV.
- Other enabled services (ClamAV, collectd, Avahi, rsync/backup tasks,
  ProFTPD's exact exposure, etc.) still require dependency evaluation.

These decisions affect only the **future replacement OS**. The working
OMV server and all containers remain unchanged.

## First step: collect CURRENT host evidence

Run the read-only script `inventory.py` on the actual host as root. It requires
`hostname=openmediavault`, reads source-of-truth runtime state rather than
assuming that this repository matches the server, and writes only to a root-only
directory under `/root/debian-migration-inventory`.

The result has a brief terminal summary and a private `inventory.json`.
The full file includes disk UUIDs/serials, addresses, usernames, mount paths,
Docker source paths and other PRIVATE infrastructure metadata; it must **never
be committed to this public GitHub repository**. It does **not** collect
passwords, private keys, Docker environment variable values, actual Compose
contents, credentials-bearing service configuration bodies, or persistent data.

This is an inventory, **not a verified backup**.

### What the inventory discovers

| Area | Evidence gathered | Rebuild strategy to decide later |
|---|---|---|
| Boot / OS | Current Debian/OMV version, BIOS/UEFI, kernel, disks | Install Debian on **new OS SSD only**; never format data/parity drives |
| Storage | UUIDs, filesystem types, active mounts, mergerfs mounts and fstab fields | Explicit fixed UUID mounts and matching mergerfs branches |
| SnapRAID | Parity/data/content directives, status, related packages | Restore original config and AIO workflow; do not initialize array |
| SSH | Safe subset of effective settings, config file names | Restore pubkey authentication and access *before* old host retirement |
| Fail2ban | Active jails, ban counters, jail/filter/action file names | Install native fail2ban and transfer reviewed jail configs privately |
| Networking | Interfaces, routes, Tailscale self info, firewall table names, listening ports | Ensure remote SSH, firewall and DNS access before switching |
| Docker | Exact runtime container names, images, Compose project/service labels, source paths, bind mounts, volumes, ports, namespaces and restart policy | Restore **original Compose projects** and persistent data, preserving shared VPN/Tailscale namespace groups |
| Shares | Samba share names/paths, NFS exports (client rules omitted) | SMB is **optional**, not enabled by default in the future Debian plan; preserve the existing share configuration and permissions for later opt-in |
| Other services | systemd services/timers, cron schedule metadata, UPS, SMART, mail tools | Recreate host-native services and alerts without OMV plugins |
| Packages/users | Infrastructure packages, manually installed packages, UID/GID and homes | Preserve service identity and file ownership across reinstall |

**Special checks** to conduct after viewing the first report:

- Fail2ban: identify exact jail overrides, backend, filters, actions,
  ignored-IP lists, log sources, firewalls and persistent ban database needs.
  Copy config privately only after review; never publish protected IPs/keys.
- UPS: determine whether APCUPSD or NUT actually controls shutdown.
- SMART: determine smartd mail routing and current device by-id paths, not
  unstable `/dev/sdX` identifiers.
- SSH/firewall: test access from LAN and Tailscale independently *before*
  enabling restrictive policies; do not lock out recovery access.
- SnapRAID/mergerfs: preserve identical disks and parity/content metadata;
  verify backups before migration, not by guessing from old notes.
- Pi-hole/Tailscale DNS: maintain DNS continuity; prepare an alternate
  resolver to avoid a bootstrapping loop while replacing the host OS.
- Docker: ensure all projects' files, env files, **named and bind volumes**,
  ownership and sidecar network dependencies are backed up and restorable.
  Backups must contain data, not merely image/container metadata.
- Watchtower's 02:45 ET updates and 05:00 independent health timer,
  Pi-hole DNS guard, Tailscale certificate renewal, SnapRAID AIO and OMV
  email/SMART alerts need native systemd timer or service replacements.
- Any OMV-created configuration must be reconstructed explicitly;
  do **not** blindly import `/etc/openmediavault/config.xml` into Debian.

## First real OMV inventory checkpoint (October 20, 2026)

The user ran the SHA-pinned **read-only** inventory on the verified
`openmediavault` host. The terminal summary (safe facts only) confirms:

| Observed live fact | October 20 result |
|---|---|
| Base OS and boot | Debian 12 Bookworm, UEFI |
| Docker fleet | 55 total container records; 12 named Docker volumes |
| Running queried native services | SSH, Fail2ban, Docker, cron, Samba (`smbd`), APC UPS (`apcupsd`), host Tailscale (`tailscaled`), `pihm-web`, unattended upgrades |
| Fail2ban jails | `omv-webgui`, `proftp`, `ssh` |
| Samba / NFS | 1 Samba share, 0 exported NFS paths |
| systemd | 75 enabled unit names in saved private inventory |
| root user's crontab | 0 schedules (does not exclude system crontabs/timers or OMV schedules) |
| SnapRAID | 38 directives present |
| APT infrastructure | 62 relevant installed package entries |

**Interpretation:** Keep the actual SSH Fail2ban jail when reconstructing
Debian. `omv-webgui` is likely obsolete without OMV; `proftp` may be
obsolete **only after** confirming whether an FTP daemon is still used.
Do not remove either while OMV is running. Do not equate the 55 Docker records
with 55 running services or the 75 enabled units with 75 active processes.
The 1 Samba share's definition, access policy and UID/GID must be preserved in the private migration archive for optional later use. SMB is not part of the required day-one Debian services.

**Next data handoff:** The JSON was saved privately at
`/root/debian-migration-inventory/20261020-135204-875455/inventory.json`.
Run the separately reviewed `review.py` against this existing JSON to
produce a targeted, private chat report: actual unit/timer names, fail2ban
config entry points, storage and mergerfs mounts, Samba share paths,
Docker Compose provenance, UPS/mail program availability and installed
infrastructure packages. This does not collect additional host data or
change any services. The full original JSON should remain outside public Git.

**Still unknown:** OMV plugins and DB state versus true host config sources;
actual effective fail2ban jail configurations and log sources; SMB users and
permissions; UPS shutdown policy and connection; SMART/email service settings;
any scheduled OMV UI tasks; system firewall policy; static IP/resolver policy;
all 55 containers' real Compose paths and persistence dependencies; external
secret backup/restore strategy. Identifying these requires current live
facts rather than guessing from repo examples.

## Second live review checkpoint: dependency audit

The user supplied a focused review of the same private October 20 inventory.
A sanitized interpretation is saved in
[host-findings-2026-10-20.md](host-findings-2026-10-20.md), without
publishing disk UUIDs, authentication policies, user names or private
Docker source paths.

Important new findings:

- One currently configured Samba share points to mergerfs, but the user **rarely uses SMB**. Treat it as an optional future service, preserve its configuration in private backup, and do not enable it by default. The mergerfs storage mount remains mandatory for other services.
- SSH/Fail2ban must be migrated as a coordinated access policy, not simply
  copied from OMV. The *actual* SSH settings remain private.
- Docker has 55 running Compose-provenance-backed containers and 12 named
  volumes. Stale Freshdock overlays are still part of many Compose source
  references. Preserve source identity until explicitly migrated.
- OMV backup, FTP, ClamAV, SMART/mail and network facilities overlap with
  ordinary Debian programs. Enabling a unit or installing an OMV plugin
  does not establish ongoing use.
- The 64 GB unmounted device must be identified before any disk-selection
  or restore script is constructed.

The next one-shot probe is [native_audit.py](native_audit.py).
It **only reads** live systemd states, mergerfs mount types, the presence
and count of OMV scheduled tasks where available, basic backup indicators
and Podman container names. It prints no SSH policy values, login keys,
firewall rules, Docker environment values or OMV scheduled job commands.
Use its private terminal output to decide which host features to retain.
The workflow tests audit parsing and sensitive-field suppression; it does
not validate actual host service behavior.

The future-service split, preservation requirements, acceptance checks
and opt-in SMB profile are tracked in
[restore-manifest.md](restore-manifest.md). Scheduled OMV and rsync jobs can
be classified without exposing their command bodies using
[jobs_audit.py](jobs_audit.py).

## Rebuild milestones

1. **Inventory:** Run `inventory.py`; analyze the private report and compare
   real state with repo documentation. Identify unknown host services.
2. **Configuration audit:** For every host-native service, document source
   files, owners, UID/GID, dependencies, secrets required and exact systemd
   start/restore validation. Separate OMV-managed settings from plain Debian.
3. **Backup + rollback:** Produce a separately stored verified encrypted
   backup of OS configuration/secrets and tested backups of app data. Record
   SMART state, disk/UUID mapping, shares, DNS behavior, firewall, permissions
   and known working Compose provenance. **Keep original Intel SSD intact.**
4. **Installer design:** After inventory/backup review, develop an idempotent,
   staged Debian installer with dry-run, explicit disk identifiers, package
   installation, systemd units/timers, and a *separate* manual restore phase.
   Absolutely no automatic partitioning of existing storage drives.
5. **Isolated rehearsal:** Test with a separate spare SSD or disposable
   Debian environment; validate native systemd services and Docker stacks.
   A throwaway VM alone cannot validate physical disk UUIDs and hardware UPS.
6. **Actual cutover:** Physically remove/disconnect or positively isolate
   existing data/parity disks during the **new OS SSD installer** as practical,
   verify target disk serial/capacity and boot path, and preserve old SSD.
   Mount data disks only after reviewing `blkid`, `lsblk`, and `fstab`.
7. **Acceptance tests:** SSH LAN/Tailscale, FTP, DNS/Pi-hole, mergerfs and SnapRAID,
   fail2ban, firewall, optional Samba only if enabled, UPS/smartd email, all relevant Compose
   projects/volumes, Docker updates, systemd timers and backup restore.
   No decommission until these pass.

## Web administration options

**Primary:** SSH + terminal, systemd, Docker Compose, source files in Git.
Retain existing **Dockge** for Compose management if desired.

**Optional:** [Cockpit](https://cockpit-project.org/) for basic Debian
system/drive/service/log monitoring, preferably access-restricted to
LAN/Tailscale, not publicly exposed. Docker-containerized dashboards such as
Homepage or Homarr are presentation layers, not substitutes for mounting,
firewall, SSH, backup or systemd administration.

Avoid replacing the OMV GUI with a second configuration authority. At most
one tool should own a given daemon's actual configuration.

## Safety limits

- Do not run the installer or deletion tools during discovery. This project
  currently contains **no executable deployment script**.
- Never use inventory JSON as configuration, a disk restore manifest or a
  backup. The command deliberately does not capture secrets or contents.
- No indiscriminate `rsync` of live Docker DBs or SnapRAID parity while
  writers are running. SnapRAID is not a replacement for backups.
- Do not assume the Intel OS SSD is failing solely because a SMART report
  had a nonzero error count. There is no immediate migration deadline.
- The prior WD 8 TB SATA cable issue is reported resolved by the user; live
  drive health will be reassessed when the actual migration is prepared.

## What to do after the first inventory

Supply the terminal summary first, then run `review.py` against the existing
private JSON and paste its focused report into this PRIVATE conversation.
Retain the original JSON for a later deeper audit; review it before attaching
or transmitting it. Never attach the inventory to a GitHub
issue, commit, release or public gist. The next phase will identify missing
host-specific configurations and prioritize native replacements.

Repo notes and example Compose YAML are not guaranteed to be deployed.
Only a **new live host inventory** establishes actual container names,
Compose service identity, paths, storage mounts and active services.
