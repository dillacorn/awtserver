# Second Transmission instance: planning and safety

**Not deployed.** Based on read-only `openmediavault` inventory from 2026-10-29. The checked-in [overlay](compose.transmission-brother.yml) is only a proposal; it deliberately does not change Gluetun or Watchtower. Before production use, verify all live Compose and settings files again.

## Verified host

- The live `privacy` project lists `/docker/privacy/compose.yml`, `compose.override.yml`, `compose.amutorrent.yml` in that order.
- Existing `transmission` uses `lscr.io/linuxserver/transmission:latest`, RPC **9091**, peer port **25045**, config `/docker/privacy/transmission/data`, and download bind mount `/srv/mergerfs/data/root/downloads:/downloads`. Completed files are at `/downloads/transmission/complete`, incomplete at `/downloads/transmission/incomplete`.
- Gluetun accepts `FIREWALL_INPUT_PORTS=9091,3000,4000,9696` and `FIREWALL_VPN_INPUT_PORTS=25045`. Five current VPN namespace consumers: `transmission`, `mullvad-browser`, `amutorrent`, `prowlarr`, and standalone `trawl`.
- Watchtower runs an **exact 24-container** allowlist, and its installed verifier fails with `Unapproved additional Gluetun namespace user: trawl`. Neither `transmission-brother` nor its Tailscale sidecar exists. aMuTorrent, Prowlarr and TRAWL are also not Watchtower targets.

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
3. Update Watchtower's verifier and exact target list *together*, including six additions: `amutorrent`, `prowlarr`, Compose-managed `trawl`, `tailscale-amutorrent`, `transmission-brother`, and `tailscale-transmission-brother` (24 to **30** targets). Only expand after every container exists, is healthy, has valid Compose sources, and is listed in the private manifest and running Watchtower command. Do not suppress fail-closed namespace checks. The installed 05:00 systemd verifier must use the matching policy.
4. Pre-create the second instance's config, credentials, and download directories with proper ownership and permissions, **without touching existing Transmission**. Validate `settings.json` syntax offline.
5. Plan Gluetun firewall updates and a maintenance window: recreating Gluetun can interrupt **all** namespace clients and strand standalone TRAWL if migration was skipped. Preserve original input and VPN port lists; never replace their values with only the new port.
6. Validate the complete active Compose list, then add `compose.transmission-brother.yml` as another final overlay and create only the new services with `docker compose ... up -d --no-deps transmission-brother tailscale-transmission-brother`. Validate VPN egress, RPC 9091/9092, separate peer ports, Tailscale access, and both directory boundaries.
7. Verify Watchtower's exact 30-target manifest, running command and verifier after enrollment. Test rollback and TRAWL response before trusting unattended updates. Watchtower does **not** guarantee health-aware VPN startup or automatic rollback.

## Rollback

Keep dated copies of live Compose files, private Watchtower config/manifest, and new Transmission config. A rollback must **only** remove the two new containers and their new Compose overlay, restore Gluetun firewall policy and Watchtower selection with the complete namespace group accounted for, and leave all torrents and the original Transmission's files unchanged. Never run `docker compose down`, `down -v`, recursive `chmod`/`chown`, or delete persistent torrent/download data. Production application and VPN restarts require separate explicit host validation; this repository does not deploy them.
