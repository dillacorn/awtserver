# `awtserver`

**Debian Stable server setup and management, focused on SSH and the command line.**

awtserver collects reusable scripts, Docker Compose configurations, and maintenance guides for a headless home server. It uses standard Debian tools rather than a custom distribution or required control panel.

## Components

| Area | Tools |
| --- | --- |
| **Storage** | ext4, [SnapRAID](https://www.snapraid.it/), [mergerfs](https://github.com/trapexit/mergerfs) |
| **Containers** | Docker Engine, Docker Compose, optional Dockge |
| **Networking** | Tailscale, Pi-hole, encrypted upstream DNS, Gluetun |
| **Security** | SSH, Fail2ban, firewall |
| **Maintenance** | SMART, UPS shutdown, backups, scheduled updates and alerts |

## Install

On Debian 12/13, install the **awtserver command only**:

```bash
curl -fsSL https://raw.githubusercontent.com/dillacorn/awtserver/main/install.sh | sudo bash
```

Then run `awtserver` (TUI), `sudo awtserver update` or `sudo awtserver uninstall`. Installer changes only its own program files. **Server configuration remains experimental and write-blocked outside disposable Debian 13 VMs**, including on OMV. Review [installation, updates and uninstall safety](docs/awtserver-cli.md) before running the remote script.

Quick guides: [per-app Tailscale](docs/quick/remote-apps.md) · [Android Auto Rules](docs/quick/android-auto.md) · [implementation progress](docs/IMPLEMENTATION.md).

## Documentation

- [Docker services](docker/README.md) — container configurations and service guides
- [Pi-hole](docker/pihole/README.md) — DNS, blocking profiles and `pihm`
- [Watchtower](docker/watchtower/README.md) — selected container updates and verification
- [Seerr](docker/seerr/README.md) — media requests
- [Server inventory and recovery](migration/debian/README.md) — host rebuild safeguards and service checklist

## Principles

- **CLI-first:** Debian, systemd and plain configuration files stay in control.
- **Modular:** Use the services and scripts you need; there is no all-in-one installer.
- **Data-safe:** Verify mounts, volumes, parity, backups and recovery before making changes.

## License

Code and configuration: [MIT License](LICENSE). Third-party projects keep their own licenses.

## Donate

Built and maintained out of passion. Always FOSS.

[Donate via PayPal](https://www.paypal.com/donate/?business=XSNV4QP8JFY9Y&no_recurring=0&item_name=Built+and+maintained+out+of+passion.+Always+FOSS.+Donations+appreciated.+%28smtty%2C+MicLockTray%2C+awtarchy%29&currency_code=USD)
