# `awtserver`

#### [Debian migration plan](migration/debian/README.md) · [Restore manifest](migration/debian/restore-manifest.md) · [Docker service notes](docker/pihole/README.md)

---

**awtserver** is not a Linux distribution. It is a planned SSH/CLI-first server management environment for minimal Debian Stable, following the same base-OS-plus-managed-configuration approach as [Awtarchy](https://github.com/dillacorn/awtarchy).

**Current status:** This repository still supports an existing OpenMediaVault server with scripts, service notes, and Docker/Compose examples. The live host has not migrated to vanilla Debian. No cutover date or production-ready installer is claimed.

## Install model

1. **Today:** Keep the working OMV server running and maintain its existing services.
2. **Future:** Install minimal Debian on a separately verified OS SSD, then restore the OMV features actually used, rather than reproducing the entire OMV web interface.
3. **After validation:** Manage the server with SSH, native Debian utilities, systemd, Docker Compose, and reviewable scripts.

The [migration plan](migration/debian/README.md) documents the inventory, prerequisites, backup and rollback safeguards, and staged verification needed before cutover.

## Why this approach

- **Direct control:** Plain configuration files and native Debian services instead of an OMV-specific management database.
- **CLI-first:** SSH and TTY administration; optional web or terminal interfaces must not become required dependencies.
- **Reproducible:** Version-controlled configuration and individually usable setup and maintenance helpers.
- **Conservative storage handling:** Verify mounts, backups, parity, ownership, and restore behavior before any migration.

## Server overview

These are **current services and future feature-parity goals**, not a claim that an awtserver installer already provisions them.

| Area | Components |
| --- | --- |
| **Foundation** | [Debian Stable](https://www.debian.org/releases/stable/) (future); OpenMediaVault on Debian (current) |
| **Administration** | SSH, TTY, systemd, optional standalone management helpers |
| **Storage** | ext4, [SnapRAID](https://www.snapraid.it/), [mergerfs](https://github.com/trapexit/mergerfs) |
| **Applications** | Docker Engine, Docker Compose, optional Dockge |
| **Network and DNS** | Tailscale, Pi-hole, Quad9 upstream DNS, Gluetun isolation |
| **Security** | Fail2ban, firewall, service-specific access controls |
| **Reliability** | SMART monitoring, APC UPS, scheduled jobs, alerts, backup and restore |
| **Optional** | Samba/SMB when explicitly enabled |

## Documentation

- **Migration inventory, implementation stages, and safety requirements:** [Debian migration](migration/debian/README.md)
- **Service requirements and acceptance checks:** [Restore manifest](migration/debian/restore-manifest.md)
- **Pi-hole and DNS profile management:** [Pi-hole](docker/pihole/README.md)
- **Automatic Docker updates:** [Watchtower](docker/watchtower/README.md)
- **Media requests:** [Seerr](docker/seerr/README.md)

## External references

- [SnapRAID AIO scripts](https://github.com/auanasgheps/snapraid-aio-script/tree/master)
- [APC UPS setup walkthrough](https://youtu.be/MyXrlRUBqyg)

## License

Project code and configuration are licensed under the [MIT License](LICENSE). Third-party projects retain their own licenses.

## Donate

Built and maintained out of passion. Always FOSS. Donations appreciated.

[Donate via PayPal](https://www.paypal.com/donate/?business=XSNV4QP8JFY9Y&no_recurring=0&item_name=Built+and+maintained+out+of+passion.+Always+FOSS.+Donations+appreciated.+%28smtty%2C+MicLockTray%2C+awtarchy%29&currency_code=USD)
