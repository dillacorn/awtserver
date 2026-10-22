# Tailscale | Remote access

Use this when you want to reach a private server from outside home.

1. Install and sign into **Tailscale** on the Debian host and phone. Both devices must belong to the same tailnet.
2. In the [Tailscale admin DNS settings](https://login.tailscale.com/admin/dns), enable **MagicDNS**. For HTTPS with **Tailscale Serve**, also enable HTTPS certificates (device names appear in public certificate logs).
3. Pick one route **per app**: host Tailscale + a reviewed local service route, or the app's own Tailscale sidecar. Do not mix them without verifying ports, routing and identity.
4. Confirm tailnet access permissions; then test the app from **mobile data with Wi-Fi off**, not just on your home Wi-Fi.
5. Keep the Tailscale state directory persistent. Never copy the same state into two running nodes.

**No public port forwarding required.** Prefer tailnet-only Serve, not Funnel. Adding Tailscale does not automatically expose every Docker application.

Next: `awtserver docs remote-apps` or `awtserver docs android-auto`.

Full reference: [Tailscale Docker Compose](https://tailscale.com/docs/features/containers/docker/how-to/connect-docker-container) · [Serve](https://tailscale.com/docs/features/tailscale-serve).
