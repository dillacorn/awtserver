# SnapRAID | AIO v3.4

1. Install SnapRAID and review real parity/content/data paths and exclusions. Verify with `snapraid status` (read-only). **Do not initialize parity or force sync on existing disks.**
2. Use the upstream [SnapRAID AIO v3.4 release](https://github.com/auanasgheps/snapraid-aio-script/releases/tag/v3.4). Review/download locally; verify a **trusted SHA-256** of `snapraid-aio-script.sh` first.
3. `awtserver snapraid prepare --source /path/to/snapraid-aio-script.sh --sha256 <64-hex>` previews staging. On a disposable Debian 13 VM, explicit `--apply --confirm-vm` copies that checked script; **it does not run it**.
4. Install/review the matching private `script-config.conf` separately. Check `CONFIG_VERSION=3.4`, parity paths, Docker pause list, notification setup, scrub and sync thresholds.
5. `awtserver snapraid enable --schedule "30 1 * * *"` previews a daily 01:30 job. `disable` previews stopping it. On the VM only, `--apply --confirm-vm` records the choice.
6. `awtserver snapraid sync` previews the managed root cron file; **separate explicit** `sync --apply --confirm-vm` deploys it after prerequisites pass. Cron starts at the next scheduled run, not immediately.

Do not overlap the SnapRAID window with Watchtower or other maintenance. Upstream AIO already supplies diff/sync/scrub, thresholds and reporting; no competing engine is implemented.
