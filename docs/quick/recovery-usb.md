# Backup USB | OS recovery

1. Identify the **dedicated USB backup disk by UUID** (`lsblk -f`). Never assume an unmounted or unknown USB device is a backup target.
2. Manually mount it and verify with `findmnt`. No awtserver command formats or mounts a disk.
3. Initialize an encrypted **restic** repository separately. Keep the restic password in a root-owned mode 0600 local file, with an **independently stored recovery copy**.
4. `awtserver backup plan --mount /mnt/backup-usb --uuid UUID` checks that exact mount and previews OS-config coverage.
5. In a disposable Debian 13 VM only, `backup snapshot ... --password-file /root/backup-password --apply --confirm-vm` performs the OS config backup **to an already initialized repository**.
6. Run `awtserver backup restore-stage --mount /mnt/backup-usb --uuid UUID --password-file /root/backup-password` to preview an isolated recovery. On a disposable Debian 13 VM only, add `--apply --confirm-vm` to restore to a **fresh, root-private** staging directory. Verify sampled files and package/boot/EFI dependencies. Never restore straight into the running root filesystem.

Default OS scope: `/etc`, `/usr/local`, `/opt/awtserver`. **Not covered:** Docker application volumes/databases, parity/data disks, full bootable OS imaging or current OMV host. These need separately tested backups. No automatic backup timer, bootable imaging or pruning yet. Recovery staging is not a complete disaster-recovery restore.
