# OMV job schedules | October 22, 2026

**Read-only audit, not deployment configuration.** Captured from the user's sanitized OMV jobs/rsync audit. No commands, usernames, source/destination paths, credentials or host identifiers are included.

| OMV entry | Status | Schedule | Category | OMV email |
| --- | --- | --- | --- | --- |
| Custom 1 | Disabled | Monthly macro | Backup | Yes (inert) |
| Custom 2–4 | Disabled | `* * * * *` each | Docker-related | No (inert) |
| Custom 5 | Enabled | Daily `45 3 * * *` | SnapRAID, Docker, Bash | Yes |
| Custom 6 | Enabled | `@weekly` | Docker, Bash | Yes |
| Custom 7 | Enabled | Daily `0 3 * * *` | Backup | Yes |
| Rsync 1 | Enabled | Sundays `45 5 * * 7` | Local push | No |
| Rsync 2 | Enabled | Monthly on 17th `0 6 17 * *` | Local push | No |

Rsync tasks both have: `delete=no`, `dryrun=no`, `archive=yes`, `recursive=yes`, `acls=no`, `xattrs=no`. No verified success, restore or destination inspection is implied.

## Possible timing conflicts

- **Daily 03:00 → 03:45:** only 45 minutes between backup and SnapRAID starts. Actual overlap depends on runtime and locking.
- **Sunday 05:45 → monthly 17th 06:00:** only 15 minutes apart when the 17th is Sunday. They may overlap.
- **Weekly macro:** actual expansion and timing under the deployed cron implementation must be verified, along with collisions and timezone.
- **Five active entries only:** three user-defined OMV cron jobs plus two OMV rsync jobs. Four disabled custom jobs must remain disabled.
- **No automatic import:** Preserve current cron ownership while OMV runs. Never install duplicates, change scheduling or activate jobs based on this document.

## awtserver development

Run `awtserver schedules list` or `awtserver schedules review --min-gap 60` to inspect the **historical sanitized example only**. The reviewer does not know actual job commands or durations and cannot deploy schedules.

Before native migration: verify exact script purpose, scheduler ownership, run duration, independent locks, dependencies, success/error status, email delivery, rsync destinations and actual backup restore. Check timer interactions with Watchtower, certificate/DNS guards and automatic updates. The existing SnapRAID script is **not proven** to live at conventional paths.

See [October 22 host capabilities](host-findings-2026-10-22.md), [sanitized example JSON](../../docs/examples/omv-schedules-2026-10-22.json), [scheduler implementation gates](../../docs/IMPLEMENTATION.md).
