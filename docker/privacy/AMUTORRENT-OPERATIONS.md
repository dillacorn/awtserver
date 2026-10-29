# aMuTorrent + Prowlarr trial

aMuTorrent provides multi-user, browser-based torrent search and download management; Prowlarr supplies search indexes and existing Transmission remains the download engine. The two UIs serve different audiences: only aMuTorrent is shared with non-admin users.

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
- `docker/privacy/compose.trawl.yml`: **optional future Compose-managed TRAWL service**. The current OMV `trawl` is a standalone container, so do not activate this overlay without a migration plan. Port 8191 stays internal and does not need a Gluetun input firewall exception for shared-loopback traffic.
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

## Maintenance / rollback

- Back up existing live Compose overlays, `.env`, nginx site, Pi-hole settings and application data before edits. Confirm current container names, port bindings, networks, certificate paths and tailnet identity each time.
- Never rerun the one-time trial installer: it was interrupted partway through the initial Gluetun health check, and the follow-up repair was required for storage ACLs. Neither failed script belongs in a production deployment path.
- Do not restart or recreate Gluetun, Transmission or Mullvad Browser just to change the aMuTorrent application or its accounts. Changing Gluetun's firewall ports may require a maintenance interruption affecting all three.
- The current standalone `trawl` has `--network container:gluetun`, not Compose ownership. If Gluetun is recreated, that standalone container may remain tied to an obsolete namespace and must be revalidated. For later Compose migration, inspect the running container, ports and project first; create a rollback plan, then replace it with the optional `compose.trawl.yml` service **under explicit host authorization**. Do not use `docker compose down` or delete TRAWL while it is still serving Prowlarr.
- If a new Compose overlay fails, revert only the changed files from the recorded backup, preserve the persistent Tailscale state and aMuTorrent database, validate the restored *complete* Compose set, and recreate only affected services. Do not use `docker compose down` or delete volumes.
- Verify certificate renewal for the dedicated sidecar through `docker/tailscale-certs/renew.sh --dry-run` before relying on it. Exported cert files used by nginx need scheduled renewal and an nginx reload/restart on renewal; Tailscale Serve HTTPS renewal is independent.
