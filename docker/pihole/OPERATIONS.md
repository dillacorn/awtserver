# Pi-hole

This stack uses Pi-hole as the self-hosted filtering/policy layer and `dnsproxy` only as encrypted upstream transport. **Quad9 DoH is the default and recommended upstream.**

```text
client -> Pi-hole profile/group -> dnsproxy -> Quad9 DoH
```

That keeps blocking, allow/deny rules, client groups, and policy decisions local to Pi-hole while using Quad9 only for recursive DNS resolution over encrypted DoH.

## Start here

For the normal recommended setup, use [SETUP.md](SETUP.md).

For the deeper IPv6, Tailscale, Docker, ASUS/BGW320, and troubleshooting details, use [NETWORKING.md](NETWORKING.md).

To prevent accidentally losing Tailscale/IPv6 DNS bindings during Compose recreation, or temporarily recover remote DNS **without stopping Pi-hole**, see [DNS-RECOVERY.md](DNS-RECOVERY.md).

Keep normal setup simple. The advanced networking guide exists so the main setup does not have to carry every edge case.

### Optional NextDNS upstream

NextDNS remains supported as an optional upstream for users who want it. It is not the default and should not be configured as a parallel resolver beside Pi-hole.

Use the optional overlay:

```bash
export NEXTDNS_CONFIG_ID='your-nextdns-config-id'

docker compose \
  -f compose.yml \
  -f compose.nextdns-upstream.yml \
  up -d --no-deps dnsproxy
```

The resulting path is:

```text
client -> Pi-hole profile/group -> dnsproxy -> NextDNS DoH
```

Pi-hole still performs the local profile/blocking policy. NextDNS is only the encrypted recursive upstream in that mode.

To return to the recommended Quad9 default, recreate `dnsproxy` from the base Compose file without the NextDNS overlay.


The profile manager below keeps groups, lists, allow/deny rules, blocked TLDs, and client assignments editable as normal INI files instead of hand-editing `gravity.db`.

## Profile manager

The short command is `pihm` ("Pi-hole Manager").

Files:

- `pihm-installer` - install/update/uninstall helper
- `pihole-profile-manager` - management program and CLI
- `pihole-profile-tui` - arrow-key TUI for normal day-to-day management
- `profile-catalog.ini` - maintained blocklist URLs
- `profile.example.ini` - editable profile example
- `/docker/pihole/profiles.d/*.ini` - live profile definitions

### Install

Run as root on the OMV host:

```bash
curl -fsSL https://raw.githubusercontent.com/dillacorn/omv-remote-dots/main/docker/pihole/pihm-installer | bash
```

The installer keeps the manager under `/docker/pihole`, creates `/usr/local/bin/pihm`, preserves existing profile files, backs up replaced manager files, and validates the Python programs before installing them.

Updates are handled inside the TUI:

```text
pihm
  -> Update pihm
```

The updater downloads the latest manager files from `main`, validates them, creates backups for changed program files, installs the update, and restarts the TUI automatically.

Uninstall only the manager program files and command links:

```bash
pihm-installer uninstall
```

Pi-hole databases, profile definitions, backups, and Compose files are preserved on uninstall.

### TUI

Launch it from anywhere:

```bash
pihm
```

Running `/docker/pihole/pihole-profile-manager` with no arguments opens the same TUI.

Navigation is intentionally similar to smtty/Awtarchy: Up/Down or `j/k` moves, held arrow keys repeat, Enter selects or toggles, `h` opens Help from any menu, `q`/Esc goes back, and PgUp/PgDn scrolls long lists.

The TUI can create Normal/Strict/Parental/blank profiles, clone profiles, toggle blocklists, edit allow/deny rules and blocked TLDs, assign LAN/Tailscale clients, configure a proxy port/Docker IP per profile, apply profiles, rebuild Gravity, manage the daily timer, update `pihm` itself, and show exact proxy connection guidance. The profile list shows either `[proxy :PORT configured]` or `[no proxy]`. `[no proxy]` means the Pi-hole policy exists but no Arachnidium endpoint has been configured for it yet.

On an existing Pi-hole install, use **Profiles -> Import current Pi-hole groups** once. This captures the current groups into editable files under `/docker/pihole/profiles.d/` without changing them.

Capture existing non-default Pi-hole groups as editable profiles:

```bash
/docker/pihole/pihole-profile-manager capture --all
```

Inspect them:

```bash
/docker/pihole/pihole-profile-manager list
/docker/pihole/pihole-profile-manager status
/docker/pihole/pihole-profile-manager show "Home Router"
```

Edit and apply a profile:

```bash
/docker/pihole/pihole-profile-manager edit "Home Router"
/docker/pihole/pihole-profile-manager apply "Home Router" --gravity
```

In the TUI, **Sync to Pi-hole** synchronizes the profile definition into Pi-hole: group description, selected list-to-group assignments, allow/deny regex rules, blocked TLDs, client assignments, and the configured Arachnidium proxy Docker IP. It creates a timestamped SQLite backup first, then reloads DNS. It does **not** redownload blocklist contents.

**Sync + refresh lists** performs the same policy sync and then runs a full Pi-hole Gravity rebuild/download. Use it after changing selected blocklists or when you explicitly want to fetch the latest contents from all enabled blocklist URLs.

Create a new profile from a preset:

```bash
/docker/pihole/pihole-profile-manager new "Guest" --preset normal
/docker/pihole/pihole-profile-manager edit "Guest"
/docker/pihole/pihole-profile-manager apply "Guest" --gravity
```

Available presets:

- `normal` - HaGeZi Normal + OISD + TIF + DGA30 + device tracker lists
- `strict` - HaGeZi PRO++ + OISD + TIF + DGA30 + device tracker lists
- `parental` - Normal plus NSFW, gambling, piracy, dating, and DynDNS lists

Clone an existing profile:

```bash
/docker/pihole/pihole-profile-manager new "Tablet" --clone "Guest"
```

Assign a normal client or profile-aware proxy by IP:

```bash
/docker/pihole/pihole-profile-manager assign \
    "Guest" 100.64.0.50 --label tablet
```

Return it to Pi-hole's Default group:

```bash
/docker/pihole/pihole-profile-manager unassign 100.64.0.50
```

Every database-changing command creates a timestamped online SQLite backup beside `gravity.db` before writing.

### Profile format

Start from `profile.example.ini`.

```ini
[profile]
name = Example Strict
description = My profile
default = false

[lists]
keys =
    proplus
    oisd
    tif
    dga30
extra_urls =

[allow]
domains =
    allowed.example

[deny]
domains =
    blocked.example
tlds =
    zip

[clients]
entries =
    100.64.0.50 | laptop

[proxy]
enabled = true
port = 18101
docker_ip = 172.30.53.101
label = arachnidium-personal
```

The proxy port is the address you enter in a browser/Android proxy setting. The Docker IP is the fixed private source address Pi-hole uses to select this profile. When the profile is applied, `pihm` automatically assigns the configured proxy Docker IP to the Pi-hole group, so it does not need to be duplicated under `[clients]`.

The manager converts allow/deny domains and TLDs into Pi-hole regex rules that also cover subdomains. It synchronizes its catalog lists and manager-owned rules/clients while leaving unrelated manual Pi-hole data alone.

### Default fallback profile

Pi-hole's built-in `Default` group is the policy used by otherwise-unassigned clients. `pihm` can make one normal profile the persistent fallback policy.

In the TUI, open the profile and set **Default fallback**. The profile list marks the selected profile with `[DEFAULT]`.

CLI:

```bash
pihm default "Home Router"
pihm default
```

When the selected fallback profile is synced, `pihm` mirrors that profile's current blocklist assignments and allow/deny/TLD rules into Pi-hole's built-in `Default` group. Client assignments are not copied.

This means a setup can use specific profiles for known clients while all otherwise-unassigned clients automatically receive the chosen fallback policy. Cloning a profile never copies its default status.

### Link a device without typing IPs

Inside any profile, open **Clients -> Add / link device**. This is the recommended client-assignment workflow.

`pihm` reads `tailscale status --json` and shows tailnet devices by friendly hostname, Tailscale IP, and online state. You can also enter a Tailscale hostname or full MagicDNS name instead of choosing from the list.

After selecting a Tailscale device, `pihm`:

1. adds its Tailscale IPv4 automatically;
2. checks whether Tailscale currently has a direct connection to that same device from the local LAN and, when safe, uses that direct RFC1918 address as the LAN identity;
3. otherwise shows recently seen Pi-hole/LAN clients, newest first, so the LAN IP can be selected instead of typed;
4. stores both identities in the same profile; and
5. offers to sync the profile to Pi-hole immediately.

Example result:

```ini
[clients]
entries =
    100.64.0.50 | phone - Tailscale
    192.168.1.50 | phone - LAN
```

Both addresses select the same Pi-hole policy. The LAN address is used when the device talks to Pi-hole locally; the Tailscale address is used when DNS reaches Pi-hole over Tailscale.

`pihm` does not silently guess uncertain LAN matches. If Tailscale cannot provide a direct same-LAN endpoint and the hostname cannot be matched confidently, the TUI shows discovered LAN clients for explicit selection.

## Daily blocklist updates

Pi-hole does not continuously stream changes from the configured list URLs. Gravity fetches the current contents when a Gravity rebuild runs.

For predictable daily updates, enable the persistent daily Gravity timer from **pihm -> Maintenance -> Enable daily blocklist updates**. The default run time is 03:15 with a randomized delay of up to 20 minutes:

```bash
/docker/pihole/pihole-profile-manager timer install
```

Use another local time if wanted:

```bash
/docker/pihole/pihole-profile-manager timer install \
    --on-calendar '*-*-* 04:30:00'
```

Status/remove:

```bash
/docker/pihole/pihole-profile-manager timer status
/docker/pihole/pihole-profile-manager timer remove
```

This updates blocklists only. It does not auto-update the Pi-hole container.

## IPv6 LAN DNS

For direct LAN IPv6 reachability, Pi-hole can use the optional IPv6-only macvlan overlay:

```text
compose.ipv6-dns.yml
```

This keeps the normal Docker bridge IPv4-only while giving Pi-hole a real IPv6 address on the LAN. The overlay is intentionally variable-driven because residential DHCPv6 Prefix Delegation can change the LAN prefix.

Before using it, read [NETWORKING.md](NETWORKING.md). That guide records the validated AT&T BGW320 + stock ASUSWRT behavior, DHCPv6-PD setup, Tailscale interaction, RDNSS/client-identity limitation, security constraints, troubleshooting commands, and prefix-change procedure.

Future agents working in this directory must also read [AGENTS.md](AGENTS.md).

## Tailscale DNS endpoint

The base Compose file binds DNS only to the LAN IP. To make the same Pi-hole available as a tailnet DNS resolver without exposing port 53 publicly, add the optional Tailscale overlay:

```bash
cd /docker/pihole
TAILSCALE_IP=100.64.0.10 docker compose \
    -f compose.yml \
    -f compose.tailscale-dns.yml \
    up -d
```

Test it from another Tailscale device before changing tailnet DNS:

```bash
dig @100.64.0.10 example.com
```

Then configure the tailnet resolver to the OMV Tailscale IP. MagicDNS can remain enabled independently.

Before relying on per-device groups over Tailscale, verify Pi-hole's query log shows the real `100.x` client address. If Docker source-NATs the request into one shared address, individual direct-client grouping will not work until that path is changed.

## Profile-aware HTTP proxies

Pi-hole chooses a profile from the DNS client's source IP. A proxy therefore needs a unique, stable Docker IP if different proxy endpoints should use different Pi-hole profiles.

The TUI keeps the association visible. For example:

```text
Home Router                         [proxy :18101 configured]
Security++ Windows & Android        [proxy :18102 configured]
Guest                               [no proxy]
```

A configured port is metadata until the matching Arachnidium container is actually deployed and running. The connection-info screen reports that runtime state explicitly.

Inside a profile, open **Arachnidium proxy**. `pihm` can allocate the next recommended pair automatically, starting at host port `18101` and Docker IP `172.30.53.101`. Configuring this pair only records the planned endpoint; it does not by itself deploy or start Arachnidium. The **Proxy endpoints** screen then shows the hostname, LAN address, Tailscale address, port, Docker IP, and whether the matching Arachnidium container is running.

CLI equivalents are also available:

```bash
pihm proxy list
pihm proxy set "Home Router" --port 18101 --docker-ip 172.30.53.101
pihm proxy disable "Home Router"
```

Create the private proxy network once:

```bash
docker network inspect pihole-proxy >/dev/null 2>&1 || \
    docker network create --driver bridge --subnet 172.30.53.0/24 pihole-proxy
```

Attach Pi-hole at `172.30.53.2`:

```bash
cd /docker/pihole
docker compose \
    -f compose.yml \
    -f compose.proxy-profiles.yml \
    up -d
```

Each proxy container uses a unique `172.30.53.x` address, `172.30.53.2` as DNS, and its own host proxy port.

Assign the proxy container IP to the profile:

```bash
/docker/pihole/pihole-profile-manager assign \
    "Personal" 172.30.53.101 --label arachnidium-personal
```

See `../arachnidium/README.md` for the optional Arachnidium regular HTTP proxy example.

### LAN and Tailscale proxy addresses

For a proxy published on port `18101`:

```text
LAN IP:       192.168.1.10:18101
Tailscale IP: 100.64.0.10:18101
```

Both addresses terminate at the same proxy container, so they use the same Pi-hole profile.

The easiest single address is the OMV MagicDNS hostname. Put the real values in `/docker/arachnidium/.env`:

```ini
LAN_IP=192.168.1.10
TAILSCALE_IP=100.64.0.10
PROXY_HOSTNAME=omv.example-tailnet.ts.net
```

Then use the same browser proxy address everywhere:

```text
omv.example-tailnet.ts.net:18101
```

On the home LAN, Pi-hole can override that hostname to the OMV LAN IP. Away from home, Tailscale MagicDNS resolves the same hostname to the OMV Tailscale IP. The browser proxy setting therefore stays identical in both places.

If the exact same literal LAN IP is required instead, advertise the OMV LAN IP or LAN subnet as a Tailscale subnet route.

Never expose a MITM proxy on a public/WAN address.

## Local HTTPS routing

Local LAN clients can resolve the normal tailnet service names through Pi-hole and reach `nginx-pihole` directly instead of bouncing through a Tailscale `100.x` address:

```text
service.example-tailnet.ts.net
  -> Pi-hole local DNS
  -> LAN server IP
  -> nginx-pihole:443
  -> local-webapps Docker network
  -> application HTTP port
```

Create the shared network once:

```bash
docker network inspect local-webapps >/dev/null 2>&1 || \
    docker network create local-webapps
```

For each application that should be reachable locally, load its `compose.local-webapps.yml` overlay. Nginx should proxy LAN traffic to the local Docker backend, not back to a Tailscale `100.x` address.

Validate Pi-hole directly:

```bash
dig @192.168.1.10 jellyfin.example-tailnet.ts.net A +short
```

Then force the HTTPS request through the LAN IP:

```bash
curl -k \
    --resolve jellyfin.example-tailnet.ts.net:443:192.168.1.10 \
    https://jellyfin.example-tailnet.ts.net/
```
