# Seerr

Media requests for Jellyfin, Sonarr and Radarr.

## Setup

- **New install:** Use the local Compose template and `.env`; persistent configuration lives in `./seerr/config`.
- **Existing Jellyseerr:** Use `migrate-from-jellyseerr.sh` with `--dry-run` before `--apply`. This is an **in-place** app migration, not a Docker/Tailscale container rename.
- **Access:** HTTPS is provided by the Tailscale sidecar. An optional Pi-hole/Nginx route can be configured separately.

**Do not delete existing app databases, Tailscale state, or Compose overlays during migration.** The migration helper refuses unverified database layouts.

[Migration commands, compatibility rules, optional DNS rename, rollback and maintenance notes](OPERATIONS.md) · [Official Seerr migration guide](https://docs.seerr.dev/migration-guide/)
