# Seerr

Seerr is the maintained media-request application for Jellyfin, Sonarr and Radarr. It succeeds Jellyseerr and Overseerr.

## New deployments

- Image: `ghcr.io/seerr-team/seerr:v3.5.0`
- Database: SQLite under `/app/config/db/db.sqlite3`
- Configuration bind mount: `./seerr/config:/app/config` (the image runs as UID/GID 1000)
- Service: `seerr`, Docker `init: true`
- Tailscale sidecar: `tailscale-seerr`, persistent state in `./ts/state`
- Tailscale Serve: HTTPS to `http://127.0.0.1:5055` (tailnet only)

Edit `.env` for the new installation, populate your Tailscale authentication key locally if necessary, ensure the config mount is writable for UID/GID 1000, then use the Compose template. `compose.local-webapps.yml` is an optional LAN Nginx backend overlay. Never commit keys or reuse the same Tailscale state simultaneously in two containers.

## Existing Jellyseerr users: migration script

`migrate-from-jellyseerr.sh` upgrades **the supported `/docker/jellyseerr` Compose installation in place**. It retains the existing Compose project/service (`jellyseerr`), container (`jellyseerr`), and Tailscale sidecar (`tailscale-jellyseerr`) so existing HTTPS and integrations continue to point at the same node. **It does not rename Docker containers or move the live project to `/docker/seerr`.** This new directory is a clean-install template, not a file tree to copy over the existing project.

Supported source: running `fallenbagel/jellyseerr` with the expected Compose service and `.env` settings, SQLite containing a valid `user` and `media_request` table, and a shared `tailscale` network namespace. If `DB_TYPE=mysql`, the script **only proceeds if the configured MariaDB database is verifiably empty**. Nonempty MySQL/MariaDB databases require a separate planned conversion: the script intentionally refuses to guess or discard their data. Unexpected Compose layout, mounts, missing state, or incompatible services also stop the migration.

On the OpenMediaVault host as root, download the script and inspect its output before applying:

```bash
curl -fsSLo /tmp/migrate-from-jellyseerr.sh \
  https://raw.githubusercontent.com/dillacorn/omv-remote-dots/main/docker/seerr/migrate-from-jellyseerr.sh
bash /tmp/migrate-from-jellyseerr.sh --dry-run
bash /tmp/migrate-from-jellyseerr.sh --apply
```

The script checks Docker identity, active Compose files including overrides, SQLite integrity, and MariaDB table inventory; stops **only** the old Jellyseerr app; makes a root-only cold backup of config, Compose, `.env`, and Tailscale state; copies the verified SQLite installation into a new config directory; switches the original Jellyseerr service to Seerr v3.5.0 with SQLite and `init: true`; starts it without restarting Tailscale or MariaDB; and checks HTTP startup and record preservation. A deployment failure attempts to restore the original Compose files and old Jellyseerr app. The old config and MariaDB data are never deleted. The script prints the backup location.

After completion, sign in using Jellyfin and confirm existing requests, users, Sonarr/Radarr integrations, and Jellyfin library sync. A passing HTTP check does not prove that all integrations work.

## URL after migration

The URL follows the **Tailscale machine name**, not the Seerr application image or Docker container name.

- **Keep the old machine name:** continue using `https://jellyseerr.<your-tailnet>.ts.net`.
- **Prefer `seerr`:** rename the *existing* Tailscale machine from `jellyseerr` to `seerr` in the Tailscale admin console, and use `https://seerr.<your-tailnet>.ts.net`. Disable automatic machine-name regeneration when setting the custom name. Keep the current Tailscale state; do **not** remove/re-register or run a second sidecar.

The migration script prints the name reported by the running Tailscale node. Tailscale Serve uses the node's certificate name and keeps the same backend port. DNS/certificates used by an **optional local Pi-hole/Nginx proxy** are separate from Tailscale Serve and may still use the old hostname until updated.

## Optional Pi-hole local DNS and Nginx rename

If you use Pi-hole's `FTLCONF_dns_hosts` overrides and a local Nginx reverse proxy, and you've already renamed the **existing** Tailscale machine to `seerr`, update that local routing explicitly. If the application has already been migrated, run:

```bash
bash /tmp/migrate-from-jellyseerr.sh --pihole-only --dry-run
bash /tmp/migrate-from-jellyseerr.sh --pihole-only --apply
```

If the Tailscale rename was done **before** migrating the app, you can opt into the local rename in the same command:

```bash
bash /tmp/migrate-from-jellyseerr.sh --dry-run --rename-pihole
bash /tmp/migrate-from-jellyseerr.sh --apply --rename-pihole
```

The optional step derives the new FQDN from the *running* Tailscale node (`seerr.<tailnet>.ts.net`), checks for a matching new cert/key, and changes the exact old hostname in the **active** Pi-hole Compose DNS override and existing Nginx config. It deliberately **keeps** the backend `tailscale-jellyseerr:5055` and current certificate **mount directory**, because an in-place application migration did not rename either. It renames the Nginx config file to `seerr.conf`, checks `nginx -t`, recreates only the `pihole` and `dnsproxy` services from the **entire active Pi-hole Compose overlay set**, checks the running DNS host environment, and reloads Nginx. Expect a short DNS interruption. Original Pi-hole/Nginx files are backed up for rollback.

### Pi-hole API password drift

Before recreating Pi-hole, the migration helper compares all active `FTLCONF_` Compose environment settings against the running container. Docker Compose represents literal `$` characters as `$$` in Compose input; its rendered JSON may retain the escaped form. The preflight therefore decodes `$$` **only when comparing** `FTLCONF_webserver_api_password` to the running password. It does not rewrite, log, or export the password. All other `FTLCONF_` settings must match exactly.

If the password still differs after escape normalization, the script refuses to proceed. This can indicate an outdated inline value or an intentional pending password change. Select the intended password and reconcile the running Pi-hole configuration and its active Compose file before retrying. Keep credentials out of terminal output, GitHub, and support logs. Do not skip the guard or recreate Pi-hole solely to rename Seerr. Re-run `--pihole-only --dry-run` after reconciliation; `--apply` must wait until all checks pass.

This automated local-DNS step has **strict compatibility guards**: it requires running Pi-hole and `nginx-pihole` and discovers the running `dnsproxy` Compose service by labels (not a fixed container name) in the expected topology; it verifies the old runtime DNS entry, source Compose values, published ports, certificate mount, and existing Nginx backend before writing. If active Compose overlays require `TAILSCALE_IP`, `PIHOLE_IPV6`, `LAN_INTERFACE`, `LAN_IPV6_SUBNET`, or `LAN_IPV6_GATEWAY`, the script recovers them from the running Pi-hole port bindings and IPv6 macvlan Docker network rather than assuming they are still exported in the user's shell. If a supplied value disagrees with the running configuration, the preflight stops without changes. If any of these differ, it stops and requires manual review. It does not replace your custom Pi-hole Compose stack with a repository example, nor does it delete old certs or Tailscale state. Check actual LAN DNS resolution and HTTPS afterward; if clients cache the old DNS record, refresh their DNS cache.

For the validated OMV layout, the intended path is:

```text
seerr.<tailnet>.ts.net -> Pi-hole LAN DNS -> OMV LAN IP -> nginx-pihole:443
                    -> tailscale-jellyseerr:5055 -> Seerr
```

## Maintenance integration after an in-place migration

The upgraded server continues using the original Compose names and state
paths. This is expected and does not prevent its MagicDNS machine from being
called `seerr`.

- The repository certificate-renewal script now falls back from
  `tailscale-seerr` to `tailscale-jellyseerr`, but only when the legacy
  sidecar still mounts the expected Tailscale state. Its exported certificates
  are renewed in `/docker/jellyseerr/ts/state/certs`. Verify with
  `/docker/tailscale-certs/renew.sh --dry-run`.
- The repository Compose-restart script detects the active Seerr service
  (including legacy `jellyseerr`) and uses the Compose project and overlay
  files recorded by the running container.
- Watchtower uses container **names**, not MagicDNS machine names. For an
  upgraded stack, keep `jellyseerr` and `tailscale-jellyseerr` in the live
  Watchtower target list. For a clean install, use `seerr` and
  `tailscale-seerr`. Preserve the existing schedule and all unrelated
  targets. Seerr itself uses SQLite; a new `mariadb_seerr` is not needed.
- Pi-hole's clean-install example assumes `tailscale-seerr:5055` and
  `/docker/seerr/ts/state/certs`. On the upgraded host, preserve the
  functioning backend `tailscale-jellyseerr:5055` and the existing
  certificate mount from `/docker/jellyseerr/ts/state/certs`; only the
  hostname and certificate filenames change when the Tailscale machine
  is renamed. Never copy the generic Pi-hole example onto a live stack.

Repository examples do not automatically update the host. The optional
`docker/seerr/update-migrated-maintenance.py` helper checks the actual
migrated Seerr/Tailscale containers, previews legacy-name corrections to the
existing renewal/restart/Watchtower files, and backs up only those files it
changes. It preserves unrelated settings and never restarts any service.
Run it with `--dry-run` first and `--apply` only after reviewing the result.
Any Watchtower Compose changes need a separate, reviewed recreation to take
effect. It does not touch Pi-hole, application data or Tailscale state.

## Recovery and limitations

If automatic rollback fails, stop and inspect the logged backup path, exact Compose files, image and container state before retrying. Do not run `docker compose down -v`, delete the original Jellyseerr/Seerr databases, or clean up unused MariaDB files until the new application and its integrations have been verified.

This script does **not** automate changing Docker service/container names, Compose project name, or the Tailscale sidecar location. Those are a separate infrastructure migration that requires reviewing reverse-proxy mounts, cert-renewal tasks, Watchtower, maintenance scripts, and persistent Tailscale state. The script intentionally favors preserving the proven live topology.

See the [official Seerr migration guide](https://docs.seerr.dev/migration-guide/) for supported product upgrades.