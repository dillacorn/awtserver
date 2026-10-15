# Docker Engine upgrade recovery for OMV

APT-driven Docker Engine/containerd upgrades should not leave previously running services stopped. This opt-in host-side safeguard supplements normal Docker restart policies; it does **not** upgrade Docker itself or modify Compose projects.

## Behavior

1. A Debian APT `DPkg::Pre-Install-Pkgs` hook checks the `.deb` filenames before Docker Engine, Docker CLI, or containerd packages install. Other package upgrades do nothing.
2. Before APT touches the Docker runtime, it records the **actual running** Docker container IDs and names with `always` or `unless-stopped` restart policies (excluding paused containers). It also records systemd invocation IDs for Docker and containerd. It does **not** snapshot stopped services or credentials.
3. A systemd timer checks a pending snapshot every minute, skips recovery while APT/dpkg holds package locks, and waits at least 30 seconds after capture. If neither runtime service restarted, it does nothing.
4. After a runtime restart, it inspects **those exact container IDs** and starts only containers which were running when the update began and are now unexpectedly exited, dead, or created. A second timer check verifies started containers remain running. Transient start failures retry, up to eight checks within one hour. Remaining failures are logged and stored in `last-result.json`.
5. Missing/replaced containers, changed restart policies, paused services and unhealthy-but-running containers are **never forcibly recreated or restarted**. Those conditions are reported for manual inspection.

No `docker compose up`, `docker compose restart`, blanket `docker start $(docker ps -aq)`, image pull, volume change, configuration overlay substitution, or forced container recreation occurs. In particular, the Pi-hole/Tailscale/IPv6 Compose overlay stack is never touched by this recovery mechanism.

This cannot prevent every outage. A container may crash repeatedly, lose upstream DNS, or be unhealthy while still running; restoring the process does not repair application-specific errors. Manual Docker operations and direct `dpkg -i` do not invoke the APT snapshot hook. Recovery snapshots expire after one hour, and overwritten/deleted container identities require separate investigation.

## Installation (on the actual OMV host)

Download or clone the **reviewed revision** of this repository. Run from the `docker/engine-upgrade-recovery` directory as root:

```bash
./install.sh --check
./install.sh --apply --enable-live-restore
```

`--check` is read-only. `--apply` installs the APT hook, recovery script and systemd timer **without restarting Docker or containers**. Adding `--enable-live-restore` safely merges `"live-restore": true` into the existing `/etc/docker/daemon.json`, validates the candidate config with `dockerd --validate`, backs up an existing config and calls `systemctl reload docker` (not restart). If you prefer to keep the Docker daemon config unchanged, use `./install.sh --apply` instead.

The installer refuses to overwrite foreign or locally modified managed files. Its checksum manifest allows subsequent repo-managed updates if the installed versions haven't been edited locally. Before deployment, verify you are on the intended OMV server; this repository is not proof of live host state.

Docker live restore reduces interruptions during supported daemon patch releases. It is **not guaranteed** for major Docker upgrades or containerd changes, which is why the APT snapshot/timer safeguard is still included. Docker networking may be temporarily disrupted even with live restore.

## Read-only verification

```bash
systemctl status omv-docker-upgrade-recovery.timer --no-pager
apt-config dump | grep -F 'omv-docker-upgrade-recovery'
docker info --format 'Live restore enabled: {{.LiveRestoreEnabled}}'
/usr/local/libexec/omv-docker-upgrade-recovery status
/usr/local/libexec/omv-docker-upgrade-recovery recover --dry-run
journalctl -u omv-docker-upgrade-recovery.service --no-pager -n 60
```

No package upgrade or live Docker restart is performed as a test. A true APT upgrade integration test requires an actual Docker runtime package update and separate host confirmation.

## Source files and rollback

| File | Host destination |
| --- | --- |
| `docker-upgrade-recovery.py` | `/usr/local/libexec/omv-docker-upgrade-recovery` |
| `90-omv-docker-upgrade-recovery` | `/etc/apt/apt.conf.d/90-omv-docker-upgrade-recovery` |
| `omv-docker-upgrade-recovery.service` | `/etc/systemd/system/omv-docker-upgrade-recovery.service` |
| `omv-docker-upgrade-recovery.timer` | `/etc/systemd/system/omv-docker-upgrade-recovery.timer` |

The snapshot, final result and installer checksum manifest are in `/var/lib/omv-docker-upgrade-recovery/`. These contain container IDs/names and status text only, not volumes, env files or secrets. Failure reports also appear in the systemd journal.

To disable automatic recovery without disabling Docker upgrades:

```bash
systemctl disable --now omv-docker-upgrade-recovery.timer
```

Disabling the timer does not disable the APT snapshot hook. Restore a saved daemon config if you want to reverse live restore; validate it and use `systemctl reload docker`. Do not delete unknown daemon settings, or change Compose files to roll back this recovery feature.

## Offline test

From a checkout of the repository, run:

```bash
python3 -m unittest discover -s tests -v
bash -n docker/engine-upgrade-recovery/install.sh
python3 -m py_compile docker/engine-upgrade-recovery/*.py
```

No real Docker containers are started by these tests.

Official documentation: [Docker live restore](https://docs.docker.com/engine/daemon/live-restore/) and [Debian APT `DPkg::Pre-Install-Pkgs`](https://manpages.debian.org/bookworm/apt/apt.conf.5.en.html).
