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

`replace_wud_daemon.py` **without** `--apply` verifies the actual live WUD, SMTP, DNS and privacy state. `enroll_services.py --precutover` verifies all currently eligible Compose ownership, *live config hashes*, and network dependencies **before WUD is stopped**.

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
- Validate effective JSON Compose configs. **Only Freshdock labels may differ** from the previous configuration. Refuse stale hashes, missing source files, unexpected network clients, or nonrunning target services.
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

## Progressive migration when original Compose hashes have drifted

**Do not rerun the full two-stage command when the read-only enrollment gate
reports `current Compose file hash differs from live container`.** That result
comes from an already-existing difference between the running Compose metadata
and the current source file, not from Freshdock.

The WUD daemon can be replaced independently via
`replace_wud_daemon.py --apply --compose /path/to/verified/compose.yml`.
This step does **not** recreate any application or change its image, network or
mounts. It leaves the selected application list in
`/docker/freshdock/selected.json`, and a strict opt-in Freshdock scheduler
running without enrolled update targets. WUD is removed only after Freshdock
starts and reports its SMTP notifier.

Then run `audit_enrollment.py` **once**. It reports every selected app's
stored-vs-effective Compose hash, local image consistency, environment drift
(count only), bind mounts, network parent ID and restart policy without
printing secret values. It does not stop at the first mismatch, change any
container, or reveal private Compose/environment details.

Do **not** automatically relax hash checks to force a 21-container recreation.
Investigate the complete inventory, reconcile live configuration for the affected
services, and then run the enrollment stage in one reviewed pass. WUD daemon
replacement and service update enrollment are separate verifiable states.

## Verified full-project enrollment for the 2026-10-18 OMV snapshot

The first live post-WUD audit confirmed **21 candidates**, with nine Compose
hash matches and 12 previously existing hash mismatches. Ten hash mismatches
had no differences in the initial runtime comparison. The other two,
`app-ntfy` and `mariadb_jellyseerr`, had image-reference drift, but their
locally tagged image IDs matched the running images.

To avoid declaring the old hashes an automatic failure, the newer
`enroll_services_verified.py` has a **read-only default**:

```bash
python3 docker/freshdock/enroll_services_verified.py
```

It recognizes **only the exact 12 recorded hash mismatches**, checks all
candidate image IDs, selected network-parent dependencies, and safety-sensitive
runtime settings, and requires entire live Compose projects to be in scope.
The two image-reference exceptions are overridden in the generated overlay
with their **currently running image references**, preventing an incidental
image change during label enrollment.

After the plan passes, `--apply` stages overlays, compares effective Compose
configuration to the originals with only those verified changes permitted,
stores a **private 0600 Docker inspect backup** under
`/docker/freshdock/snapshots/`, and recreates each selected project as a
unit using Compose dependency ordering. It verifies image IDs remain unchanged,
all 21 services receive the 02:45 Freshdock labels, and all unselected
containers stay untouched. On partial failure, Freshdock is stopped to prevent
unattended updates of an incomplete fleet.

This is a scoped transition based on one known host snapshot, not a general
purpose authorization to ignore Compose hashes. **A failed read-only check
must not be bypassed.**

A private SMTP send test is available after installation:

```bash
python3 docker/freshdock/smtp_smoke_test.py --send
```

The SMTP test sends one email using the root-only
`/docker/freshdock/freshdock.toml` and never prints authentication details.
Delivery still needs confirmation in the destination mailbox.

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

### Tailscale inline config comparisons

The live nine Tailscale sidecars mount Compose inline JSON configs. Their
content validator reads the file from each running container without printing
its contents or credentials and compares it against the currently rendered
Compose `configs.content` value. Capability strings `CAP_NET_ADMIN` and
`NET_ADMIN` are treated as equivalent (same for `NET_RAW`).

For JSON configs, equivalent parsed JSON data may differ in formatting,
whitespace or member order. **Tailscale also expands `\u0024{TS_CERT_DOMAIN}`**
to its node's actual FQDN when applying the Serve configuration. When the
template contains that placeholder, the preflight gets the DNSName from the
*running sidecar's own* `tailscale status --json`, resolves the placeholder and
requires the **entire parsed JSON document** to match the live config.
A different hostname, HTTP proxy, Funnel setting, or JSON value blocks
enrollment; no service config contents or credentials are printed. No files
in the running containers are modified by the preflight.
