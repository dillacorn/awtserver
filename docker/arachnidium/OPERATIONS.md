# Arachnidium profile proxies

Optional data-saving HTTP(S) proxies for Pi-hole profiles.

This wrapper runs Arachnidium in mitmproxy's regular HTTP proxy mode instead of its default WireGuard mode. Pi-hole remains the DNS/filtering authority, so Arachnidium's own ad blocking is disabled.

Upstream: https://github.com/p2r3/Arachnidium

## Network model

Each proxy instance has one fixed IP on the private Docker network `pihole-proxy`, Pi-hole at `172.30.53.2` as DNS, one host TCP port, and one Pi-hole profile assigned to the proxy container IP.

```text
browser -> 192.168.1.10:18101 -> arachnidium-personal (172.30.53.101)
                                  -> DNS 172.30.53.2
                                  -> Pi-hole profile for 172.30.53.101
```

Remote Tailscale clients use the same port on the OMV Tailscale IP:

```text
100.64.0.10:18101
```

The example binds proxy ports only to the configured LAN and Tailscale IPs. Do not publish them on `0.0.0.0` or a WAN-facing address.

## One-time setup

Create the private DNS network and attach Pi-hole with the overlay in `../pihole`:

```bash
docker network inspect pihole-proxy >/dev/null 2>&1 || \
    docker network create --driver bridge --subnet 172.30.53.0/24 pihole-proxy

cd /docker/pihole
docker compose \
    -f compose.yml \
    -f compose.proxy-profiles.yml \
    up -d
```

Copy this directory to `/docker/arachnidium`, create `.env`, then build/start:

```bash
cd /docker/arachnidium
cp .env_example .env
nano .env
docker compose -f compose_example.yml build --pull
docker compose -f compose_example.yml up -d
```

Set all three values in `.env`: the OMV LAN IP, OMV Tailscale IP, and OMV MagicDNS hostname. `PROXY_HOSTNAME` is the single address you can keep configured in the browser at home and away.

Assign each proxy's private Docker IP to the Pi-hole profile it should use:

```bash
/docker/pihole/pihole-profile-manager assign \
    "Personal" 172.30.53.101 --label arachnidium-personal

/docker/pihole/pihole-profile-manager assign \
    "Family" 172.30.53.102 --label arachnidium-family
```

## Browser connection

For the `18101` profile, set both HTTP and HTTPS proxy to:

```text
LAN:       192.168.1.10 port 18101
Tailscale: 100.64.0.10 port 18101
```

While connected through the proxy, open `http://mitm.it` and install the mitmproxy CA for the client. The example containers share `./state/mitmproxy`, so one CA can be used for every profile instance.

The CA private key in `state/mitmproxy` is sensitive. Back it up securely and never publish that directory.

## One proxy address at home and away

The easiest single browser setting is the OMV MagicDNS hostname:

```text
omv.example-tailnet.ts.net:18101
```

On the home LAN, Pi-hole can override that hostname to the OMV LAN IP. Away from home, Tailscale MagicDNS resolves the same hostname to the OMV Tailscale IP. Both paths land on the same profile proxy.

If the exact same literal LAN IP is required instead, advertise the OMV LAN IP or LAN subnet as a Tailscale subnet route. Then remote clients can also use `192.168.1.10:18101`.

## Add another profile proxy

Duplicate one service in `compose_example.yml`, then change only the service/container name, `ipv4_address`, and host port. Assign that Docker IP to the desired Pi-hole profile with `pihole-profile-manager assign`.

## Notes

Arachnidium rewrites HTTPS content and therefore requires trusting its CA. Some applications use certificate pinning or protocols that will not work through a MITM HTTP proxy. Treat this as an opt-in browser/data-saver path, not a transparent whole-network proxy.

The Docker wrapper is pinned to a specific upstream revision so a future upstream change cannot silently alter the local deployment. Validate a new upstream revision before changing the pin.
