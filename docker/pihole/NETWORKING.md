# Pi-hole networking reference

Use [SETUP.md](SETUP.md) for the normal setup.

This file records the advanced networking behavior that was actually validated so future troubleshooting does not repeat the same false starts.

## Intended DNS paths

```text
LAN IPv4 client
  -> Pi-hole LAN IPv4
  -> Pi-hole sees the client LAN IPv4

Tailscale client
  -> OMV Tailscale IPv4
  -> Pi-hole
  -> Pi-hole sees the client 100.x address

LAN IPv6 client on validated stock ASUSWRT
  -> ASUS LAN IPv6 advertised as RDNSS
  -> ASUS forwards to Pi-hole IPv6
  -> filtering works, but Pi-hole may see the ASUS instead of the client
```

For per-device policy, the stable LAN IPv4 and Tailscale IPv4 identities are the preferred identifiers.

## AT&T BGW320 + stock ASUSWRT

Validated hardware/software pattern:

- AT&T BGW320-500;
- ASUS RT-AX82U on stock ASUSWRT;
- BGW320 IPv4 IP Passthrough enabled;
- BGW320 IPv6 enabled;
- BGW320 DHCPv6 enabled;
- BGW320 DHCPv6 Prefix Delegation enabled;
- ASUS IPv6 mode `Native`;
- ASUS DHCP-PD enabled;
- ASUS LAN autoconfiguration `Stateless`;
- ASUS Router Advertisement enabled;
- ASUS IPv6 firewall enabled.

### Why Native + DHCP-PD

With ASUS IPv6 set to `Passthrough`, the BGW320 did not show a delegated prefix for the ASUS.

After changing ASUS to `Native` with DHCP-PD enabled:

- the BGW320 populated its delegated-prefix field;
- the ASUS received a dedicated LAN /64;
- the ASUS became the IPv6 router for the LAN;
- external IPv6 connectivity worked;
- Tailscale reported both public IPv4 and public IPv6 capability.

Do not disable IPv6 merely to simplify DNS.

## Stock ASUSWRT RDNSS limitation

Even after configuring Pi-hole as the custom IPv6 DNS target, `rdisc6` showed stock ASUSWRT advertising the ASUS LAN IPv6 address itself as the Recursive DNS Server.

That means the practical path can remain:

```text
client -> ASUS IPv6 DNS -> Pi-hole
```

Pi-hole still filters the request, but the source identity may collapse to the router.

This is a client-identity limitation, not a Pi-hole filtering failure.

Do not add rotating Android IPv6 privacy addresses to `pihm` profiles as a workaround.

## Pi-hole IPv6 macvlan

The normal Pi-hole Docker bridge is IPv4-only.

`compose.ipv6-dns.yml` adds a separate IPv6-only macvlan so Pi-hole has a real IPv6 address on the physical LAN.

Required variables:

```text
LAN_INTERFACE
LAN_IPV6_SUBNET
LAN_IPV6_GATEWAY
PIHOLE_IPV6
```

Example:

```bash
export LAN_INTERFACE=enp3s0
export LAN_IPV6_SUBNET='2001:db8:1234:5678::/64'
export LAN_IPV6_GATEWAY='2001:db8:1234:5678::1'
export PIHOLE_IPV6='2001:db8:1234:5678::53'
```

Validate the full active stack before applying:

```bash
TAILSCALE_IP="$(tailscale ip -4 | head -n1)"

LAN_INTERFACE="$LAN_INTERFACE" \
LAN_IPV6_SUBNET="$LAN_IPV6_SUBNET" \
LAN_IPV6_GATEWAY="$LAN_IPV6_GATEWAY" \
PIHOLE_IPV6="$PIHOLE_IPV6" \
TAILSCALE_IP="$TAILSCALE_IP" \
docker compose \
  -f compose.yml \
  -f compose.tailscale-dns.yml \
  -f compose.ipv6-dns.yml \
  config
```

Use the same active overlay set when recreating the stack. To make ordinary bare `docker compose` commands use the intended overlay set, pin `COMPOSE_FILE` in the project's local `.env` as described in [DNS-RECOVERY.md](DNS-RECOVERY.md). The helper never recreates Pi-hole; native DNS bindings still require a planned Compose recreation if already lost.

The macvlan solves Pi-hole IPv6 reachability. It does not force stock ASUSWRT to advertise Pi-hole itself as RDNSS.

## Prefix changes

Residential delegated IPv6 prefixes may change.

Do not hard-code a residential global prefix into the public repository.

If the delegated prefix changes, update these together:

1. `LAN_IPV6_SUBNET`;
2. `LAN_IPV6_GATEWAY`;
3. `PIHOLE_IPV6`;
4. the router's custom IPv6 DNS target.

Old IPv6 addresses may remain on Linux interfaces until their advertised lifetimes expire. That alone is not a reason to restart networking.

Avoid hard-coded local AAAA overrides tied to a residential delegated prefix unless they are maintained automatically.

## Tailscale DNS

Recommended tailnet DNS:

```text
Global nameserver: OMV Tailscale IPv4
MagicDNS: on
Override DNS servers: on
```

Remove any direct NextDNS global resolver instead of leaving it beside Pi-hole.

Verify Pi-hole sees the real Tailscale client address:

```bash
docker exec pihole pihole -t
```

For a linked device, the same profile can contain:

```text
LAN IPv4
Tailscale 100.x IPv4
```

`pihm` should discover/link these where possible.

## Upstream DNS

Default and recommended:

```text
client -> Pi-hole -> dnsproxy -> Quad9 DoH
```

Optional:

```text
client -> Pi-hole -> dnsproxy -> NextDNS DoH
```

Use one upstream behind Pi-hole.

Do not configure Quad9 and NextDNS as parallel client-side resolvers around Pi-hole.

Always inspect the running `dnsproxy` command before changing a live host.

## Browser and Android DNS bypasses

Check these separately:

- Android Private DNS;
- Firefox DNS-over-HTTPS;
- other browser Secure DNS settings;
- VPN/Tailscale DNS;
- cached DNS answers;
- persistent HTTP/2 or HTTP/3 connections.

Android Private DNS can be correct while Firefox still bypasses Pi-hole through DoH.

Android Wi-Fi Proxy should normally remain `None`. Proxy `Auto-config` is not a DNS fix.

A browser can continue loading pages without generating new DNS queries.

To force a fresh lookup, use a unique intentionally nonexistent hostname and watch Pi-hole logs. The page is expected to fail; the DNS query is the test.

## Evidence rules

Do not over-interpret one log line.

A query logged from the router does not prove a particular downstream device generated it. Routers perform their own DNS lookups.

A packet capture on OMV cannot see a phone-to-router DNS packet if that packet terminates at the router.

Use multiple pieces of evidence when client identity matters:

- Pi-hole query log;
- unique test hostname;
- `rdisc6`;
- packet capture;
- Tailscale status/netcheck/ping.

## Useful diagnostics

Active Compose files:

```bash
docker inspect pihole --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}'
```

Pi-hole interfaces:

```bash
docker exec pihole sh -c 'ip -br addr'
```

DNS listeners:

```bash
docker exec pihole sh -c 'ss -lnptu | grep ":53 "'
```

Live Pi-hole traffic:

```bash
docker exec pihole pihole -t
```

Router Advertisement and RDNSS:

```bash
rdisc6 enp3s0
```

Tailscale network capability:

```bash
tailscale netcheck
```

Specific peer path:

```bash
tailscale ping <peer>
```

`tailscale netcheck` proves available network capability, not that every peer is direct.

After recreating Pi-hole, wait for FTL to finish starting and verify port 53 is listening before diagnosing an immediate connection failure as a networking-design problem.

## Security

Never expose raw Pi-hole DNS publicly without an explicit access-control design.

For the validated design:

- ASUS IPv6 firewall stays enabled;
- LAN IPv6 may reach the Pi-hole macvlan endpoint;
- Tailscale reaches Pi-hole through the Tailscale-bound IPv4 DNS port;
- WAN/public DNS is not intentionally opened.

Do not commit passwords, API keys, tailnet names, residential public IPv6 prefixes, or other deployment secrets.

Rotate the Pi-hole web/API password if it has been pasted into a chat, ticket, or public location.
