# aMuTorrent + Prowlarr trial

aMuTorrent provides multi-user, browser-based torrent search and download management; Prowlarr supplies search indexes and existing Transmission remains the download engine. The two UIs serve different audiences: only aMuTorrent is shared with non-admin users.

## 2026-10-29 TRAWL migration completed (host-confirmed)

The operator ran the guarded `migrate_trawl.py` helper. After the first attempt's immediate health check failed and reverted, the corrected bounded-wait helper successfully created `trawl` as a **Compose-managed** service in project `privacy`, sharing the unchanged Gluetun namespace. Docker inspect reports project/service `privacy`/`trawl`, and `http://127.0.0.1:8191/health` returned `"status":"ok"` with one live browser worker. Gluetun and Transmission container IDs were unchanged.

The original container `trawl-standalone-backup-20261029t172518z` was identity-checked and removed after successful integration testing. Its root-only Docker inspection backup remains at `/root/awtserver-trawl-migration/trawl-standalone-backup-20261029t172518z.json`. The live overlay was installed at `/docker/privacy/compose.trawl.yml`. The privacy directory and `compose.override.yml` had world-write removed (`2775`/`0664`), without stripping named ACL entries.

**Functional verification passed:** the operator's read-only Prowlarr API check confirmed saved `cloudflare` tags on the TRAWL proxy and 1337x indexer; a 1337x `ubuntu` search returned **80 results**; recent TRAWL logs contained **one `request.success` and zero `request.failure` events**. The stopped original container **was subsequently removed** after matching its ID against the root-only saved Docker inspection, checking it was exited with restart disabled, and confirming the replacement TRAWL and Gluetun were healthy. The saved inspection JSON remains. Original Transmission and Gluetun were not changed. **Later October 29 host update:** Watchtower was successfully enrolled from 24 to 28 targets (adding `amutorrent`, `prowlarr`, Compose-managed `trawl`, and `tailscale-amutorrent`), with no other application container ID/state changes. The installed independent verifier reported `28 healthy targets` twice and the 05:00 timer remained active. The root-private enrollment backup is `/root/awtserver-watchtower-enrollment/20261029T181404Z`. No second Transmission was deployed; the first unattended update of the expanded policy remains unobserved. See [Watchtower operations](../watchtower/OPERATIONS.md).

## Current OMV observation (2026-10-29)

These are **dated host observations**, not guarantees about another installation or a future server state.

- Inspected host: `openmediavault`. Compose project `privacy` in `/docker/privacy`, with Gluetun, Transmission, Mullvad Browser and separate Tailscale sidecars. Pi-hole/nginx project is `/docker/pihole` with pinned overlays including Tailscale/IPv6 DNS.
- Trial containers `amutorrent`, `prowlarr`, and `tailscale-amutorrent` were running after the user repaired aMuTorrent's bind-mount access. Gluetun was healthy and both existing VPN-dependent applications were running.
- aMuTorrent returned HTTP 200 from `/health`; its initial setup saved `/docker/privacy/amutorrent/data/config.json`.
- Dedicated Tailscale machine `amutorrent` registered and served HTTPS to Gluetun port 4000. Local Pi-hole Compose contained the new host record, nginx passed `nginx -t`, and forced local HTTPS returned HTTP 302 with TLS verification result 0.
- The sidecar container environment no longer contained `TS_AUTHKEY` (on-disk secret state and key revocation still require separate verification).
- A standalone `trawl` container was started using `ghcr.io/germondai/trawl:1.9.3-baseline` and `--network container:gluetun`. Its `/health` returned OK. Direct FlareSolverr-compatible `/v1` request solved the 1337x Cloudflare challenge with HTTP 200 and a `cf_clearance` cookie. Prowlarr sent successful proxy-ping requests to TRAWL; **these were only proxy tests**, not proof of a working 1337x indexer.
- All five privacy containers (`gluetun`, `transmission`, `amutorrent`, `prowlarr`, `trawl`) were confirmed in the same Linux network namespace. Gluetun was healthy, the observed route to an external IPv4 address used `tun0`, and the VPN exit address differed from the host's public address. This confirms **observed routed VPN egress**, not a full DNS-leak/kill-switch test; public IPs are deliberately omitted.
- The user confirmed **1337x saved and enabled (green status check)** in the Prowlarr indexer list and subsequently reported that **aMuTorrent's Prowlarr API connection was configured and working**. These are application UI/user checks, not independent API or end-to-end download tests.
- Later **read-only Prowlarr API inspection** revealed that saved 1337x had **no tags**, did **not match any FlareSolverr proxy**, and direct searches for two queries returned **zero results**. The documented correction is selecting the same `cloudflare` tag on both the 1337x indexer and TRAWL proxy, saving each, and testing the real search. The user later confirmed that saving the matching indexer tag fixed searching on 2026-10-29; no fresh direct Prowlarr API output was provided.
- **Not yet verified:** admin authentication in a fresh session, independently observed search results from 1337x in aMuTorrent, successful aMuTorrent → Transmission download, another user's permissions, access from outside the LAN as a non-admin, DNS-leak/kill-switch testing, or exported certificate renewal.

### Why UID 1001 is intentional

On the inspected OMV host, `/docker/privacy/amutorrent/{data,logs}` were owned by UID 1001, GID 1000 with mode 2700 and inherited ACL entries. Running the container as UID 1000 failed with `EACCES` on `/usr/src/app/server/data/metrics.db`. `chown` returned success but ownership remained UID 1001. A targeted container-only change to `user: "1001:1000"` resulted in HTTP 200 and zero restarts at that test. Do **not** apply `chmod -R 777`, discard ACLs or recursively change unrelated Docker paths.

For any other host, inspect owners, ACLs, application user and bind mounts first; select the matching UID/GID rather than copying 1001 blindly.

## Source layout

- [Manual application setup](AMUTORRENT-SETUP.md): first-time web UI steps, Prowlarr authentication, TRAWL proxy and tag setup, 1337x troubleshooting, aMuTorrent wizard and restricted users.
- `docker/privacy/compose.amutorrent.yml`: optional privacy Compose overlay, not an independent stack. Its Gluetun firewall ports reflect the inspected trial only; merge with the live port list instead of replacing additional existing ports.
- `docker/privacy/compose.trawl.yml`: Compose-managed TRAWL service. The OMV operator confirmed migration of `trawl` to the `privacy` project; the live overlay at `/docker/privacy/compose.trawl.yml` must be included in future effective Compose configurations. Port 8191 stays internal and does not need a Gluetun input firewall exception for shared-loopback traffic.
- `docker/pihole/compose.amutorrent.yml`: nginx certificate directory overlay, to append to the **complete** existing Pi-hole Compose file list.
- `docker/pihole/conf.d/amutorrent.conf`: local HTTPS proxy example (replace the example domain).
- `docker/pihole/compose_example.yml`: includes an example DNS host record and certificate mount for a clean deployment.
- `docker/tailscale-certs/renew.sh`: optional sidecar certificate renewal, requiring validation before use on the host.

**These files document the trial. They were not copied verbatim from the live server.** Local secrets, Tailscale state/certificates, database/logs and Prowlarr data are ignored by `docker/privacy/.gitignore`; the existing tracked `docker/privacy/.env` must NEVER be overwritten with the host's private `.env` or copied verbatim into a commit. On the host, inspect `docker inspect ... com.docker.compose.project.config_files`, the real `.env` `COMPOSE_FILE`, existing overlay, nginx site, cert mounts, and DNS host list before considering any deployment from GitHub. Do not run `docker compose up -d` using a partial file list, and do not overwrite a working live overlay.

## Connection and security model

```text
Tailscale client -> tailscale-amutorrent HTTPS Serve -> gluetun:4000 -> aMuTorrent
Home LAN client -> Pi-hole local A record -> nginx-pihole:443 -> gluetun:4000
aMuTorrent -> Prowlarr HTTP on 127.0.0.1:9696 (same Gluetun network namespace)
aMuTorrent -> Transmission RPC on 127.0.0.1:9091 (same namespace)
```

- Keep `4000` un-published to LAN/WAN. Prowlarr `9696` is host-loopback-only for SSH forwarding. Public Tailscale Funnel is disabled.
- Require aMuTorrent login before sharing access; its default is unauthenticated. For a limited non-admin user, enable only `search`, `add_downloads`, `pause_resume`, and optionally `assign_categories`. Leave `view_all_downloads`, `edit_all_downloads`, `view_logs`, `manage_categories`, `clear_history`, and `view_history` disabled. In aMuTorrent v3.9.8 the history API does not apply per-user ownership filtering. See the [manual restricted-user checklist](AMUTORRENT-SETUP.md#7-in-amutorrent-create-a-limited-but-usable-account).
- Restrict your brother's Tailscale access using tailnet policy as appropriate. aMuTorrent permissions do not isolate storage or enforce per-user disk quotas; shared Transmission can still fill disks.
- Transmission is already authenticated. Do not commit its password or Prowlarr's API key; configure both within aMuTorrent's authenticated Settings UI.

## Manual application configuration (pending final validation)

Read [aMuTorrent, Prowlarr and TRAWL manual setup](AMUTORRENT-SETUP.md) **before** attempting search/download testing. This is the operator procedure for every required web-interface action, including a phone-only Prowlarr admin route via the existing remote Mullvad Browser, secure login, TRAWL's FlareSolverr-compatible proxy, saved matching `cloudflare` tags, 1337x indexer, the aMuTorrent wizard, Transmission RPC, API key, and restricted accounts. **Proxy ping and direct TRAWL 1337x success do not establish Prowlarr's end-to-end search or aMuTorrent's Transmission handoff.**

## Read-only operational checks

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}'
docker inspect --format '{{.Name}} {{.State.Status}} {{.Config.User}}' amutorrent prowlarr gluetun
docker exec amutorrent node -e 'require("http").get("http://127.0.0.1:4000/health",r=>{r.resume();process.exitCode=r.statusCode===200?0:1}).on("error",()=>process.exitCode=1)'
docker exec nginx-pihole nginx -t
```

After verifying the **actual** local domain and LAN IP, test nginx with a trusted TLS connection using `curl --resolve domain:443:lan-ip https://domain/health`, and Pi-hole's DNS host entry with `dig @lan-ip domain A +short`. Separately test Tailscale remote access and the application's login.

For VPN assurance, verify all active consumers including TRAWL share Gluetun's network namespace, then inspect `ip -4 route get 1.1.1.1` from Gluetun's network namespace and compare host versus Gluetun external IPs using a trusted endpoint. The inspected host passed these checks on 2026-10-29; check again after network/Compose changes. Do not interpret them as a full DNS-leak, IPv6-leak, or kill-switch verification. TRAWL log `proxy=false` means no additional HTTP/SOCKS proxy, **not** that Gluetun was bypassed.

## aMuTorrent /Movies and /Shows category warnings (host mount verified 2026-10-29)

**Observed 2026-10-29:** The aMuTorrent `amutorrent` container runs UID/GID `1001:1000` in privacy Compose, but its only original bind mounts are `/docker/privacy/amutorrent/data` and `logs`. Transmission has the mergerfs `/Movies` and `/Shows` mounts already. aMuTorrent shows a yellow path configuration warning because its upstream category modal calls `/api/config/check-path`, which tests existence and **read/write** access **inside the aMuTorrent container**. A read-only mount does not satisfy this check.

The host now has a dedicated `/docker/privacy/compose.amutorrent-media.yml` overlay that adds only two writable bind mounts to **aMuTorrent**, `/srv/mergerfs/data/root/Movies:/Movies:rw` and `/srv/mergerfs/data/root/Shows:/Shows:rw`. Transmission, Gluetun, qBittorrent, Watchtower, Prowlarr, TRAWL, Pi-hole, media files, and the default Transmission download path remain untouched.

`mount_amutorrent_media.py --overlay-source ... --check` is read-only and verifies current OMV host/root identity, four effective live Compose files, existing and candidate service equivalence (only two mounts differ), original Transmission mount source paths, UID/GID, Gluetun health, and absence of prior media overlay. `--apply` stages the exact new overlay and runs Compose **only for `amutorrent`** with `--no-deps --no-build --pull never`. It verifies both runtime mounts, Node read/write access, the application HTTP health endpoint, and that all other container IDs/states are unchanged. On failure it attempts a scoped aMuTorrent-only Compose rollback and retains the overlay if rollback cannot be confirmed.

**Important:** Adding these mounts gives aMuTorrent real write access to those libraries. Continue to restrict its non-admin users' destructive/download-management permissions. Do not adjust mergerfs ACLs, ownership, or mode as part of this fix. A new `compose.amutorrent-media.yml` must be included in all **subsequent complete privacy Compose file lists**, after `compose.trawl.yml`, as long as the fix is active; do not run bare Compose without verifying the pinned live set.

**Operator-confirmed application (2026-10-29):** The pinned sources and Python syntax verified. Both `--check` and `--apply` reported the original four-file effective Compose services unchanged except the two aMuTorrent mounts; after the scoped recreation, aMuTorrent confirmed both paths readable/writable, application health passed, and all other container identities and states were preserved. The live overlay is now `/docker/privacy/compose.amutorrent-media.yml`. **Whether the yellow warnings disappeared in the browser is not yet confirmed**; refresh the aMuTorrent categories to check. The unmounted `/downloads/transmission/complete` default category path may also need a **separate** mount if a warning appears; no broad `/downloads` write access was added.

## Jellyfin access to completed torrents (verified 2026-10-29)

The existing Transmission `/downloads` mount points to mergerfs `/srv/mergerfs/data/root/downloads`. With Transmission's completion location `/downloads/transmission/complete`, the actual files live under `/srv/mergerfs/data/root/downloads/transmission/complete`. The independent `jellyfin` Compose project mounts that directory **read-only** at `/data/Incoming`; the Jellyfin user-facing library is **Downloads**. This was applied to the live Jellyfin `compose.override.yml` (not the GitHub optional overlay), and `RW: false` was verified. See [Jellyfin downloads operations](../jellyfin/OPERATIONS.md) for exact live file order, verification, rollback and library setup. Do not change Transmission paths or storage ownership as part of this Jellyfin-only mount.

## Maintenance / rollback

- Back up existing live Compose overlays, `.env`, nginx site, Pi-hole settings and application data before edits. Confirm current container names, port bindings, networks, certificate paths and tailnet identity each time.
- Never rerun the one-time trial installer: it was interrupted partway through the initial Gluetun health check, and the follow-up repair was required for storage ACLs. Neither failed script belongs in a production deployment path.
- Do not restart or recreate Gluetun, Transmission or Mullvad Browser just to change the aMuTorrent application or its accounts. Changing Gluetun's firewall ports may require a maintenance interruption affecting all three.
- The current standalone `trawl` has `--network container:gluetun`, not Compose ownership. If Gluetun is recreated, that standalone container may remain tied to an obsolete namespace and must be revalidated. For later Compose migration, inspect the running container, ports and project first; create a rollback plan, then replace it with the optional `compose.trawl.yml` service **under explicit host authorization**. Do not use `docker compose down` or delete TRAWL while it is still serving Prowlarr.
- If a new Compose overlay fails, revert only the changed files from the recorded backup, preserve the persistent Tailscale state and aMuTorrent database, validate the restored *complete* Compose set, and recreate only affected services. Do not use `docker compose down` or delete volumes.
- Verify certificate renewal for the dedicated sidecar through `docker/tailscale-certs/renew.sh --dry-run` before relying on it. Exported cert files used by nginx need scheduled renewal and an nginx reload/restart on renewal; Tailscale Serve HTTPS renewal is independent.
