# awtserver CLI and safety boundaries

**Command-only installation:** Debian 12 and 13, including OMV, can run the read-only terminal UI and diagnostics. Installing the command **does not enable service configuration**. Those write operations remain restricted to disposable Debian 13 virtual machines.

## Install, update and uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/dillacorn/awtserver/main/install.sh | sudo bash
awtserver
sudo awtserver update
sudo awtserver uninstall
```

This bootstrap gets a GitHub revision, fetches the source over HTTPS and installs the **allowlisted program files** into `/opt/awtserver`, with the command link `/usr/local/bin/awtserver`. As with any pipe-to-shell installation, review [the bootstrap source](https://github.com/dillacorn/awtserver/blob/main/install.sh) before running it. Requires Python 3, curl, and root privileges for system-wide installation. It never installs packages or starts services.

- **Install** refuses an existing command or installation. No overwrite or change to existing user files.
- **Update** fetches a SHA-pinned `main` archive, checks the installed manifest and file hashes, stages the new code and keeps rollback files if final cleanup fails. It refuses changed files, symlinks and unexpected contents.
- **Uninstall** removes **only** the verified program files and the owned symlink. It leaves `/etc`, `/var/lib`, system jobs, Docker volumes, storage, backups and your existing NAS configurations alone. If anything is unrecognized, it fails without removing that content.
- `awtserver version` prints the installed revision. `awtserver installer` previews a local install; no other management action is automatic.
- On an already deployed system, always verify current service permissions and back up important configurations independently. This manager is **not** an OMV migration/uninstaller.

Unattended automatic updates are **not** enabled. You explicitly run `sudo awtserver update`. A GitHub `main` merge provides a new upstream revision; no GitHub Release is needed.

From a checkout, `python3 awtserver` opens the read-only TUI or `python3 awtserver docs` displays the offline topics. Example: `python3 awtserver docs android-auto`. Full service-configuration and disk-recovery workflows remain experimental.



## Try the CLI

From a checked-out feature branch:

```bash
python3 awtserver.py doctor
python3 awtserver.py profiles
python3 awtserver.py plan
python3 awtserver.py plan --profiles base access storage ftp ups docker-debian scheduler
python3 awtserver.py install --profiles base storage
```

All commands above are read-only. `install` without `--apply` prints only a plan; no APT calls are made.

**VM-only package experiment:** After taking a VM snapshot and reviewing the selected package plan, running as root inside a **fresh Debian 13 VM**, a deliberate `install --apply --confirm-vm` performs APT index refresh, an APT simulated install and then installs the selected Debian packages. The preflight rejects OMV, unsupported Debian versions, non-root calls and machines not detected as virtual machines. **APT package installation can automatically start daemons** even though awtserver does not configure or enable services itself. Do not point this at a live or reused VM with important data.

The package profiles are independent. The default includes only `base`, `access`, `storage` and `backup`. The `sharing` (Samba), `ftp`, `ups`, `scheduler`, `borg`, `timeshift` and `docker-debian` profiles are opt-in. **Docker CE is confirmed on the existing OMV host.** `docker-debian` is explicitly the *alternative Debian archive provider* (`docker.io`/`docker-compose`), not a migration default. Official Docker CE + Compose plugin provisioning is **not implemented**; it needs a separate reviewed repository setup. Never automatically switch providers or mix their packages.

## Storage, SnapRAID and recovery

- `awtserver storage usage --threshold 80` warns when a filesystem exceeds 80%.
- `awtserver storage disks|pools|tools` reports devices, mergerfs pools and optional disk TUIs.
- `awtserver snapraid status|plan|enable|disable|sync` provides VM-only AIO scheduling (not a SnapRAID engine).
- `awtserver monitor stats|usage|check|notify` provides status, missing-mount detection and optional guarded mail.
- `awtserver backup plan|snapshot|restore-plan|restore-stage` provides UUID-verified, encrypted restic OS backup planning for a separately initialized USB repository.

More: `awtserver docs mergerfs`, `snapraid`, `alerts`, `recovery-usb`, `smart-ups`. Every write remains a separate Debian 13 disposable-VM operation; real OMV is not modified.

## Historical schedule review

`python3 awtserver schedules list` and `python3 awtserver schedules review --min-gap 60` inspect a **non-deployable October 22 OMV audit example**. This preserves only categories, schedules, enabled states and email flags. It flags possible short start gaps, not proven runtime overlap. TUI: Maintenance → OMV historical schedule audit. It never reads commands, runs scripts, activates cron or imports live OMV configuration.

## Job planning

```bash
python3 awtserver.py jobs list
python3 awtserver.py jobs add --name backups --schedule "15 2 * * *" --user backup --script /usr/local/libexec/awtserver-jobs/backup
python3 awtserver.py jobs enable --name backups
python3 awtserver.py jobs disable --name backups
```

**Recording and activating are separate operations.** `jobs add/enable/disable/remove` preview a desired state by default. On a disposable Debian 13 VM, their `--apply --confirm-vm` flags save only private state at `/var/lib/awtserver/jobs.json` (mode 0600). A job's `enabled` field is **desired state**, not proof that it runs.

A separate synchronization action is available:

```bash
python3 awtserver.py jobs render
python3 awtserver.py jobs sync
```

Both commands above are read-only previews. **Only in a disposable Debian 13 VM**, after provisioning a non-root execution account, writing a suitable root-owned executable script directly under `/usr/local/libexec/awtserver-jobs/`, and installing/running Debian's `cron` service, run `jobs sync --apply --confirm-vm` to install or update **only** the managed `/etc/cron.d/awtserver` file.

Sync refuses existing unmanaged cron content, symlinked target files, unsafe cron directory ownership/permissions, inactive cron, missing execution users, root execution, non-executable or non-root-owned scripts, and scripts writable by other users. The resulting file is atomically installed as root-owned mode 0644. Disabled jobs appear only as comments. Changes to stored job state are **not** automatically synchronized; use `jobs render` to inspect differences first.

Current limitations: five numeric cron fields, non-root job execution, strict script locations, no automatic user provisioning, no job-specific environment variables, no overlap locking or failure alert routing. Cron tasks missed while the VM is powered off are not caught up. **Cron activation remains experimental and is not authorized for the existing OMV server.**

## Read-only TUI preview

With an interactive SSH or local TTY (at least 30 columns wide and 14 lines high):

```bash
python3 awtserver_tui.py
```

The compact TUI has **Status / Packages / Schedules / Guides** categories. **Arrow keys or j/k** select and scroll, **Enter** opens details, **Esc or h** returns, and **q** quits. The Guides menu groups short documents under Remote access, Networking, Applications, Storage and Maintenance. It does not write files, install packages, or activate jobs. Window resizing and a small-terminal warning are supported. Configuration selection and commit/apply workflows remain CLI-only while their safety gates are tested.

## Safe OMV test workflow

For the existing Debian 12/OMV host, run only the pinned, unprivileged [TUI and temporary-write sandbox test](host-sandbox-validation.md). This test verifies **synthetic files** under private temporary directories, never actual cron/installer/backup writes. The CLI/TUI production write operations stay Debian 13 VM-only.

## Host inventory before OMV feature parity

`migration/debian/feature_probe.py` is a separate, read-only probe for the current OMV host. It reports service/package/timer presence and job counts without displaying host IPs, disk identifiers, cron commands, emails or container names. Its output helps determine which features must be adopted; it is not a backup or permission to change the host.

## Planned expansion

The CLI remains the noninteractive backend for the initial read-only terminal UI inspired by [smtty](https://github.com/dillacorn/smtty). The eventual menu can show service state, choose install profiles, edit and toggle scheduled tasks, review changes, and guide individual service setup. TUI navigation must never become necessary to use the CLI.

Actual storage mounts, SnapRAID parity configurations, existing array discovery, Samba shares and ACLs, Docker stack restore, Pi-hole networking, Tailscale identity, Fail2ban jails, APC UPS policy, SMTP credentials and OpenMediaVault removal remain explicitly **out of scope** for this prototype. They are captured in the [feature map](feature-map.md) and existing [recovery requirements](../migration/debian/restore-manifest.md). No host behavior is inferred from the public repository.

## Validate

```bash
python3 -m py_compile awtserver.py awtserver_cron.py awtserver_tui.py
python3 -m unittest discover -s tests -p 'test_awtserver*.py' -v
python3 awtserver.py plan
```

These are static and offline tests, not a verified clean Debian VM installation. Validate packages with a real disposable Debian 13 VM before broadening installation support.
