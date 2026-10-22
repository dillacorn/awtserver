# awtserver CLI prototype

**Experimental:** Tested code paths are intended for a **disposable Debian 13 virtual machine**. There is no supported live-NAS installation or OMV removal procedure.

## Terminal command and quick guides

From the checked-out development branch, run `python3 awtserver` to open the **read-only** TUI, or `python3 awtserver docs` for short topics. Examples: `python3 awtserver docs remote-apps` and `python3 awtserver docs android-auto`. All quick guides work offline after the files have been downloaded.

On a **disposable Debian 13 VM**, `python3 awtserver installer` previews a first-time command install. After confirming the source checkout and taking a snapshot, `sudo python3 awtserver installer --apply --confirm-vm` installs the reviewed files to `/opt/awtserver` and a symlink at `/usr/local/bin/awtserver`. Thereafter run `awtserver`, `awtserver doctor`, or `awtserver docs`. Existing installation paths are never overwritten; update and uninstall are **not implemented**. No other host is supported for installation.

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

With an interactive SSH or local TTY (at least 30 columns wide and 12 lines high):

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
