# Coordinated VPN-safe automatic updates

## Purpose

Nightly coordinated image updates for Gluetun, Transmission and Mullvad Browser in the existing /docker/privacy Compose project. WUD continues updating the other approved containers, including the independent Tailscale sidecars.

The updater never substitutes a sample Compose file for the live configuration. It uses the original Compose project and overlay paths read from live container labels and checks image references, bind mounts, service identities and network mode before writing anything.

Safety gates: no active SnapRAID, no paused SnapRAID-managed containers, no duplicate Compose service containers, correct host and project, Gluetun healthy, traffic routed through tun0 with a public VPN egress IP, both clients already in the current Gluetun network namespace, and WUD no longer independently watching the three names. A WUD label that forces watching blocks the handoff.

The updater pulls all three images but does not recreate unchanged services. When Gluetun changes, it stops both VPN clients first, recreates Gluetun, verifies tunnel routing/egress, and recreates both clients attached to the new namespace. When only an app image changes, it recreates only that app. After failures during changes it attempts to stop both VPN clients, never starting them with host networking or manually unpausing an obsolete namespace.

This is deliberately fail-closed, not an atomic upgrade or database rollback mechanism. An unhealthy Docker daemon or disk may prevent even a requested stop. Tunnel-route and egress checks also do not independently prove the Gluetun firewall rule set. A first live update still requires application-level validation.

## Deployment

**Do not activate on the October 18 host state.** The stalled SnapRAID scrub and paused Transmission will cause the preflight to refuse changes. Resolve the SATA issue and restore Transmission on the current Gluetun namespace first.

Stage the reviewed Python source files as root-owned regular files on the known OMV host:

- /docker/privacy/auto_update.py
- /docker/privacy/activate_auto_update.py

Do not copy the example privacy Compose file over the live host: its volumes/overlays may differ.

First run the two read-only preflights:

    python3 /docker/privacy/activate_auto_update.py
    python3 /docker/privacy/auto_update.py

Once the host is healthy and the dry runs pass, activate during a deliberate maintenance window:

    python3 /docker/privacy/activate_auto_update.py --apply
    systemctl status omv-privacy-auto-update.timer --no-pager

Activation verifies WUD, makes a private mode-0600 backup of its current .env, removes only gluetun/transmission/mullvad-browser from the WUD include allowlist, recreates only WUD, checks its effective healthy state and exclusion, then installs and enables a systemd timer. It attempts to restore WUD if recreation fails. No SMTP secrets are printed or copied into GitHub.

The timer schedules updates at **01:30 America/New_York**, with up to five minutes' jitter. It runs before the 02:45 WUD update, 03:00 Docker upgrade and 03:45 SnapRAID schedule. Missed runs are not replayed after reboot (Persistent=false). Any SnapRAID activity or paused container causes a skip/failure until the following day.

The updater submits success/failure notifications to the existing host local root mail transport. Submission is best effort; inspect the journal and verify delivery independently.

## Monitoring and rollback

    systemctl list-timers omv-privacy-auto-update.timer --no-pager
    journalctl -u omv-privacy-auto-update.service -n 100 --no-pager
    python3 /docker/privacy/auto_update.py

Disable only this scheduled updater without touching containers or WUD:

    systemctl disable --now omv-privacy-auto-update.timer

Disabling the timer does **not** automatically re-add the three services to WUD. Reversing that handoff is a separate reviewed change. Never blindly restore an obsolete WUD .env containing older SMTP credentials.

## Repository validation

    python3 -m py_compile docker/privacy/auto_update.py docker/privacy/activate_auto_update.py
    python3 -m unittest discover -s tests -p test_privacy_auto_update.py -v

Offline simulations cover preflight failures, no-change behavior, recreation ordering and fail-closed errors. They are not a live test of Docker, WireGuard, mail or application functionality. A GitHub commit does not deploy the service.
