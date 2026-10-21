# Debian Stable server inventory and recovery

Keep a reproducible record of storage, services and backups before rebuilding or moving a Debian server.

## Reference

- [Service restore checklist](restore-manifest.md) — required services, optional components and deployment order
- [Inventory and migration procedures](OPERATIONS.md) — live-host findings, safeguards and step-by-step recovery planning
- [October 2026 host findings](host-findings-2026-10-20.md) — historical environment-specific evidence

## Safety

The supplied `inventory.py` and `review.py` tools were written for a **specific existing host**. Inspect their host/path checks before reuse on another Debian installation.

Never treat repository Compose examples or an inventory as a verified data backup. Confirm disk identities, parity, mount points, credentials, service networks and rollback before changing an existing system.
