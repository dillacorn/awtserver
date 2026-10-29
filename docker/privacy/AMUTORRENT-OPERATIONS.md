# aMuTorrent + Prowlarr trial

aMuTorrent provides multi-user, browser-based torrent search and download management; Prowlarr supplies search indexes and existing Transmission remains the download engine. The two UIs serve different audiences: only aMuTorrent is shared with non-admin users.

## Current OMV observation (2026-10-29)

These are **dated host observations**, not guarantees about another installation or a future server state.

- Inspected host: `openmediavault`. Compose project `privacy` in `/docker/privacy`, with Gluetun, Transmission, Mullvad Browser and separate Tailscale sidecars. Pi-hole/nginx project is `/docker/pihole` with pinned overlays including Tailscale/IPv6 DNS.
- Trial containers `amutorrent`, `prowlarr`, and `tailscale-amutorrent` were running after the user repaired aMuTorrent's bind-mount access. Gluetun was healthy and both existing VPN-dependent applications were running.
- aMuTorrent returned HTTP 200 from `/health`; its initial setup saved `/docker/privacy/amutorrent/data/config.json`.
- Dedicated Tailscale machine `amutorrent` registered and served HTTPS to Gluetun port 4000. Local Pi-hole Compose contained the new host record, nginx passed `nginx -t`, and forced local HTTPS returned HTTP 302 with TLS verification result 0.
- The sidecar container environment no longer contained `TS_AUTHKEY` (on-disk secret state and key revocation still require separate verification).
- **Not yet verified:** admin authentication in a fresh session, indexer configuration, Prowlarr-to-Transmission searches/downloads, another user's permissions, VPN public egress, access from outside the LAN, or future certificate renewal.

### Why UID 1001 is intentional

On the inspected OMV host, `/docker/privacy/amutorrent/{data,logs}` were owned by UID 1001, GID 1000 with mode 2700 and inherited ACL entries. Running the container as UID 1000 failed with `EACCES` on `/usr/src/app/server/data/metrics.db`. `chown` returned success but ownership remained UID 1001. A targeted container-only change to `user: "1001:1000"` resulted in HTTP 200 and zero restarts at that test. Do **not** apply `chmod -R 777`, discard ACLs or recursively change unrelated Docker paths.

For any other host, inspect owners, ACLs, application user and bind mounts first; select the matching UID/GID rather than copying 1001 blindly.

## Source layout

- `docker/privacy/compose.amutorrent.yml`: optional privacy Compose overlay, not an independent stack. Its Gluetun firewall ports reflect the inspected trial only; merge with the live port list instead of replacing additional existing ports.
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
- Require aMuTorrent login before sharing access; its default is unauthenticated. Create a non-admin user with `search`, `add_downloads` and only the desired management capabilities. Do not grant `view_all_downloads`, `edit_all_downloads` or `view_logs` unless necessary.
- Restrict your brother's Tailscale access using tailnet policy as appropriate. aMuTorrent permissions do not isolate storage or enforce per-user disk quotas; shared Transmission can still fill disks.
- Transmission is already authenticated. Do not commit its password or Prowlarr's API key; configure both within aMuTorrent's authenticated Settings UI.

## Manual application integration (pending validation)

1. Confirm a private browser session prompts for aMuTorrent credentials before exposing it to other users.
2. Reach Prowlarr over an SSH local forward, not an exposed port:
   `ssh -N -L 127.0.0.1:9696:127.0.0.1:9696 root@<verified-omv-lan-ip>`.
   Visit `http://127.0.0.1:9696`, enable authentication, add and test trusted indexers.
3. In aMuTorrent, Settings > BitTorrent Integration: confirm Transmission host `127.0.0.1`, port `9091`, path `/transmission/rpc`, its existing username/password, SSL disabled for internal RPC. Enable Prowlarr with `http://127.0.0.1:9696` and the API key from Prowlarr's Settings > General; Test and Save.
4. Search for a legal/public-domain torrent or Linux distribution image, send the result to Transmission, and verify the task and finished file. **Upstream's Prowlarr-specific guide still mentions only qBittorrent/rTorrent; Transmission handoff is not treated as tested until this succeeds.**
5. Add a restricted account and test that searching/adding works but Prowlarr/admin controls and other users' download changes do not.

## Read-only operational checks

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}'
docker inspect --format '{{.Name}} {{.State.Status}} {{.Config.User}}' amutorrent prowlarr gluetun
docker exec amutorrent node -e 'require("http").get("http://127.0.0.1:4000/health",r=>{r.resume();process.exitCode=r.statusCode===200?0:1}).on("error",()=>process.exitCode=1)'
docker exec nginx-pihole nginx -t
```

After verifying the **actual** local domain and LAN IP, test nginx with a trusted TLS connection using `curl --resolve domain:443:lan-ip https://domain/health`, and Pi-hole's DNS host entry with `dig @lan-ip domain A +short`. Separately test Tailscale remote access and the application's login.

For VPN assurance, check that aMuTorrent and Prowlarr use the running Gluetun network namespace and confirm outbound egress from inside those namespaces through an independently identified VPN endpoint. Do not mistake a matching namespace for proof of VPN egress, and do not make privacy claims based on Gluetun health alone.

## Maintenance / rollback

- Back up existing live Compose overlays, `.env`, nginx site, Pi-hole settings and application data before edits. Confirm current container names, port bindings, networks, certificate paths and tailnet identity each time.
- Never rerun the one-time trial installer: it was interrupted partway through the initial Gluetun health check, and the follow-up repair was required for storage ACLs. Neither failed script belongs in a production deployment path.
- Do not restart or recreate Gluetun, Transmission or Mullvad Browser just to change the aMuTorrent application or its accounts. Changing Gluetun's firewall ports may require a maintenance interruption affecting all three.
- If a new Compose overlay fails, revert only the changed files from the recorded backup, preserve the persistent Tailscale state and aMuTorrent database, validate the restored *complete* Compose set, and recreate only affected services. Do not use `docker compose down` or delete volumes.
- Verify certificate renewal for the dedicated sidecar through `docker/tailscale-certs/renew.sh --dry-run` before relying on it. Exported cert files used by nginx need scheduled renewal and an nginx reload/restart on renewal; Tailscale Serve HTTPS renewal is independent.
