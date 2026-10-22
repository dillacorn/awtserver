# awtserver CLI prototype

**Experimental:** Tested code paths are intended for a **disposable Debian 13 virtual machine**. There is no supported live-NAS installation or OMV removal procedure.

## Try the CLI

From a checked-out feature branch:

```bash
python3 awtserver.py doctor
python3 awtserver.py profiles
python3 awtserver.py plan
python3 awtserver.py plan --profiles base access storage ftp ups docker scheduler
python3 awtserver.py install --profiles base storage
```

All commands above are read-only. `install` without `--apply` prints only a plan; no APT calls are made.

**VM-only package experiment:** After taking a VM snapshot and reviewing the selected package plan, running as root inside a **fresh Debian 13 VM**, a deliberate `install --apply --confirm-vm` performs APT index refresh, an APT simulated install and then installs the selected Debian packages. The preflight rejects OMV, unsupported Debian versions, non-root calls and machines not detected as virtual machines. **APT package installation can automatically start daemons** even though awtserver does not configure or enable services itself. Do not point this at a live or reused VM with important data.

The package profiles are independent. The default includes only `base`, `access`, `storage` and `backup`. The `sharing` profile (Samba), `ftp`, `ups`, `docker` and `scheduler` profiles are opt-in. Docker uses Debian's `docker.io` and `docker-compose` packages for this isolated prototype; do **not** mix them with an installation from Docker's official repository.

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

## Planned expansion

The CLI will be the noninteractive backend for a later raw-key, arrow-key **TUI inspired by [smtty](https://github.com/dillacorn/smtty)**. The eventual menu can show service state, choose install profiles, edit and toggle scheduled tasks, review changes, and guide individual service setup. TUI navigation must never become necessary to use the CLI.

Actual storage mounts, SnapRAID parity configurations, existing array discovery, Samba shares and ACLs, Docker stack restore, Pi-hole networking, Tailscale identity, Fail2ban jails, APC UPS policy, SMTP credentials and OpenMediaVault removal remain explicitly **out of scope** for this prototype. They are captured in the [feature map](feature-map.md) and existing [recovery requirements](../migration/debian/restore-manifest.md). No host behavior is inferred from the public repository.

## Validate

```bash
python3 -m py_compile awtserver.py tests/test_awtserver_cli.py
python3 -m unittest discover -s tests -p 'test_awtserver_cli.py' -v
python3 awtserver.py plan
```

These are static and offline tests, not a verified clean Debian VM installation. Validate packages with a real disposable Debian 13 VM before broadening installation support.
