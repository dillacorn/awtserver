# Navidrome

Music streaming server backed by an existing read-only music library.

- **Media:** Mounted at `/music:ro` in the container.
- **State:** Navidrome database/cache stored under the service's `data` directory.
- **Access:** Tailscale HTTPS at the configured Navidrome MagicDNS hostname.
- **Optional:** Pi-hole/Nginx LAN HTTPS route.

Before starting, check library bind mounts and ownership of the writable data directory. The example host paths are specific to the recorded installation.

[First start, certificates and LAN routing](OPERATIONS.md)
