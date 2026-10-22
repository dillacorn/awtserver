# Tailscale | Android Auto Rules

[Tailscale Auto Rules (Google Play)](https://play.google.com/store/apps/details?id=fr.vbrosseau.tailscaleautorules) is a third-party companion by Valentin Brosseau. It controls the official **Tailscale** Android app; it does not replace it or configure the server.

1. Install and sign into the **official Tailscale Android app** first.
2. Install **Tailscale Auto Rules** and follow its permissions/foreground-service setup.
3. Mark **home Wi-Fi** as trusted: Tailscale **off** there if your services are reachable directly on LAN.
4. Set mobile data and unknown/untrusted Wi-Fi to **Tailscale on**.
5. Turn off Wi-Fi to test a real cellular transition; check the companion's displayed rule/history and open a private app URL.
6. Return to home Wi-Fi and verify the tunnel and LAN access behave as intended.

**Important:** Turning Tailscale off at home disconnects tailnet-only services unless a working LAN DNS/reverse-proxy path exists. Android VPN/battery restrictions may affect automation. Avoid enabling conflicting Android **Always-on VPN** rules without checking behavior.

Source: [project](https://github.com/c4software/tailscale-auto-rules) · [Play Store](https://play.google.com/store/apps/details?id=fr.vbrosseau.tailscaleautorules).
