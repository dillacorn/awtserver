# What's Up Docker (WUD): replacement for Watchtower

This directory contains WUD 9.4.1 Compose and a one-shot, guarded OMV
migration script. The public repository contains **no SMTP addresses, passwords,
access tokens or server-specific authentication credentials**.

## Design

- Target host: `openmediavault`; current live Compose source:
  `/docker/watchtower/compose.yml`.
- Reads the **running** Watchtower container and verifies Compose labels, the
  complete reviewed 28-application allowlist, and daily 02:45 schedule.
- Creates `/docker/wud/compose.yml` and a root-only `/docker/wud/.env`.
  SMTP credentials are inherited from the currently running Watchtower's
  Docker environment, not from GitHub.
- WUD 9.4.1 runs without HTTP/API, with a persistent `/docker/wud/store`
  directory and no published ports.
- WUD's name `INCLUDE` regex is anchored to exact Watchtower-selected
  application container names; additional `EXCLUDE` regex blocks Pi-hole,
  Quad9 dnsproxy, nginx-pihole, Watchtower and WUD.
- WUD's `wud.watch=true` label can override watcher include/exclude patterns.
  Migration fails if any non-selected existing container bears that opt-in label.
- Automatic image updates at 02:45 America/New_York. No scan at startup or
  on Docker lifecycle events. Watchtower is stopped and removed as a container.
- Uses the WUD Docker trigger rather than its Docker Compose trigger to avoid
  letting the updater rewrite Compose files and overlays under independent
  `/docker/` directories.
- SMTP on `success,failure,rollback`. Notifications are best effort, and
  initial delivery must be verified at the next update event.
- Healthcheck rollback is enabled; for images lacking HEALTHCHECK, WUD
  accepts a container after a 15-second running-state check. Rollback does not
  undo database schema migrations, persistent-file changes, or networking
  failures invisible to the container healthcheck.
- WUD itself is pinned to 9.4.1 and excluded from unattended self-updating.
- Docker Engine updates and host reboots are outside WUD's control. The host
  Docker upgrade recovery guard remains independent.

## Execute a complete migration

Run the migration script only after inspecting the commit and performing the
host-specific preflight checks it contains:

```bash
curl -fLsS https://raw.githubusercontent.com/dillacorn/omv-remote-dots/main/docker/wud/migrate-watchtower-to-wud.sh -o /tmp/migrate-watchtower-to-wud.sh
bash /tmp/migrate-watchtower-to-wud.sh
```

The script:

1. Confirms host, current service names and the live Watchtower command.
2. Confirms all three critical DNS containers remain running and that no
   `wud.watch=true` label bypasses the exact allowlist.
3. Refuses to overwrite existing WUD configurations and refuses to run near
   Watchtower's scheduled update.
4. Writes only WUD configuration, pre-pulls the pinned WUD image, and validates
   resolved Compose before any container stop.
5. Makes a private backup of the legacy Watchtower Compose file.
6. Disables Watchtower's restart policy, stops/removes only its container and
   starts WUD. An EXIT trap attempts to restore Watchtower using the original
   Compose if WUD startup/effective-config checks fail.
7. Confirms Pi-hole, dnsproxy and nginx-pihole container identities remained
   unchanged.

Persistent application volumes/networks are never deleted or pruned. The
legacy `/docker/watchtower/compose.yml` remains for emergency rollback,
though there is **no Watchtower container** after successful cutover. Do not run
`docker compose up -d` there again.

### Inspect the result

```bash
docker ps --filter name=wud --format 'table {{.Names}}\t{{.Status}}'
docker logs --tail 100 wud
docker inspect wud --format '{{.State.Running}} {{.RestartCount}}'
```

No source repository change proves any runtime deployment succeeded. Capture
the host command output to confirm. If the private source SMTP password has
appeared in chat, rotate it after the migration and update `/docker/wud/.env`.

## Important operational notes

- The first scheduled run is the next 02:45 in the local timezone. It may take
  additional time due to WUD's registry polling and jitter.
- The 03:45 SnapRAID job and the 03:00 Docker Engine unattended upgrades are
  independent of WUD. They can still create resource contention or downtime.
- WUD's 9.x Docker trigger can recreate containers with network namespace
  dependencies, but those updates have not been runtime-tested on this OMV host.
  WUD's basic container health gate is not a complete integration test.
- A failed switch restores Watchtower if Docker is healthy enough to run it.
  If Docker itself is unavailable, recovery requires manual intervention.
- A WUD `docker compose up -d` does not update the original application
  Compose files. Preserve WUD state/config and use scheduled/manual coordinated
  maintenance for complex dependency stacks.
- Changing SMTP settings requires updating the root-only `.env` and recreating
  only WUD using `cd /docker/wud && docker compose up -d wud`.

Docs:
- https://getwud.app/docs/configuration/watchers/
- https://getwud.app/docs/configuration/triggers/docker/
- https://getwud.app/docs/configuration/triggers/smtp/
- https://getwud.app/docs/configuration/triggers/ntfy/
- https://getwud.app/docs/configuration/storage/
