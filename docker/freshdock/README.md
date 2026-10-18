# Freshdock: replacement for WUD on OMV

Freshdock **v1.7.1**, pinned to `ghcr.io/turbootzz/freshdock:1.7.1`, replaces WUD's unattended Docker update daemon. The public repository stores no email addresses, passwords, VPN keys or authentication tokens.

## Confirmed live evidence

- WUD 9.4.1 **failed** a disposable Compose shared-network update, stranding the dependent at the old parent container ID.
- Freshdock 1.7.1 **passed** manual parent recreation, automatic image update, a forced unhealthy-image rollback, and dependent namespace reattachment, with existing containers unchanged.
- The live WUD configuration on `openmediavault` had an exact 28-name allowlist, 26 currently present selected containers, a daily 02:45 schedule, and 6/6 effective SMTP fields.
- Gluetun is healthy; **Transmission remains paused and refers to an obsolete Gluetun ID**. The two legacy `vaultwarden` and `nginx-vaultwarden` containers refer to a missing Compose file. All five are protected from the first cutover.
- A stale SATA connection was diagnosed earlier; no running SnapRAID process was found, but this is **not** proof of hardware repair.

## Production migration

The migration is split into two stages so a bad Compose file cannot force live application recreation before WUD has been safely inspected.

### Stage 0: pre-cutover read-only checks

`replace_wud_daemon.py` **without** `--apply` verifies the actual live WUD, SMTP, DNS and privacy state. `enroll_services.py --precutover` verifies all currently eligible Compose ownership, *live config hashes*, network dependencies, and kernel SATA state **before WUD is stopped**.

If either fails, **do not run an apply command**; fix the reported source mismatch first.

### Stage 1: replace only the updater daemon

`replace_wud_daemon.py --apply --compose /path/to/verified/compose.yml`

- Import the actual WUD SMTP settings to a private root-owned `/docker/freshdock/freshdock.toml` with TLS based on the existing port (587 STARTTLS, 465 implicit). No secrets are printed.
- Record the selected 26 names from the live WUD watcher in a private root-owned `selected.json`.
- Validate/pull Freshdock; **only after these succeed** disable WUD's restart policy and stop WUD.
- Start Freshdock with `watch_all=false` and fallback mode `watch`. Require scheduler and a configured SMTP notifier at startup, then remove only the stopped WUD *container*. WUD source directory and private credentials are kept as emergency rollback evidence.
- **This alone is not a completed migration**. At this point, no application is opted in; automatic application updates are temporarily on hold.

### Stage 2: opt in only eligible services

`enroll_services.py --apply`

- Stage only `compose.freshdock.yml` overlays in each reviewed active project. An overlay adds labels `freshdock.enable=true`, `freshdock.mode=nightly`, `freshdock.schedule="45 2 * * *"`, and `freshdock.notify=true`.
- Validate effective JSON Compose configs. **Only Freshdock labels may differ** from the previous configuration. Refuse stale hashes, missing source files, unexpected network clients, SATA timeouts, or nonrunning target services.
- Recreate selected services in dependency order with `docker compose up -d --no-deps --no-build --pull never --force-recreate <service>`. No `down`, `--remove-orphans`, volume pruning, data deletion or global `watch_all`.
- Verify each selected app is running, its labels and namespace are correct, and all non-selected existing container IDs/states are unchanged.
- On partial failure, stop the Freshdock daemon (no unattended updates until repaired) and preserve the overlays for reconciliation.

**Important:** The overlays are intentionally separate from the original Compose definitions. Until their inclusion is incorporated into your normal Dockge/manual Compose workflow, **always pass the overlay last** when recreating any service:

```bash
docker compose -p PROJECT --project-directory /docker/PROJECT \
  -f /docker/PROJECT/compose.yml \
  -f /docker/PROJECT/compose.override.yml \
  -f /docker/PROJECT/compose.freshdock.yml \
  up -d SERVICE
```

Include only the base/override files actually present. Otherwise a future Compose recreation can drop Freshdock labels.

## Five intentionally excluded containers

| Container | Why not automatically enrolled yet |
|---|---|
| `gluetun` | VPN network parent; requires actual tunnel, firewall/kill-switch and egress validation |
| `transmission` | **Paused with stale Gluetun network attachment**; do not unpause directly |
| `mullvad-browser` | Shares Gluetun's network; needs end-to-end fail-closed validation |
| `vaultwarden` | Legacy running password-manager service has no recoverable Compose source |
| `nginx-vaultwarden` | Legacy Nginx service has no recoverable Compose source |

The other 21 selected containers are candidates, **not guaranteed eligible**: live hash checks can stop the migration to prevent unrelated drift. This is why both stages have a read-only preflight and a separate apply mode.

After repairing the five exclusions, reconstruct their canonical Compose sources, validate effective image/environment/mount/network configuration without displaying secrets, then explicitly enroll the intended services. No hidden global updater whitelist exists in Freshdock.

## SMTP and scheduling

Freshdock's triggers `succeeded,failed` replace WUD's `success,failure,rollback` events (rollback is a failed update). SMTP startup validation **does not prove message delivery**; a controlled test event is required. The daemon uses America/New_York and mounts host zoneinfo. The calendar trigger is evaluated locally at **02:45** via per-container labels, not via a daemon-wide WUD cron.

## Repository cleanup

This branch removes the obsolete WUD Compose, installer, and test workflow; updates `restart_defined_compose.sh` to reference Freshdock rather than the old Watchtower path. Historic WUD files remain available in Git history. **Do not merge or treat the source as deployed merely because CI passes.** Confirm production cutover output and excluded-service safety first.

Related: [replacement decision #8](https://github.com/dillacorn/omv-remote-dots/issues/8), [Freshdock canary #10](https://github.com/dillacorn/omv-remote-dots/pull/10), [live migration audit #11](https://github.com/dillacorn/omv-remote-dots/pull/11).
