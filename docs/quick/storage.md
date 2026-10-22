# Storage | Safe starting point

1. List disks, by-id identifiers, UUIDs, filesystems and existing mount sources.
2. Verify whether each device is the OS disk, data, parity, backup or an unknown volume.
3. In a VM, start with **disposable virtual disks**. Configure ext4 mounts, mergerfs branches and SnapRAID metadata only after confirming intended UUIDs.
4. Restore data, parity/content files, UID/GID permissions and dependent application mounts. Check SnapRAID status and diff before scheduling sync.
5. Never interpret SnapRAID as a backup. Verify a separate file restore.

**awtserver does not format, mount or initialize storage.**

Details: [restore requirements](../../migration/debian/restore-manifest.md) · [existing host findings](../../migration/debian/host-findings-2026-10-20.md).
