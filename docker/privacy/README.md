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

## aMuTorrent + Prowlarr

Optional multi-user search interface behind Gluetun with Transmission as the download engine. The separate Tailscale application and Pi-hole local HTTPS route are documented in [aMuTorrent operations](AMUTORRENT-OPERATIONS.md). Validate the live Compose stack before using the optional overlay.
