# Watchtower

Automatic Docker image updates using [Nicholas Fedor's maintained Watchtower fork](https://github.com/nicholas-fedor/watchtower).

## Configuration

- **Image:** `nickfedor/watchtower:1.23.1` in the documented deployment.
- **Scope:** Explicitly selected containers, including related VPN/network-namespace services.
- **Schedule:** 02:45 America/New_York; independent read-only verification at 05:00.
- **Observed:** The October 21, 2026 overnight run updated applications successfully, per the server operator.

The checked-in `compose.yml` is an **example**, not the live private deployment. Watchtower may not roll back an unsuccessful container recreation; the verifier detects failures but cannot automatically repair every service.

[Detailed deployment, verifier, rollback limitations and test evidence](OPERATIONS.md)
