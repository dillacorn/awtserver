# Freshdock production migration: initial audit (no cutover)

## Host-confirmed situation (2026-10-18)

- OpenMediaVault host: `openmediavault`, Docker Engine `29.9.1`.
- Running WUD `getwud/wud:9.4.1` with an anchored 28-container allowlist and daily `45 2 * * *` updater.
- Gluetun healthy, `tun0` route verified; Mullvad Browser references the current Gluetun ID.
- **Transmission is still paused and points at an obsolete Gluetun ID. Do not unpause it or bypass the VPN.**
- No SnapRAID processes were detected, but this does not verify the damaged SATA cable is repaired.
- WUD's Docker trigger **failed** a disposable shared-network update; Freshdock v1.7.1 passed manual recreation, automatic registry-triggered update, unhealthy-image rollback, and dependent reattachment in disposable tests (#8, #9, #10).

## Why we cannot directly translate the WUD configuration

Freshdock v1.7.1 is intentionally **label-opt-in**. It has no WUD `WUD_WATCHER_LOCAL_INCLUDE` equivalent. Setting `FRESHDOCK_WATCH_ALL=true` with `FRESHDOCK_DEFAULT_MODE=nightly` could update non-allowlisted Pi-hole/database/other containers. **Never use that as a shortcut.**

To preserve the existing selection, each reviewed Compose **service** needs these labels:

```yaml
labels:
  freshdock.enable: "true"
  freshdock.mode: "nightly"
  freshdock.schedule: "45 2 * * *"
  freshdock.notify: "true"
```

These are *illustrative labels*, not a ready-to-apply Compose file. Preserve each existing service's labels (merge, do not replace), mounts, networks, images and project configuration. Freshdock should use `FRESHDOCK_WATCH_ALL=false`, `FRESHDOCK_DEFAULT_MODE=watch`, `FRESHDOCK_COMPOSE_AWARE=true` and cleanup/prune disabled initially. Verify its **local timezone** really matches `America/New_York` before trusting the 02:45 schedule. Existing `watch` or `off` labels must be reviewed individually. An unlabelled Compose one-shot that an enabled service requires to complete may be re-run by Freshdock's Compose-aware rollout; audit this case.

Adding labels to already-running containers generally requires **recreating them through their original Compose source**, which is a production change. This audit deliberately does not do that. Do not recreate VPN-dependent services while Transmission is attached to the obsolete Gluetun ID; plan its safe Compose recovery separately.

## Private email notification migration

The prior report's `SMTP configured: False` was a false negative; it checked `WUD_SMTP_*` on the running container instead of `WUD_TRIGGER_SMTP_LEGACY_*`. This audit prints only whether the six effective SMTP fields are set, plus non-secret TLS and event flags. It does not read or print the private `/docker/wud/.env`.

Freshdock's email settings use its own `notifications.email` TOML keys or private `FRESHDOCK_NOTIFY_*` variables, and email requires per-container `freshdock.notify=true`. WUD's `success,failure,rollback` events map to Freshdock's `succeeded,failed` notifications; a rollback should be reported as a failure. **Do not assume WUD's `TLS_ENABLED=false` has the same meaning as Freshdock's `tls=none`.** Match the relay's actual transport requirements and verify delivery without exposing credentials in GitHub or chat.

## Read-only audit command

On OMV as root:

```bash
python3 audit_migration.py
```

The audit reads Docker inspection metadata but performs no Docker writes, restarts, migrations, unpauses or file rewrites. It prints:

- WUD's effective allowlist, override-label anomalies and current schedule.
- The exact service/project and Compose file paths behind each selected container.
- Current states and network references, including the paused Transmission mismatch.
- Existing Freshdock/Watchtower policies to preserve or correct.
- Whether the real legacy SMTP fields are present, without secrets.
- Compose path and one-shot dependency warnings.

## After auditing

Prepare a **separate guarded cutover** that:

1. Confirms every selected container, Compose project/service and file and backs up (mode 0600) any Compose and WUD files it will touch; protect credentials.
2. Constructs and validates minimally scoped per-service Freshdock labels in the *actual live Compose definitions or an explicit per-project overlay*, without modifying unrelated services.
3. Creates an authenticated private notification configuration only on the host; verifies SMTP and scheduler timezone.
4. Prevents simultaneous updater control; WUD must be safely disabled/stopped **before any Freshdock automatic-update mode is enabled**. Keep the old Compose for rollback.
5. Uses a deliberate maintenance window for the required Compose recreations, preserving all mounts, databases, networks and overlay ordering. Reattach Transmission to Gluetun only through a verified fail-closed recovery procedure.
6. Validates actual Freshdock eligible services, non-eligible services, schedule, email notifications, VPN routing and every selected Compose stack. Stop/roll back if verification fails.

**No merge, release or production migration is authorized merely by the audit.** Related: #8, #9, #10.

Freshdock documentation: https://github.com/Turbootzz/freshdock/blob/main/docs/configuration.md and https://github.com/Turbootzz/freshdock/blob/main/docs/notifications.md.

## Follow-up live audit findings (2026-10-18)

The user ran the read-only audit on OMV successfully:

- **26** of the 28 exact WUD allowlist names currently exist. There were **no** unexpected `wud.watch=true` overrides, WUD exemptions, or existing Freshdock/Watchtower policy labels.
- WUD's **six of six SMTP fields are present** in the actual running container. Its actual TLS mode still requires a private configuration review; never disclose SMTP addresses or credentials.
- Docker Compose labels resolve selected containers to **12** projects, many using separate `compose.yml` and `compose.override.yml` files. Apply both original paths in order when validating or migrating.
- **Two recorded Compose paths are missing**: `/docker/rustdesk/docker-compose.yml` for `hbbs` and `hbbr`, and `/docker/vaultwarden/docker-compose.yml` for `nginx-vaultwarden` and `vaultwarden`. Do not blindly recreate these four containers; first identify their actual live Compose source and confirm its service names.
- Transmission remains **paused with a stale Gluetun namespace**. Mullvad Browser is correctly attached to Gluetun.

Use the additional **read-only targeted discovery**:

```bash
python3 docker/freshdock/resolve_missing_compose.py
```

It searches only the relevant two project directories (bounded depth), checks
recorded Docker Compose source paths, and safely asks `docker compose config
--services` for candidate file service names. It does not print config contents,
interpolation error messages, environment values, volumes or secrets. Failed
validation is reported as unverified, not interpreted as absence of a service.
If the missing files cannot be found or parsed, preserve these four services in
place during any initial migration rather than reconstructing their configuration
from container inspect alone.

## Second Compose source check (2026-10-18)

The user ran the first missing-source discovery:

- **RustDesk:** `/docker/rustdesk/compose.yml` exists and declares both `hbbs` and `hbbr` (the current recorded `docker-compose.yml` file is missing). Treat this as a plausible replacement source, but review the resolved configuration against running containers before any recreate.
- **Vaultwarden:** `/docker/vaultwarden/compose.yml` and `compose.override.yml` both exist. The previous script checked only the base file and reported no matching services; this does **not** establish that the combined Compose configuration is invalid. The running project includes `vaultwarden`, `nginx`, `application`, and `tailscale`. Test the pair **in that order**, requesting only `config --services`, to establish whether the combined sources contain all four.

The updated `resolve_missing_compose.py` reports **individual sources and base+override pairs**. A `POSSIBLE SOURCE` result verifies service-name coverage only, **not** that the network, volume, image, environment, or data configuration is identical to the running containers. A safe production cutover still requires that comparison. No production changes have occurred.

## Third live check (2026-10-18): Vaultwarden source mismatch confirmed

The user ran the corrected layered Compose service-name discovery:

- `/docker/rustdesk/compose.yml` defines exactly both current RustDesk services (`hbbs`, `hbbr`). Still compare full configuration before recreation.
- `/docker/vaultwarden/compose.yml` and `compose.override.yml`, both individually and combined, define **only** `application` and `tailscale`.
- The live Vaultwarden Compose project **also** has running `nginx` (`nginx-vaultwarden`) and `vaultwarden` (`vaultwarden`) services whose recorded `docker-compose.yml` source is missing. They may be legacy/orphaned service containers, but this is not proven.
- **Do not** run `docker compose up`, `down`, `--remove-orphans`, recreate, or rebuild against the current Vaultwarden files. That risks interrupting the running password manager.

Additional **read-only** recovery check: `docker/freshdock/vaultwarden_legacy_sources.py` searches bounded Compose/backup filenames under `/docker/vaultwarden` (excluding data and secrets directories) and tests candidate service-name definitions without showing configuration or credentials. If no matching legacy source exists, **preserve the existing running Vaultwarden and nginx containers; exclude those two from any first Freshdock cutover** until the exact configuration can be recovered or safely reconstructed in a separately approved maintenance window. No automatic update tooling should attempt to restart or change them in the interim.
