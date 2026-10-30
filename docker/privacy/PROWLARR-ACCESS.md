# Prowlarr private HTTPS management

Prowlarr remains the existing `privacy/prowlarr` service behind Gluetun on port 9696. The new `tailscale-prowlarr` machine adds private HTTPS for management without changing Prowlarr's VPN routing, Gluetun ports, Transmission, aMuTorrent, or SSH forwarding.

- Remote: `https://prowlarr.<verified-tailnet>.ts.net` via Tailscale Serve; public Funnel disabled.
- Local: the **same** URL resolves through Pi-hole's existing `FTLCONF_dns_hosts` to the NAS LAN IP and the `nginx-pihole` HTTPS reverse proxy.
- The auth key is stored only temporarily at `/docker/privacy/ts/prowlarr/authkey.env` with root ownership and mode 0600. Never paste into chats/issues/commits. The persisted Tailscale identity lives at `/docker/privacy/ts/prowlarr/state`. Use a normal non-ephemeral key, and rotate or revoke it after successful registration.
- Prowlarr's existing login must remain enabled. Tailscale limits network reachability; it does not replace Prowlarr account authentication.

## Source files

- `docker/privacy/compose.prowlarr-access.yml`: new sidecar only. Becomes **seventh** overlay after the existing six privacy files.
- `docker/pihole/compose.prowlarr.yml`: nginx certificate mount only. Becomes the **last** Pi-hole overlay after its active files.
- `docker/pihole/conf.d/prowlarr.conf`: template, never deploy with the example hostname unchanged.
- `docker/privacy/setup_prowlarr_access.py`: guarded `--check` and `--apply`; the templates are supplied through `--templates`.

The setup reads **current Docker labels**, the complete active Pi-hole/nginx Compose file set, and the existing aMuTorrent tailnet identity. It never assumes a static LAN IP or the exact Pi-hole Compose overlay list. It requires a unique existing aMuTorrent `FTLCONF_dns_hosts` line. Pi-hole v6 treats that setting as read-only when provided via the environment, so the script makes a single exact source edit with an on-disk root-only backup rather than attempting to change the record through the Pi-hole UI.


**First read-only preflight (2026-10-29 local):** The original helper stopped without changing the host because it assumed a container called `dnsproxy`. The operator's subsequent read-only Docker inspection confirmed that `pihole` and `nginx-pihole` share the same five Compose files (`compose.yml`, `compose.override.yml`, `compose.tailscale-dns.yml`, `compose.ipv6-dns.yml`, and `compose.amutorrent.yml`); the single Pi-hole namespace dependent is named `dnsproxy-quad9`. The revised helper discovers the dependent dynamically and requires an approved service identity and matching Compose provenance before any write. The service label is **not yet verified** from the operator's output; rerun the read-only preflight to confirm it.

**Second read-only preflight (2026-10-29 local):** Source hashes and Python syntax passed, and the dynamically matched Quad9 service check advanced to the Pi-hole Compose-file metadata check. The live DNS host source contains an extended POSIX ACL. The original installer stopped safely with `Pi-hole Compose DNS source has an extended ACL; refuse atomic replacement`; no server files or containers were changed. The new implementation copies and byte-verifies **all** original file extended attributes (including `system.posix_acl_access`) and original owner, group, and mode onto the staged file before atomic replacement. The same mechanism applies to rollback. Any ACL copy error fails closed before replacing the source file. Added Linux ACL regression tests run in CI. **This revision has not been applied to the host; rerun `--check` and report any next guard failure rather than bypassing permissions.**

**Third read-only preflight (2026-10-29 local):** The operator's verified pinned command reported **READ-ONLY PASS**. The source file `/docker/pihole/compose.yml` has an extended ACL, which the revised script will preserve. All six privacy Compose files and the existing Gluetun/Prowlarr relationship passed. Pi-hole and nginx provenance was confirmed as `compose.yml`, `compose.override.yml`, `compose.tailscale-dns.yml`, `compose.ipv6-dns.yml`, and `compose.amutorrent.yml`. The live network namespace dependent is **container** `dnsproxy-quad9`, **Compose service** `dnsproxy`. The local HTTPS domain is `prowlarr.time-puffin.ts.net`; its existing aMuTorrent A record is the model for adding one Pi-hole DNS record. The operator has **not** created the root-private Prowlarr auth-key file. There were **no writes or container changes**. Before applying, the installer was further adjusted to stop the verified DNS proxy dependent before recreating Pi-hole, then force-recreate the proxy against the new namespace, followed by nginx; the order is regression-tested. Deployment remains pending.

## Host preparation

First run **only `--check`** and inspect the output. It makes no changes. The server must report existing Gluetun/Prowlarr running, valid six-file privacy configuration, current Pi-hole/nginx Compose provenance, exactly one known DNS source line, a valid nginx network path, and exactly one approved DNS proxy sharing the Pi-hole namespace. The current OMV host reports its dependent as `dnsproxy-quad9`, **not** `dnsproxy`. The helper locates it by the actual namespace relationship and requires that its Compose service and file provenance match the live Pi-hole stack. **Stop if any check fails.** This is not a server-port-forwarding or SSH-configuration fix.

Before apply, place the Tailscale auth key in this **host-only** file:

```bash
umask 077
install -d -m 0700 /docker/privacy/ts/prowlarr
read -r -s -p 'Prowlarr Tailscale auth key: ' key
printf '\n'
printf 'TS_AUTHKEY=%s\n' "$key" > /docker/privacy/ts/prowlarr/authkey.env
unset key
chmod 0600 /docker/privacy/ts/prowlarr/authkey.env
```

Do not show the key on the terminal or paste it into GitHub. `--apply` must be run **only after successful host preflight**. It first creates the Tailscale sidecar and verifies its identity and exported cert; only then does it modify Pi-hole/nginx. An existing site or sidecar is treated as a collision, not overwritten.

## DNS and rollback boundary

Pi-hole uses `dnsproxy` in its network namespace. A Pi-hole recreation invalidates that dependent namespace, so the script checks for **exactly one** dependent DNS proxy (`dnsproxy-quad9` on this OMV host), verifies its actual Compose service identity, and stops it before replacing Pi-hole. When adding the record, the script recreates **only** Pi-hole, then the verified DNS proxy Compose service, then nginx, using the full active Pi-hole Compose files plus the new certificate overlay. DNS service can be briefly interrupted. It verifies Pi-hole answers the new A record locally and the HTTPS endpoint returns through nginx with a trusted certificate.

The original Pi-hole Compose file is backed up under `/root/awtserver-prowlarr-access/<timestamp>-<pid>/`. If validation fails after the DNS stage, the script attempts to restore that original file, remove only its newly created site/overlay, and recreate the same three Pi-hole components. The Tailscale sidecar is intentionally retained for diagnostics. A failure before the Pi-hole stage never recreates DNS. No script can guarantee recovery from independent failures during restart: inspect the output and backup if rollback cannot be confirmed.

**Host installation confirmed (2026-10-30):** The operator's `--apply` run completed with `PASS` for dedicated `tailscale-prowlarr` registration and HTTPS certificate export, local Pi-hole DNS/nginx trusted HTTPS verification, and preservation of existing privacy services and VPN. The bootstrap key was cleared from its local file and running container environment. Private address: `https://prowlarr.time-puffin.ts.net`. Root-only Pi-hole backup: `/root/awtserver-prowlarr-access/20261030T032146Z-1523486`. The installed seventh privacy Compose overlay is `/docker/privacy/compose.prowlarr-access.yml` and the sixth Pi-hole overlay is `/docker/pihole/compose.prowlarr.yml`; retain **all seven privacy files and all six Pi-hole files** for future Compose operations. These are the helper's reported successful checks; opening the remote page from a separate Tailscale client has **not** been user-confirmed. The root-host certificate renewal script and Watchtower strict target manifest were not changed by this deployment. This GitHub PR is still unmerged; host deployment and GitHub merges are separate operations.

## Renewal and monitoring

The private Tailscale Serve certificate renews separately from the exported nginx cert files. The exported Prowlarr cert must be included in the host's verified weekly `/docker/tailscale-certs/renew.sh` configuration after successful setup. Do not blindly replace the live renewal script. The new sidecar is not automatically enrolled in the existing strict 28-target Watchtower policy; check policy scope separately before changing it.
