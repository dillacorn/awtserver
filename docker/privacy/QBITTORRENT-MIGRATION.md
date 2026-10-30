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

## Validated host preflight (operator output, October 30, 2026)

- `docker compose config --format json` over all four live privacy files confirms `gluetun`, `transmission`, `amutorrent`, `prowlarr`, and `trawl`, and no `qbittorrent` service yet.
- In Gluetun's current namespace, ports **8080** and **25046** have no bound socket; 9091/tcp and 25045/tcp+udp are occupied. A socket scan alone is not proof that Gluetun's firewall accepts a port.
- `/docker/watchtower-fork/watchtower_verify.py` references Transmission but not qBittorrent. Source review confirms the verifier rejects an unapproved Gluetun namespace child, including a stopped one.
- All **305** `*.torrent` filenames have matching `*.resume` filenames. Previously counted extra files were unrelated extensions. The counts still do **not** prove each payload's on-disk integrity or completion.

## Offline initialization before any VPN cutover

The checked-in `stage_qbittorrent.py` offers a read-only `--check` and a guarded `--apply` that runs only the isolated initializer, then stops it. Its source overlay is digest-checked; changes to existing Compose services abort. A failed partial attempt leaves staged files for inspection, rather than blindly overwriting or deleting them. Never rerun `--apply` against those files without diagnosis.

A separate `compose.qbittorrent-init.yml` defines a temporary **network-isolated** `qbittorrent-init` container. It mounts **only** `/docker/privacy/qbittorrent/config` and publishes no ports. No download/media mounts and no Gluetun dependency. It is expressly **not** the final download client; do not add it to Watchtower, aMuTorrent, or Tailscale. Never run it simultaneously with the final `qbittorrent` service, because they share config state.

Before starting it, validate the complete *existing four-file* Compose set and then compare the five-file effective Compose JSON: all existing service definitions must be byte/semantic-equal and only `qbittorrent-init` may be added. Verify the new host config directory is empty and not a symlink, and back up it if it already contains real data rather than replacing files. Pull the exact intended image, record its digest, then run only the initializer with `docker compose ... up -d --no-deps qbittorrent-init`. Validate that its network mode is `none`, its `/config` bind mount is the expected directory, and that it writes `qBittorrent/qBittorrent.conf`. After config initialization stop the initializer gracefully. Do not display its startup logs without redacting the generated temporary WebUI password.

**Stop point:** Do not launch the final Gluetun-attached `qbittorrent` yet. The Watchtower verifier's exact target/namespace policy would reject it while the existing Transmission is enrolled. Continue with torrent inventory, migration backups, and a coordinated Watchtower cutover.

## Overlay and port plan

The candidate `compose.qbittorrent.yml` adds only the new service; it does not modify Gluetun, Transmission, Tailscale, or aMuTorrent. It intentionally requires two operator-supplied, verified free **staging** ports and must be appended to all four live Compose files. No host ports are published; the candidate shares Gluetun's network namespace. Create and permission-check the dedicated `/docker/privacy/qbittorrent/config` directory first. Preserve exact existing download/media mounts and original ownership.

The final qBittorrent candidate explicitly uses the already-allowed Gluetun ports **9091** (WebUI) and **25045** (peer). These conflict with running Transmission and therefore belong ONLY to the coordinated cutover after Transmission stops. The separate Tailscale machine must be configured independently, and its hostname does not inherit or rename the existing Transmission machine.

Before any `up`, obtain `docker compose ... config --format json` for both the original four-file and candidate five-file sets. Compare each preexisting service for exact equality. Confirm no existing container would be recreated, and verify that adding a Gluetun namespace child will not break Watchtower's fail-closed verifier.

## Reversible Transmission disablement and aMuTorrent directory warnings

The user wants **Transmission temporarily disabled for a qBittorrent trial**, not removed. During the coordinated cutover, after a verified consistent full backup of the Transmission state and the qBittorrent import is ready, record the current Transmission Docker restart policy and stop only Transmission (reversible `docker update --restart no transmission`, then a bounded `docker stop`). Preserve its entire `/docker/privacy/transmission/data` directory, original Compose service, and its Tailscale machine. **Do not stop Transmission now**: the existing Watchtower manifest still lists it and will fail until the 29-target policy is installed. Revert by restoring its recorded restart policy, stopping qBittorrent to release 9091/25045, then starting Transmission and verifying RPC; the new 29-target Watchtower policy must first be reversed to match the restored fleet.

The aMuTorrent category warning is **independent** of torrent-client RPC. Upstream `server/modules/configAPI.js` uses `configTester.testDirectoryAccess(..., {checkOnly:true})` and `CategoryModal.js` warns when the path is missing read **or write** access. Since aMuTorrent UID 1001:1000 does not currently mount `/Movies` and `/Shows`, its warnings are expected. A read-only mount would **not** satisfy both permission checks.

`docker/privacy/compose.amutorrent-media.yml` appends only `/srv/mergerfs/data/root/Movies:/Movies:rw` and `/srv/mergerfs/data/root/Shows:/Shows:rw` to aMuTorrent. `mount_amutorrent_media.py --check` verifies the existing four-file effective Compose set and matching Transmission media mounts without writes. `--apply` adds this exact overlay and recreates **only** aMuTorrent with a best-effort aMuTorrent-only rollback if verification fails. Verify the container's UID 1001:1000 read/write permissions and category warnings after refresh; **never change the default downloads path**. Because the mounts grant aMuTorrent actual media write permissions, keep account permissions restricted and verify them before any multi-user rollout. When future privacy Compose operations run, include this **fifth** live overlay along with the first four, and append the qBittorrent and Tailscale overlays in the reviewed order.

## New Tailscale machine, Pi-hole, and Watchtower (staged, not applied)

The operator chose a **new** Tailscale machine `qbittorrent` while retaining the existing `transmission` machine until comfortable. The candidate `compose.tailscale-qbittorrent.yml` has an independent `/docker/privacy/ts/qbittorrent/state` volume and Tailscale Serve backend `http://gluetun:9091` (Funnel disabled). The new auth key belongs **only on the host** in `/docker/privacy/ts/qbittorrent/authkey.env`, root-owned mode 0600 with `TS_AUTHKEY=...` and a non-ephemeral key as desired. Never paste keys into chat or GitHub. Once registered, remove the key from the running container environment on a controlled recreate while keeping the Tailscale state volume and `TS_AUTH_ONCE=true`.

The cutover candidate qBittorrent uses WebUI port **9091** and peer port **25045**, *both currently occupied by Transmission*. This intentionally reuses Gluetun's established port and AirVPN forwarding without recreating Gluetun. Do not start qBittorrent until Transmission stops and the data snapshot is preserved. The offline initializer used ports 8080/25046 only while `network_mode: none`; that is not the production configuration. Enable qBittorrent WebUI login and validate allowed Host/Origin headers for local and Tailscale HTTPS **without disabling CSRF protection**. aMuTorrent must be reconfigured to qBittorrent's API after verified RPC/WebUI reachability; it does not migrate automatically.

For Pi-hole, `docker/pihole/compose.qbittorrent.yml` stages **only** the nginx certificate bind mount. `docker/pihole/conf.d/qbittorrent.conf.example` is a non-deployable nginx site template. A host-specific guarded renderer will be needed to add exactly one new local `qbittorrent.<tailnet>` DNS entry to the **existing** `FTLCONF_dns_hosts` value. Do not replace or truncate the other entries, change DNS upstreams or Pi-hole ACLs, or deploy a partial Compose file list. Obtain the exact running Pi-hole/nginx Compose provenance and the certificate directory first. Generate the new file certificate using the sidecar Tailscale identity, then run `nginx -t` before reloading/recreating nginx. The candidate `docker/tailscale-certs/renew.sh` includes the new sidecar certificate; do not install it on the host before verifying the existing installed renewer and its schedule.

Watchtower is currently an exact **28-container** policy and rejects new, unselected Gluetun clients. The candidate `docker/watchtower/watchtower_verify_qbittorrent.py` supports the original 24, current 28 and proposed qBittorrent 29 exact-target policies; retiring the old unselected Tailscale machine does not alter the 29-target policy. The interim 29 replaces `transmission` with `qbittorrent` and adds `tailscale-qbittorrent`. The existing `tailscale-transmission` machine was **not in the original 28 Watchtower targets**, so it can remain running for rollback without falsely describing it as enrolled. The dedicated `enroll_qbittorrent_29.py` has a read-only `--check` and a guarded `--apply` **only after torrent migration and network checks**; it updates Watchtower's private manifest/Compose/verifier and recreates only Watchtower, with backups. Keeping a stopped Transmission container briefly for rollback is explicitly tolerated by the interim verifier, but its network-parent references still require careful review before future Gluetun updates.

The standalone read-only `preflight_qbittorrent_integrations.py` gathers live Pi-hole Compose provenance, the shape of the DNS hosts environment, nginx certificate mounts, Watchtower target identities/hashes and initial Tailscale key-file presence **without printing secrets**. Run it before writing any Pi-hole, Watchtower or Tailscale changes.

**Do not deploy the sidecar, update Watchtower, restart Pi-hole, or stop Transmission during this planning stage.** A coordinated cutover script must ensure backup/payload verification and fail-closed rollback across all affected projects.

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
