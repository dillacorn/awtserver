# Tailscale | Docker app checklist

Repeat **for each app**. Compose templates are examples, not your live deployment.

1. **Identify** the running Compose project, service, ports, bind mounts, and network dependencies. Do not guess container names.
2. **Choose access**: existing host Tailscale listener/proxy, or a dedicated `tailscale/tailscale` sidecar sharing the app namespace.
3. **Authenticate the sidecar** to your tailnet using a private auth key or interactive login. Never commit auth keys; persist `TS_STATE_DIR` so it survives recreation.
4. **Set HTTPS**: enable MagicDNS + HTTPS certificates in Tailscale admin; configure **Serve** to the app's *actual* internal HTTP port. Keep Funnel disabled unless you explicitly intend public access.
5. **Verify** node identity, Tailscale policy/access, `tailscale serve status` **in the relevant Tailscale container**, and the app URL while the phone is on cellular data.
6. **Protect Compose overrides** and volumes. Test restarting the app *without* recreating the sidecar; don't accidentally re-register an existing node.

**Repo examples** (new installs): Seerr uses a Tailscale sidecar forwarding to port 5055; Navidrome uses a sidecar forwarding to port 4533. Jellyfin has a Tailscale HTTPS access note. Existing migrated Seerr may still have **Jellyseerr-named** Docker services; preserve them.

Troubleshoot in order: connected phone → machine online → tailnet access rule → MagicDNS/HTTPS → Serve target → app healthy.

Detailed, topology-specific references: [Seerr](../../docker/seerr/OPERATIONS.md) · [Navidrome](../../docker/navidrome/OPERATIONS.md) · [Pi-hole networking](../../docker/pihole/NETWORKING.md). Do not blindly apply those historical host paths to a fresh Debian VM.
