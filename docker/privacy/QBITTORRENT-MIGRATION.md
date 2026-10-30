# Transmission → qBittorrent migration (staged, not deployed)

This is a migration plan and candidate overlay for the **observed** `openmediavault` host, not a ready-to-run replacement. Never run `docker compose down`, delete `/docker/privacy/transmission`, remove torrent payloads, or use this overlay without checking the live state. The checked-in Docker files are not authoritative copies of the live server.

## Current evidence (operator output, October 29–30, 2026)

- Project: `privacy`, directory `/docker/privacy`; observed live files: `compose.yml`, `compose.override.yml`, `compose.amutorrent.yml`, `compose.trawl.yml`. Older container labels still list only the first three. Inspect the effective four-file Compose model each time.
- Containers `gluetun`, `transmission`, `amutorrent`, `prowlarr`, `trawl`, and `tailscale-transmission` were running. `qbittorrent` was absent.
- Transmission image: `lscr.io/linuxserver/transmission:latest`; UID/GID 1000:1000; uses Gluetun network namespace.
- Transmission mounts: `/docker/privacy/transmission/data:/config`, `/srv/mergerfs/data/root/downloads:/downloads`, and host Movies/Shows/AudioBooks/Books directories mounted at corresponding root paths.
- Current defaults: completed `/downloads/transmission/complete`; incomplete `/downloads/transmission/incomplete`; TCP/UDP peer port 25045; 150 global peers; 50 per torrent; ratio 3.0; five download slots; normal up/down limits 50/6250 KiB/s; alternative limits 6250/6250 KiB/s; alternative schedule 01:00–05:00 every day. Check current settings again before conversion.
- 305 files in `transmission/data/torrents`, 374 files in `transmission/data/resume`. These counts are **not** a validated torrent inventory. The counts may include unmatched and older records. Reconcile hashes, in-progress torrents, and the torrent affected by the failed move.
- Root-side pre-restart backup reported: `/docker/privacy/transmission/pre-restart.eXpgzBV6` (only `resume` and `torrents`, not a full configuration backup). Verify before relying on it.
- Watchtower's exact selected target list includes `transmission`, not `qbittorrent`. Its independent verifier checks the Gluetun namespace and may reject an extra, unselected client. **Do not start qBittorrent in Gluetun until the exact Watchtower manifest and verifier have an approved transition plan.**

## Overlay and port plan

The candidate `compose.qbittorrent.yml` adds only the new service; it does not modify Gluetun, Transmission, Tailscale, or aMuTorrent. It intentionally requires two operator-supplied, verified free **staging** ports and must be appended to all four live Compose files. No host ports are published; the candidate shares Gluetun's network namespace. Create and permission-check the dedicated `/docker/privacy/qbittorrent/config` directory first. Preserve exact existing download/media mounts and original ownership.

For staging while Transmission still runs, qBittorrent must **not** bind TCP 9091 or peer port 25045. Candidate staging ports 8080 (WebUI) and 25046 (peer) are **not confirmed free** and must be checked; the staging peer port is not forwarded. Keep all imported torrents paused until final verification.

A low-disruption *proposed* cutover reuses the already-allowed Gluetun ports: after Transmission has stopped, configure qBittorrent's WebUI for 9091 and peer port for 25045. This may preserve the existing Tailscale proxy target and avoid recreating Gluetun, but must be tested against qBittorrent's WebUI Host-header, CSRF, authentication, and aMuTorrent API settings. Do not claim the old Tailscale hostname is automatically renamed.

Before any `up`, obtain `docker compose ... config --format json` for both the original four-file and candidate five-file sets. Compare each preexisting service for exact equality. Confirm no existing container would be recreated, and verify that adding a Gluetun namespace child will not break Watchtower's fail-closed verifier.

## Data migration gates

1. Inventory the live Transmission RPC torrent hashes, progress, save paths, and labels if it responds; reconcile with on-disk `.torrent` and `.resume` files. Pay attention to content stranded by the failed file move. Do not assume a torrent disappeared simply because aMuTorrent timed out.
2. Back up the **entire** Transmission configuration, original Compose files and private Watchtower policy/verifier separately; preserve ACLs and ownership. Do not copy passwords into GitHub or chat. Verify backups before the cutover.
3. Stop Transmission **cleanly** for a consistent state snapshot. Stop qBittorrent before writing to its BT_backup directory. The documented `qui migrate transmission --dry-run` previews conversion without writes; confirm that the actual CLI version and source/target paths match the installed containers.
4. `qui migrate` supports completed Transmission torrents, preserves many resume/statistics fields, and retains source paths, but explicitly **skips unfinished torrents**. Do not silently drop them. Use a separately tested paused import plus file recheck for unfinished torrents or defer those torrents until complete. Avoid accidental re-downloads or running both clients against the same mutable payload.
5. Create `Movies` and `Shows` qBittorrent categories with save paths `/Movies` and `/Shows`. The existing default remains `/downloads/transmission/complete` for migration compatibility, unless separately approved. qBittorrent may treat imported Transmission labels as *tags*, not categories; reconcile before applying category-based moves.
6. Configure speed limits, scheduling, queueing, encryption, DHT/PEX, upload/seeding limits and a combined multi-source IP filter through qBittorrent's supported configuration/WebUI API. Verify the resulting settings after restart; do not assume Transmission's config keys are equivalent.
7. Validate counts by infohash, completed and partial payload integrity, stored paths, trackers, torrent statuses, aMuTorrent API access, direct WebUI, Tailscale HTTPS, VPN routing and kill-switch behavior, incoming peer port, and Watchtower verifier before retiring Transmission. Document any item that cannot be preserved.
8. Switch Watchtower from Transmission to qBittorrent with an exact-target manifest/verifier change; check its timer and live selected targets. No unmonitored additional Gluetun child should remain. Keep Transmission disabled/stopped, **not deleted**, until rollback no longer requires its state.

## Sources

- [LinuxServer qBittorrent Docker image](https://docs.linuxserver.io/images/docker-qbittorrent/)
- [qui Transmission migration and incomplete-torrent limitations](https://getqui.com/docs/features/client-migration/)
- [qBittorrent WebUI API](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-%28qBittorrent-5.0%29)
- [Existing aMuTorrent and Gluetun operations](AMUTORRENT-OPERATIONS.md)
- [Watchtower exact-target operations](../watchtower/OPERATIONS.md)
