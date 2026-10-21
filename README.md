# deb-omv-dots
scripts and additional setup I do on my openmediavault systems

SnapRAID scripting
https://github.com/auanasgheps/snapraid-aio-script/tree/master

APC UPS configuration
https://youtu.be/MyXrlRUBqyg

## Long-term direction: headless Debian server toolkit

`awtserver` is a **working name** for a future Awtarchy-style, SSH/CLI-first server environment on vanilla Debian Stable. The goal is to replace **the OpenMediaVault features actually used**, not duplicate OMV's entire web interface. Native Debian tools, Docker Compose, plain configuration files and optional standalone management helpers should remain the sources of truth.

**No rename or migration is scheduled.** This repository continues to support the working OMV server. Consider renaming it only after the new Debian environment has passed restoration and operational checks.

A read-only inventory tool and staged plan for eventually replacing the OMV OS SSD with a minimal Debian/SSH installation are in [migration/debian/](migration/debian/README.md). This includes **non-Docker** services such as Fail2ban, Samba/NFS, UPS/SMART, systemd timers, firewall and networking. The inventory only writes private metadata under `/root` on the live host; never commit its JSON output to this public repository. **No host cutover is scheduled.**

## Docker

Pi-hole profile management, encrypted Quad9 upstream DNS, LAN/Tailscale DNS access, and optional profile-aware Arachnidium proxy examples are documented in:

`docker/pihole/README.md`

## License
This project is licensed under the [MIT License](https://github.com/dillacorn/deb-omv-dots/blob/main/LICENSE)

## ☕ Donate

Built and maintained out of passion. Always FOSS. Donations appreciated.  
[Donate via PayPal](https://www.paypal.com/donate/?business=XSNV4QP8JFY9Y&no_recurring=0&item_name=Built+and+maintained+out+of+passion.+Always+FOSS.+Donations+appreciated.+%28smtty%2C+MicLockTray%2C+awtarchy%29&currency_code=USD)
