# Jellyfin

Jellyfin runs in its own Compose project with a Tailscale HTTPS sidecar. Inspect live Compose labels and mounts before deployment; the checked-in examples are not an exact server snapshot.

## Access and operation

- Use the private `https://<service>.<your-tailnet>.ts.net` hostname (example: `https://jellyfin.time-puffin.ts.net`).
- [Downloads library / Transmission mergerfs integration](OPERATIONS.md): read-only completed-downloads mount, verified 2026-10-29 OMV deployment, manual **Downloads** library setup, verification and rollback.
- [Optional `compose.downloads.yml` overlay](compose.downloads.yml): intended for a future clean deployment **without** the same mount in another Compose file; the inspected host already has it in `compose.override.yml`.

## Certificate export for local reverse proxies

Export certificates from the *verified* Tailscale sidecar only if needed by a local reverse proxy:

```bash
docker exec -it tailscale-jellyfin tailscale cert jellyfin.<your-tailnet>.ts.net
```

Tailscale Serve renewal is separate from exported nginx certificates. Do not publish private certificate files.
