# Health | SMART and UPS

- Disk usage: `awtserver storage usage`.
- Disk identifiers: `awtserver storage disks`; verify stable `/dev/disk/by-id` paths before configuring SMART tests.
- SMART: `smartctl -a /dev/disk/by-id/<verified-id>` (read-only status; some drives require special flags); use `smartd` for scheduled tests/email.
- UPS: use `apcaccess status` for APC UPS information after confirming the service and device. **Never simulate power loss or issue UPS shutdown commands during testing**.
- Verify SMTP delivery, daemon startup, graceful shutdown thresholds, and unattended alerts in a disposable VM before adopting live hardware.

An actual USB-attached UPS and SATA SMART passthrough need hardware verification beyond a VM.
