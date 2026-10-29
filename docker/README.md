# Docker services

Compose templates, helper scripts and short service guides for a Debian Stable server.

## Browse services

| Service | Documentation |
| --- | --- |
| **DNS and profiles** | [Pi-hole](pihole/README.md), [Arachnidium](arachnidium/README.md) |
| **Media** | [Jellyfin](jellyfin/README.md), [Seerr](seerr/README.md), [Navidrome](navidrome/README.md) |
| **Privacy / torrent search** | [aMuTorrent + Prowlarr trial](privacy/AMUTORRENT-OPERATIONS.md) |
| **Management** | [Dockge](dockge/README.md), [Watchtower](watchtower/README.md) |
| **Maintenance** | [Docker Engine recovery](engine-upgrade-recovery/README.md), [Tailscale certificates](tailscale-certs/README.md) |
| **Remote access** | [Tailscale per-app setup](../docs/quick/remote-apps.md), [Android Auto Rules](../docs/quick/android-auto.md) |

Other service templates are available in their respective subdirectories.

## Safe starting point

```bash
docker compose ls
docker ps --format 'table {{.Names}}\t{{.Status}}'
```

Inspect the *running* Compose project, overrides, mounts, volumes and container identities before applying a template. Never use cleanup or `docker compose down` against a production stack whose persistent state and dependencies have not been verified.
