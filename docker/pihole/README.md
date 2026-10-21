# Pi-hole

DNS filtering, client profiles and local policy, with `dnsproxy` forwarding encrypted queries to **Quad9 DoH** by default.

```text
Clients → Pi-hole profiles → dnsproxy → Quad9
```

## Start here

- [Setup](SETUP.md) — normal installation and configuration
- [`pihm` profile manager](OPERATIONS.md#profile-manager) — TUI, groups, devices and blocklists
- [Networking](NETWORKING.md) — Tailscale, IPv6, router and Docker details
- [DNS recovery](DNS-RECOVERY.md) — guarded recovery without shutting down Pi-hole
- [Additional operations](OPERATIONS.md) — NextDNS overlay, advanced profile commands and proxy integration

Launch `pihm` to manage profiles after installation. Keep profile rules in Pi-hole; `dnsproxy` is only the upstream transport.

**Before recreating the stack, inspect all active Compose overlays and network bindings.** The base Compose file alone may not reproduce the running DNS service.
