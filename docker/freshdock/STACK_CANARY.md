# Freshdock v1.7.1 shared network namespace test

WUD 9.4.1's individual Docker trigger failed the equivalent disposable parent/child test: the parent was replaced, but the dependent remained running and referenced the old parent ID.

This canary tests Freshdock **before any WUD-to-Freshdock migration**.

## Test behavior

- Identifies the actual OMV host and existing WUD Compose service; verifies that WUD uses a strict allowlist that **cannot** select the disposable containers.
- Creates a unique temporary Compose project under /tmp using two Alpine test containers.
- The parent has Freshdock opt-in labels, with `mode=watch` so an automatic scheduler could not update it. The child uses `network_mode: service:parent`, with **no** Freshdock opt-in.
- Runs **one** temporary Freshdock v1.7.1 CLI container and explicitly calls `recreate <test-parent>`. It does not run the Freshdock background scheduler or install a permanent Freshdock container.
- Reads the **real Docker IDs** after the recreation. A pass requires a new parent ID, both containers running, and the child's `HostConfig.NetworkMode` pointing to that new ID.
- Removes only the disposable test project, then checks the original containers' IDs/states for unintended changes.

The test intentionally works with production Transmission paused and does not require SnapRAID to finish or the SATA cable to be replaced. I/O faults can still interrupt Docker operations.

### Run on openmediavault (root)

Read-only preflight:

    python3 /path/to/freshdock_stack_canary.py

Execute disposable live test:

    python3 /path/to/freshdock_stack_canary.py --run

The script has a scheduled-updater/SnapRAID time-window guard to avoid racing WUD or host maintenance.

## Scope

**Not a production migration.** The script does not recreate or unpause Gluetun, Transmission or Mullvad Browser, and does not modify WUD configuration, Compose definitions, data directories or persistent Docker volumes. It does pull/cache Alpine and Freshdock images and creates/removes a disposable Compose network and containers.

**A PASS only proves the manual Freshdock recreate/reattach path**, not an automatic registry-change event, its scheduler, rollback on unhealthy VPN, kill-switch integrity or WUD-to-Freshdock SMTP migration. Test those separately before a full cutover.

Upstream references:
- https://github.com/Turbootzz/freshdock
- https://github.com/Turbootzz/freshdock/blob/main/docs/cli-reference.md
- https://github.com/Turbootzz/freshdock/blob/main/src/docker/recreate.rs

Related: #8, WUD failed canary in PR #9.
