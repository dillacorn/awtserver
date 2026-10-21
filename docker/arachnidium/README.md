# Arachnidium

Optional profile-specific HTTP(S) proxies for Pi-hole clients.

- Each proxy uses a separate private Docker IP and Pi-hole profile.
- Browsers connect through a configured LAN or Tailscale address and TCP port.
- HTTPS inspection requires installing and trusting a mitmproxy CA certificate.

**Security:** Bind proxy ports only to intended LAN/Tailscale interfaces; never expose them to the public internet. Protect the CA private key, and expect some certificate-pinned apps not to work.

[Network layout, setup, profile commands and browser configuration](OPERATIONS.md) · [Upstream](https://github.com/p2r3/Arachnidium)
