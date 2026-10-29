# Second Transmission instance: planning and safety

**Not deployed.** Based on read-only `openmediavault` inventory from 2026-10-29. The checked-in [overlay](compose.transmission-brother.yml) is only a proposal; it deliberately does not change Gluetun or Watchtower. Before production use, verify all live Compose and settings files again.

## Verified host

- The live `privacy` project lists `/docker/privacy/compose.yml`, `compose.override.yml`, `compose.amutorrent.yml` in that order.
- Existing `transmission` uses `lscr.io/linuxserver/transmission:latest`, RPC **9091**, peer port **25045**, config `/docker/privacy/transmission/data`, and download bind mount `/srv/mergerfs/data/root/downloads:/downloads`. Completed files are at `/downloads/transmission/complete`, incomplete at `/downloads/transmission/incomplete`.
- Gluetun accepts `FIREWALL_INPUT_PORTS=9091,3000,4000,9696` and `FIREWALL_VPN_INPUT_PORTS=25045`. Five current VPN namespace consumers: `transmission`, `mullvad-browser`, `amutorrent`, `prowlarr`, and standalone `trawl`.
- Watchtower runs an **exact 24-container** allowlist, and its installed verifier fails with `Unapproved additional Gluetun namespace user: trawl`. Neither `transmission-brother` nor its Tailscale sidecar exists. aMuTorrent, Prowlarr and TRAWL are also not Watchtower targets.
- Latest read-only inspection: TCP/UDP 25045 and TCP 9091 are listening in Gluetun's namespace, but **9092 is free**. The future download directory does not exist. Live `/docker/privacy/compose.override.yml` is mode `0666` (world-writable) and `/docker/privacy` is mode `2777`; audit owners, ACLs and how OMV regenerates these files before safely tightening permissions. Do not automatically `chmod -R` the privacy tree.

## Proposed isolation

- New container `transmission-brother`, separate username/password via **untracked** `/docker/privacy/transmission-brother/auth.env` (mode 0600, fields `USER` and `PASS`).
- Dedicated config `/docker/privacy/transmission-brother/data:/config` and watch folder `/docker/privacy/transmission-brother/watch:/watch`.
- Narrow download mount `/srv/mergerfs/data/root/downloads/transmission-brother:/downloads`; the original downloads, Movies, and Shows are **not** mounted into the second container.
- Preseed `/docker/privacy/transmission-brother/data/settings.json` **before first start** with `"rpc-port":9092`, `"download-dir":"/downloads/complete"`, `"incomplete-dir":"/downloads/incomplete"`, `"incomplete-dir-enabled":true`, `"peer-port-random-on-start":false`, and `"peer-port":<distinct assigned port>`. Do not copy existing credentials/settings. LinuxServer documents that `USER` and `PASS` must be provided via environment and warns not to edit `settings.json` while running.
- Distinct AirVPN-forwarded torrent peer port `TRANSMISSION_BROTHER_PEER_PORT`, never 25045. Add this port alongside 25045 in live Gluetun's `FIREWALL_VPN_INPUT_PORTS`; add RPC **9092** alongside existing values to `FIREWALL_INPUT_PORTS`. Do not expose 9092 directly on the host.
- New `tailscale-transmission-brother` sidecar serves HTTPS to `http://gluetun:9092`. It has separate Tailscale state, a one-time local secret authkey file under the ignored `/docker/privacy/ts/` directory, and no Funnel. Restrict access in Tailscale policy to the brother's user/device. Shared Gluetun routing does **not** guarantee filesystem quotas or VPN port-forward allocation.

## Required safe rollout order

1. Re-check live `/docker/privacy/compose.override.yml`, exact Gluetun and Watchtower runtime arguments, private manifest, directory ACLs, and spare RPC/peer ports. Never publish secrets. Confirm the extra AirVPN port is actually forwarded before configuring it.
2. Resolve the Watchtower group problem first. **Standalone** `trawl` currently lacks Compose source metadata and cannot safely be added to the verifier's Compose-enforced allowlist. Plan a scoped migration to the already reviewed `compose.trawl.yml` overlay, preserving Prowlarr's solver connection and a tested rollback. Do not recreate Gluetun yet.
3. **Stage new data and credentials before changing the network:** pre-create the second instance's config, credentials, and download directories with verified ownership and permissions, **without touching existing Transmission**. Validate `settings.json` syntax offline. Set the separate AirVPN peer port and obtain a dedicated Tailscale identity without printing auth secrets.
4. **Plan a Gluetun maintenance window:** retaining all existing `FIREWALL_INPUT_PORTS` / `FIREWALL_VPN_INPUT_PORTS`, add only RPC 9092 and the new forwarded peer port. Recreating Gluetun can interrupt **every** client in its namespace; verify TRAWL is now Compose-managed and prepare a grouped recovery plan before altering the VPN parent. Avoid direct public/LAN exposure of 9092.
5. Validate the complete active Compose list; append `compose.transmission-brother.yml` once and create only `transmission-brother` and `tailscale-transmission-brother` with `docker compose ... up -d --no-deps transmission-brother tailscale-transmission-brother`. Verify VPN egress, RPC 9091/9092, separate peer ports, Tailscale access and download-directory isolation **before changing Watchtower**.
6. **Last, enroll Watchtower atomically:** after all six additions exist, are healthy and have valid Compose provenance, back up the private updater Compose file, `targets.json` and installed verifier. Expand the updater's exact positional target list and root-only manifest from 24 to **30** together; install the matching verifier, then recreate **only** Watchtower. Selected additions: `amutorrent`, `prowlarr`, Compose-managed `trawl`, `tailscale-amutorrent`, `transmission-brother`, and `tailscale-transmission-brother`. The 05:00 systemd verifier must run the matching new script. Do not suppress fail-closed namespace checks.
7. Verify Watchtower's exact 30-target manifest, running command and independent verifier after enrollment. Test rollback and TRAWL response before trusting unattended updates. Watchtower **does not** guarantee health-aware VPN startup or automatic rollback.

## Rollback

Keep dated copies of live Compose files, private Watchtower config/manifest, and new Transmission config. A rollback must **only** remove the two new containers and their new Compose overlay, restore Gluetun firewall policy and Watchtower selection with the complete namespace group accounted for, and leave all torrents and the original Transmission's files unchanged. Never run `docker compose down`, `down -v`, recursive `chmod`/`chown`, or delete persistent torrent/download data. Production application and VPN restarts require separate explicit host validation; this repository does not deploy them.
