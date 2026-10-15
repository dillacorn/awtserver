# Preserve Pi-hole Tailscale DNS during maintenance

## Why this matters

`docker compose up -d` can recreate an existing Pi-hole container with a **different file set**. If Tailscale or IPv6 DNS was originally configured with `-f` overlays, a later plain `docker compose up -d` can silently omit those overlays. Docker's `restart: unless-stopped` does not repair removed port bindings. When Pi-hole is the only DNS resolver advertised to remote Tailscale clients, this may appear as a total internet outage.

The two protections here serve different purposes:

- **Compose-file pin:** Prevent accidental loss of selected overlay files in ordinary bare `docker compose` commands by setting `COMPOSE_FILE` in the local, private `.env`. It does not run Compose or change currently running containers.
- **Temporary DNS rescue:** Route **only tailnet** DNS traffic destined for the server's Tailscale IP to Pi-hole's existing LAN DNS listener using reversible netfilter DNAT. Does not restart Docker, Pi-hole, or Tailscale. Remove it once the intended native port binding has been restored during a maintenance window. It is not intended as the permanent design.

No example assumes any fixed LAN IP, Tailscale IP, DNS container ID, project directory, Docker network, or residential IPv6 prefix. Inspect the **live deployment** before making changes.

## Pin the complete Compose file set (no downtime)

From the Pi-hole project directory, with the running container in its correct state, run:

```bash
python3 pin-compose-files.py --project-dir /docker/pihole
python3 pin-compose-files.py --project-dir /docker/pihole --apply
```

The first invocation is read-only. The second **only** updates `.env`, preserves existing values, makes a dated backup and validates the resolved Compose configuration before the write. It never calls `docker compose up`, Docker restart, service restart, or daemon reload. Other installations should replace `/docker/pihole` with the real project directory, and use `--container ACTUAL_NAME` if their Pi-hole container has another name.

**If the current container has already lost the intended overlays**, do not pin the broken active file set. Specify the intended full ordered set explicitly, after verifying its required environment variables:

```bash
python3 pin-compose-files.py --project-dir /docker/pihole \
  --file compose.yml \
  --file compose.tailscale-dns.yml \
  --file compose.ipv6-dns.yml
```

For this example to validate, `LAN_INTERFACE`, `LAN_IPV6_SUBNET`, `LAN_IPV6_GATEWAY`, and `PIHOLE_IPV6` must already be available from the shell environment or local `.env`. **Do not guess** these addresses. Repeat with `--apply` only after the check passes. The helper fetches the current server Tailscale IPv4 from `tailscale ip -4` and pins it as `TAILSCALE_IP` if missing. A conflicting Tailscale IP or existing `COMPOSE_FILE` fails closed. Do not put a residential global IPv6 prefix or credentials in GitHub. `.env` remains host-local with restrictive permissions.

Use only the overlays actually required by **your** deployment; `compose.override.yml` is optional. If your stack uses a different set, specify that exact ordered set. `COMPOSE_FILE` is used for **bare** `docker compose` commands. An explicit `docker compose -f ...` command overrides it; avoid ad-hoc partial file lists. Other tools that pass explicit Compose files may also override it. This is protection against a common operator mistake, not a global enforcement mechanism.

### Extend an existing pinned Compose file set

If you initially pinned the base/override/Tailscale overlays and later want to
add IPv6, use the explicit `--extend` flag. It permits **only appending** new
overlay files; it will never remove or reorder already pinned files.

After checking the actual IPv6 delegated prefix, gateway, parent LAN interface,
and address, make the four `LAN_*` / `PIHOLE_IPV6` values available from the
host's local `.env` or the command environment. **Do not guess them or use a
stale delegated prefix.** Then preview the entire validated set:

```bash
python3 pin-compose-files.py --project-dir /docker/pihole \
  --file compose.yml --file compose.override.yml \
  --file compose.tailscale-dns.yml --file compose.ipv6-dns.yml --extend
```

Repeat with `--extend --apply` after the preview succeeds. The original
`.env` is backed up, unrelated values are preserved, and no containers are
modified. Pinning is only preparation: activating a missing IPv6 macvlan
attachment still requires a scheduled Compose recreation.

**Pinning does not repair already-running containers.** Restoring a removed Docker-published port requires planned container recreation, with an interruption possible. Preserve remote management and wait for a maintenance window before doing so.

## Restore remote DNS temporarily without stopping Pi-hole

When Pi-hole still answers at its host LAN IPv4 but not its host Tailscale IPv4, the optional temporary bridge can make Tailscale-only DNS requests reach the current LAN binding. No Compose change is involved.

```bash
bash tailscale-dns-rescue.sh --check
bash tailscale-dns-rescue.sh --apply
bash tailscale-dns-rescue.sh --check
```

This requires root for `--apply`, working `docker`, `tailscale`, `ip`, `iptables` and `python3`, a running unpaused Pi-hole container, one identical TCP/UDP host-published LAN IPv4 endpoint, and a Tailscale interface with an active 100.64.0.0/10 address. The `PIHOLE_CONTAINER` environment variable can select a nondefault Pi-hole container name. It inserts only scoped UDP/TCP `tailscale0` DNAT rules marked `omv-pihole-ts-dns-rescue` and bound to the **current** server Tailscale IP and LAN listener. It does not open port 53 to the internet or rewrite host `/etc/resolv.conf`.

**Important limitations:** This is a temporary IP-layer rescue, not a guarantee of remote connectivity. Tailnet ACLs or a separate firewall may still block DNS; Tailscale IP changes and firewall rewrites can invalidate the rules. A remote-client DNS test is needed. Docker's userspace port proxy or NAT path may alter the source address observed by Pi-hole, so per-device policy/group identity is **not guaranteed** while the bridge is active. Do not leave it as a substitute for validating the native Tailscale overlay.

Remove only the scoped rules after restoring native port publication:

```bash
bash tailscale-dns-rescue.sh --remove
```

The rules are runtime-only and do not survive every restart/reload of firewall networking; removal does not touch unrelated iptables rules. If `iptables` is missing or host networking differs, stop and assess before using another forwarding method.

## Validation without interrupting the server

First inspect the actual project files from labels, port publications, and container health:

```bash
docker inspect pihole --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}'
docker port pihole 53/udp
docker port pihole 53/tcp
tailscale ip -4
docker inspect pihole --format 'running={{.State.Running}} paused={{.State.Paused}}'
```

Confirm DNS from a client actually connected to Tailscale before claiming success. Test LAN DNS and Tailscale DNS independently, including both UDP and TCP where practical. A healthy Docker status alone does not prove reachability.

Do **not** trigger an APT upgrade, restart Docker, change the host DNS resolver, or recreate Pi-hole as part of the remote test.

## Prevention with Docker runtime upgrade recovery

The [Docker upgrade recovery feature](../engine-upgrade-recovery/README.md) separately snapshots running container IDs before APT runtime upgrades and only restarts existing previously-running containers if they unexpectedly stop. It cannot recreate missing port bindings, recover a container that has been replaced with an incomplete Compose configuration, or fix unhealthy application processes. Compose-file pinning solves the unrelated *overlay-omission* failure mode.

Docker reference: [Pre-defined Compose variables](https://docs.docker.com/compose/how-tos/environment-variables/envvars/) and [variable interpolation](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).

## Optional persistent DNS continuity guard (without Pi-hole restarts)

When Tailscale DNS was lost due to a missing native Pi-hole port binding, the
rescue DNAT rule can disappear on reboot or after Docker rebuilds firewall
rules. The opt-in **dns-guard** systemd timer checks every minute and maintains
only the Tailscale-interface-scoped rescue rules until native publication is
restored. The guard does not restart any container or Docker daemon. When both
native TCP/UDP port 53 bindings become available, the guard removes only its
own rescue rules, restoring direct per-client DNS attribution.

On the actual OMV host, from the repository checkout:

    cd docker/pihole/dns-guard
    bash install.sh --check
    bash install.sh --apply

The installer copies the verified rescue helper, DNS guard, timer and service
into protected host paths. It refuses to overwrite unrelated/locally edited
files. No Pi-hole or Docker restart occurs. The guard is only appropriate for
hosts intentionally using Pi-hole as a Tailscale DNS server.

Inspect the timer and status:

    systemctl is-active omv-pihole-tailscale-dns-guard.timer
    journalctl -u omv-pihole-tailscale-dns-guard.service -n 30 --no-pager

To disable the timer without removing currently working DNS rescue rules:

    systemctl disable --now omv-pihole-tailscale-dns-guard.timer

Removing the forwarding rules while native DNS is still missing would break
remote DNS. Restore and verify native DNS before removing the rescue rules.
