# 🛡️ Privacy Docker Compose Setup

This guide walks you through setting up a privacy-focused Docker Compose stack using AirVPN, NGINX, and Transmission.

---

## 🌐 1. Configure AirVPN Account Settings

Before starting, follow this visual guide to properly configure your AirVPN settings:

📸 [AirVPN Setup Guide](https://github.com/dillacorn/deb-omv-dots/tree/main/docker_compose_examples/privacy/airvpn_settings)

---

## ⚙️ 2. Configure `.env`

Edit your `.env` file based on the AirVPN example (recommended for privacy):

---

## 🚀 3. Launch the Docker Stack

Use the following commands in your terminal to start the stack:

Pull Updates for docker apps
```bash
sudo docker compose pull
```
Launch docker stack
```bash
sudo docker compose up -d
```

---

## 🌍 4. Access Web Interfaces

- 📦 **Transmission**  
  Visit: `https://transmission.MagicDNS-example.ts.net`

- 🔐 **Mullvad Browser (via noVNC)**  
  Visit: `https://mullvad.MagicDNS-example.ts.net`
`
---

## 🧭 5. Configure Transmission Application

After launching, adjust the Transmission settings by referring to this visual guide:

📸 [Transmission Settings Guide](https://github.com/dillacorn/deb-omv-dots/tree/main/docker_compose_examples/privacy/transmission_settings)

---

## aMuTorrent + Prowlarr + TRAWL

Torrent search and downloads behind Gluetun, including 1337x Cloudflare handling through TRAWL.

- **[Manual app setup](AMUTORRENT-SETUP.md)**: exactly what to enter and save in the aMuTorrent and Prowlarr web interfaces; phone-only access, proxy tags, tests and restricted user accounts.
- [Detailed operations](AMUTORRENT-OPERATIONS.md): live verification, network/UID constraints, persistent data, safety and rollback.
- [Prowlarr private management URL](PROWLARR-ACCESS.md): dedicated Tailscale machine, local Pi-hole HTTPS, guarded host setup and recovery.
- Optional Compose examples: [aMuTorrent + Prowlarr](compose.amutorrent.yml) and [TRAWL](compose.trawl.yml).

Don't deploy example overlays over the running host without comparing its current active Compose configuration.

## Transmission and TRAWL

The standard privacy stack uses **one Transmission instance**. TRAWL is Compose-managed on the verified OMV host; the [guarded TRAWL migration helper](migrate_trawl.py) is retained for recovery/reference.

An [optional second-Transmission design](../../docs/optional/transmission-brother/OPERATIONS.md) is archived for reference only and is not part of the default configuration.
