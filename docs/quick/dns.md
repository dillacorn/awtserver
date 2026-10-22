# DNS | Pi-hole and Tailscale

1. Establish working DNS **without Pi-hole** during Debian/bootstrap.
2. Configure Pi-hole's LAN listener. Preserve the active Compose overlays and its data.
3. If using Pi-hole while away, bind an explicit Tailscale DNS listener and test resolution **before** changing tailnet DNS.
4. In Tailscale DNS settings, choose the intended Pi-hole resolver, MagicDNS and DNS override; don't configure contradictory global resolvers.
5. Verify LAN and remote phone DNS separately. For per-device Pi-hole policies, confirm actual Tailscale client IPs in Pi-hole logs, not a shared Docker NAT source.

**Do not automatically apply repository examples on a running host.** A lost overlay can silently remove the remote Pi-hole DNS listener.

Details: [Pi-hole setup](../../docker/pihole/SETUP.md) · [DNS recovery](../../docker/pihole/DNS-RECOVERY.md).
