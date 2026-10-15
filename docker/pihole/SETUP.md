# Pi-hole setup

This is the recommended setup for a normal home deployment.

```text
devices -> Pi-hole -> dnsproxy -> Quad9 DoH
```

Pi-hole does the blocking and per-device policy. Quad9 is only the encrypted upstream resolver.

## 1. Create the stack

Start from the example:

```bash
cd /docker/pihole
cp compose_example.yml compose.yml
```

Edit `compose.yml` before starting it.

At minimum, set:

- your OMV LAN IPv4 address;
- a Pi-hole web/API password;
- the local hostnames you actually use;
- any certificate or nginx mounts required by your deployment.

Do not copy the example over an existing live `compose.yml`.

The default upstream is already Quad9 DoH:

```text
Pi-hole -> dnsproxy -> https://dns.quad9.net/dns-query
```

Start the base stack:

```bash
docker compose up -d
```

## 2. Install pihm

Install the Pi-hole profile manager:

```bash
curl -fsSL https://raw.githubusercontent.com/dillacorn/omv-remote-dots/main/docker/pihole/pihm-installer | bash
```

Launch it:

```bash
pihm
```

For an existing Pi-hole configuration, use:

```text
Profiles
-> Import current Pi-hole groups
```

For a new setup, create the profiles you want directly in `pihm`.

## 3. Choose the fallback policy

One profile can be the policy for otherwise-unassigned clients.

Recommended for a normal home network:

```text
Home Router
-> Default fallback
```

CLI equivalent:

```bash
pihm default "Home Router"
pihm default
```

Expected:

```text
Home Router
```

Known devices can still be assigned to stricter profiles.

## 4. Point the LAN at Pi-hole

On the router, advertise the OMV/Pi-hole LAN IPv4 address as the LAN DNS server.

Recommended:

```text
DNS server 1: <OMV LAN IPv4>
DNS server 2: blank
Advertise router as an additional IPv4 DNS server: off
```

Reconnect clients after changing DHCP/DNS settings.

Verify Pi-hole sees real LAN clients:

```bash
docker exec pihole pihole -t
```

For per-device profiles, queries should normally appear from the client's LAN IPv4 address rather than only from the router.

## 5. Add a device

Inside the target profile:

```text
Clients
-> Add / link device
```

If Tailscale is installed, choose the device by Tailscale name or MagicDNS name.

`pihm` can save both identities to one profile:

```text
LAN IPv4       -> same profile
Tailscale IPv4 -> same profile
```

This is the preferred setup for a device that should keep the same filtering policy at home and away.

## 6. Optional: use Pi-hole over Tailscale

Add the Tailscale DNS overlay:

```bash
cd /docker/pihole
TAILSCALE_IP="$(tailscale ip -4 | head -n1)"

TAILSCALE_IP="$TAILSCALE_IP" docker compose \
  -f compose.yml \
  -f compose.tailscale-dns.yml \
  up -d
```

Then in the Tailscale DNS settings:

```text
Global nameserver: <OMV Tailscale IPv4>
MagicDNS: on
Override DNS servers: on
```

Remove any direct NextDNS global resolver instead of leaving both active.

**Protect this setup before later Compose commands:** A plain `docker compose up -d` can omit the optional Tailscale overlay and recreate Pi-hole without its remote DNS listener. Pin the **correct** complete Compose file list in `.env` using [DNS-RECOVERY.md](DNS-RECOVERY.md). This does not restart Pi-hole. If the live container has already lost the overlay, do not pin its broken file list.

Verify a Tailscale client reaches Pi-hole with its own `100.x` address:

```bash
docker exec pihole pihole -t
```

## 7. Optional: IPv6

IPv6 is not required for Pi-hole, but keeping native IPv6 can help Tailscale establish direct connections.

The tested AT&T BGW320 + stock ASUSWRT setup requires DHCPv6 Prefix Delegation and has an ASUS-specific RDNSS limitation.

Do not copy that advanced setup blindly.

Read:

[NETWORKING.md](NETWORKING.md)

before enabling the Pi-hole IPv6 macvlan overlay.

## 8. Verify the final setup

Check the upstream:

```bash
docker inspect dnsproxy --format '{{json .Config.Cmd}}'
```

The normal/default result should include:

```text
--upstream=https://dns.quad9.net/dns-query
```

Check the fallback profile:

```bash
pihm default
```

Check live DNS traffic:

```bash
docker exec pihole pihole -t
```

The intended result is:

```text
unassigned client -> Default -> Home Router policy
assigned client   -> its selected profile
all allowed DNS   -> dnsproxy -> Quad9 DoH
```

## Optional NextDNS upstream

NextDNS is supported, but it is not the default.

Use:

```bash
NEXTDNS_CONFIG_ID='your-config-id' docker compose \
  -f compose.yml \
  -f compose.nextdns-upstream.yml \
  up -d --no-deps dnsproxy
```

Pi-hole should remain in front of NextDNS so local profiles and filtering still apply.

Do not configure NextDNS as a parallel client resolver beside Pi-hole.
