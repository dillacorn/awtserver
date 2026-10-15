# WUD migration from live Watchtower (staged)

This directory replaces the legacy Watchtower updater **after runtime validation**.
It is not a mirror of the live OMV host. Do not treat the sample as proof that WUD
has been installed or that Watchtower has been decommissioned.

**Current scope:** WUD 9.4.1, monitoring-only staging, then an explicitly gated
Docker update trigger. No automatic update trigger is enabled in the base Compose.

## Why this configuration

- The live Watchtower used `--schedule "0 45 2 * * *"` and a positional
  allowlist of 28 application containers plus `watchtower` itself.
- `stage-from-watchtower.sh` re-reads that **running container's** Docker
  `Config.Cmd` and Compose identity, rejects deviations from the reviewed
  configuration, and derives an anchored exact-name WUD watcher regex.
- DNS infrastructure (`pihole`, `dnsproxy-quad9`, `nginx-pihole`) and WUD
  itself are excluded. No application Compose files or labels are changed.
- The WUD watcher runs at 02:45 America/New_York, not during SnapRAID's
  03:45 run. Startup checks and Docker-event-driven checks are disabled to
  avoid unplanned update events.
- WUD watches mutable image digests, matching Watchtower's use of many
  `latest` tags.
- The Docker trigger is preferred to WUD's Compose trigger here because the
  live server uses separate Compose project directories and overlay files.
  The Docker trigger does not edit project Compose files. Recreating containers
  can nonetheless create drift from their Compose definitions; investigate
  after updates and before running `docker compose up -d` on those projects.
- Rollback validates application container state/health only, not database
  reversibility, network reachability, or functionality of Tailscale sidecars.
  A new version can irreversibly migrate persistent data despite rollback.
- WUD's API/web UI is not published to the host.
- Notification credentials are copied from the live Watchtower Compose into
  `/docker/wud/.env` (mode 0600); no credentials or personal addresses belong
  in this public repository.

## Stage on the verified OMV host

Run the reviewed feature-branch installer only after checking its contents:

```bash
curl -fLsS https://raw.githubusercontent.com/dillacorn/omv-remote-dots/feat/wud-watchtower-migration/docker/wud/stage-from-watchtower.sh -o /tmp/stage-wud.sh
bash /tmp/stage-wud.sh
```

It verifies the real host and currently running Watchtower before writing,
creates `/docker/wud/compose.yml`, `compose.updates.yml`, and a private
`.env`, then starts *only WUD*. Watchtower and all other containers remain
running. Only the monitoring-only base file is applied. SMTP is configured
but inactive in this stage, to avoid duplicate notifications.

If any assertion fails, the script stops; **do not bypass checks**.
It does not automatically retry an incomplete staging directory.

Check:

```bash
docker inspect wud --format '{{.State.Status}} {{.State.Health.Status}}'
docker logs --tail 100 wud
docker inspect watchtower --format '{{.State.Running}} {{.State.RestartCount}}'
```

## Cutover (NOT yet performed)

Do not enable unattended updates just because WUD starts. Before cutover:
verify the actual container names, Compose projects/services, network modes,
bind mounts, healthchecks and dependency chains for *every* allowlisted
container, especially `tailscale-*`, `gluetun`, and database services.
Review WUD logs for all 28 expected names and no DNS services. Verify the
WUD SMTP target works. Test manual updating/rollback on a disposable or
non-critical container first. Confirm the SnapRAID/DNS observation and prevent
any overlap with unattended image pulls/restarts.

After those checks, `compose.updates.yml` enables the Docker updater and
SMTP notifications. Preserve the Watchtower Compose backup and a rollback
command, explicitly disable Watchtower's restart policy before stopping it,
and make sure only one updater is active. No step in staging stops Watchtower.

A future cutover may set `COMPOSE_FILE=compose.yml:compose.updates.yml` in
the private `.env` and recreate only WUD; but this is **not a safe unattended
command** until the live checks above pass. Do not blindly run this on OMV.

To undo monitoring-only staging without touching Watchtower:

```bash
cd /docker/wud && docker compose -f compose.yml down
```

Do not delete `/docker/wud` without reviewing saved configuration/state.

## Current documentation

- https://getwud.app/docs/configuration/watchers/
- https://getwud.app/docs/configuration/triggers/docker/
- https://getwud.app/docs/configuration/triggers/smtp/
- https://getwud.app/docs/configuration/triggers/ntfy/
- https://getwud.app/docs/configuration/storage/
