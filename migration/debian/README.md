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

## First step: collect CURRENT host evidence

Run the read-only script \`inventory.py\` on the actual host as root. It requires
\`hostname=openmediavault\`, reads source-of-truth runtime state rather than
assuming that this repository matches the server, and writes only to a root-only
directory under \`/root/debian-migration-inventory\`.

The result has a brief terminal summary and a private \`inventory.json\`.
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
| Shares | Samba share names/paths, NFS exports (client rules omitted) | Restore identities, permissions, access policy and share services |
| Other services | systemd services/timers, cron schedule metadata, UPS, SMART, mail tools | Recreate host-native services and alerts without OMV plugins |
| Packages/users | Infrastructure packages, manually installed packages, UID/GID and homes | Preserve service identity and file ownership across reinstall |

**Special checks** to conduct after viewing the first report:

- Fail2ban: identify exact jail overrides, backend, filters, actions,
  ignored-IP lists, log sources, firewalls and persistent ban database needs.
  Copy config privately only after review; never publish protected IPs/keys.
- UPS: determine whether APCUPSD or NUT actually controls shutdown.
- SMART: determine smartd mail routing and current device by-id paths, not
  unstable \`/dev/sdX\` identifiers.
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
  do **not** blindly import \`/etc/openmediavault/config.xml\` into Debian.

## Rebuild milestones

1. **Inventory:** Run \`inventory.py\`; analyze the private report and compare
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
   Mount data disks only after reviewing \`blkid\`, \`lsblk\`, and \`fstab\`.
7. **Acceptance tests:** SSH LAN/Tailscale, DNS/Pi-hole, mergerfs and SnapRAID,
   fail2ban, firewall, Samba/NFS, UPS/smartd email, all relevant Compose
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
- No indiscriminate \`rsync\` of live Docker DBs or SnapRAID parity while
  writers are running. SnapRAID is not a replacement for backups.
- Do not assume the Intel OS SSD is failing solely because a SMART report
  had a nonzero error count. There is no immediate migration deadline.
- The prior WD 8 TB SATA cable issue is reported resolved by the user; live
  drive health will be reassessed when the actual migration is prepared.

## What to do after the first inventory

Supply the terminal summary first, followed by the private JSON *in the
conversation* after reviewing it. Never attach the inventory to a GitHub
issue, commit, release or public gist. The next phase will identify missing
host-specific configurations and prioritize native replacements.

Repo notes and example Compose YAML are not guaranteed to be deployed.
Only a **new live host inventory** establishes actual container names,
Compose service identity, paths, storage mounts and active services.
