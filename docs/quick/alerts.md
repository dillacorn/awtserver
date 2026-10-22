# Monitoring | Disk and email

- `awtserver monitor stats` shows load, memory and uptime.
- `awtserver storage usage --threshold 80` reports space and exits with code 2 for warnings. Review physical disk mounts **separately from** mergerfs pool totals to avoid double counting.
- For missing-mount or fullness warnings, create a **root-owned mode 0600** JSON config at `/etc/awtserver/monitor.json`:
  `{"threshold":80,"mounts":["/","/mnt/data"],"recipient":"you@example.com"}`
- `awtserver monitor check` is read-only. `awtserver monitor notify` only previews. On a disposable Debian 13 VM, add `--apply --confirm-vm` to send a warning through a configured local `sendmail`/Postfix MTA.
- Test mail delivery independently. **No scheduled notification timer, spam suppression, SMTP credentials or real NAS deployment yet.** Do not schedule repeated notifications until deduplication/alert recovery are implemented.

SMART attribute/temperature failures require `smartd` configuration separately. Disk fullness and SMART health are different checks.
