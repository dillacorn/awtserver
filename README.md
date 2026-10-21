# `awtserver`

#### [Debian migration plan](migration/debian/README.md) · [Restore manifest](migration/debian/restore-manifest.md) · [Pi-hole & DNS](docker/pihole/README.md)

---

**awtserver** is an SSH/CLI-first collection of server configuration, scripts, and documentation intended for **OpenMediaVault (OMV)** and **vanilla Debian Stable**. It is not a Linux distribution or a replacement for either operating system.

**Current status:** The repository documents and maintains an existing OMV server. A standalone Debian setup is planned, but there is no production-ready installer or verified migration path yet.

## Two supported paths (one current, one planned)

- **OpenMediaVault — current:** Keep OMV's storage management and web interface, with awtserver providing additional service configuration and maintenance helpers.
- **Vanilla Debian — planned:** Run the same needed services using native Debian tools, systemd, and Docker Compose, without requiring OMV. Migration is optional, not a prerequisite.

Both paths aim to share reusable configuration and scripts where practical, without interfering with the host's existing management tools.

## What it covers

These are current OMV services and future Debian feature goals, **not** a claim that one installer provisions everything.

| Area | Components |
| --- | --- |
| **Administration** | SSH, TTY, systemd, optional management helpers |
| **Storage** | ext4, [SnapRAID](https://www.snapraid.it/), [mergerfs](https://github.com/trapexit/mergerfs) |
| **Applications** | Docker Engine, Docker Compose, optional Dockge |
| **Network and DNS** | Tailscale, Pi-hole, Quad9 upstream DNS, Gluetun |
| **Security** | Fail2ban, firewall, service-specific access controls |
| **Reliability** | SMART monitoring, APC UPS, scheduled jobs, alerts, backups and restore |
| **Optional** | Samba/SMB when enabled |

## Approach

- **CLI-first, not CLI-only:** Prefer inspectable files and SSH tools; keep OMV's web interface available on OMV systems.
- **Modular:** Share setup and maintenance helpers without requiring a new control panel.
- **Safe changes:** Verify disks, mounts, permissions, parity, backups, and rollback procedures before migration or recreation.

## Documentation

- [Debian migration plan](migration/debian/README.md): inventory, safeguards, and staged validation for a possible move away from OMV
- [Restore manifest](migration/debian/restore-manifest.md): service requirements and acceptance checks
- [Pi-hole & DNS](docker/pihole/README.md): DNS and profile management
- [Watchtower](docker/watchtower/README.md): automatic Docker updates
- [Seerr](docker/seerr/README.md): media requests

## External references

- [SnapRAID AIO scripts](https://github.com/auanasgheps/snapraid-aio-script/tree/master)
- [APC UPS setup walkthrough](https://youtu.be/MyXrlRUBqyg)

## License

Project code and configuration are licensed under the [MIT License](LICENSE). Third-party projects retain their own licenses.

## Donate

Built and maintained out of passion. Always FOSS. Donations appreciated.

[Donate via PayPal](https://www.paypal.com/donate/?business=XSNV4QP8JFY9Y&no_recurring=0&item_name=Built+and+maintained+out+of+passion.+Always+FOSS.+Donations+appreciated.+%28smtty%2C+MicLockTray%2C+awtarchy%29&currency_code=USD)
