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


## Next tests: actual automatic update and health-gated rollback

The successful initial test used a manual `freshdock recreate`. A separate
`freshdock_auto_canary.py` now tests the actual Freshdock scheduler:

```bash
python3 docker/freshdock/freshdock_auto_canary.py
python3 docker/freshdock/freshdock_auto_canary.py --all
```

The default command performs preflight only. `--all` runs two independent
disposable Compose projects:

1. **Automatic update:** Freshdock 1.7.1 `run --interval 5 --tick 2`
   discovers an upstream digest change for `alpine:3.20`, pulls the current
   image and updates the parent. It must automatically recreate the unlabelled
   network-dependent child onto the parent's new Docker namespace.
2. **Rollback:** The old parent passes a synthetic healthcheck that recognizes
   Alpine `3.20.0`, while the updated `alpine:3.20` fails. Freshdock must
   restore the original parent, reattach the child, and report the rollback.

The test uses a temporary local tag `alpine:3.20` pointed at the old
`alpine:3.20.0` image. **It refuses to start if the `alpine:3.20` tag is
already present or referenced by any existing container.** Each test stage
removes only the tag it created, after removing the disposable Compose stack.
The latest upstream `alpine:3.20` must have a different digest from
`alpine:3.20.0` for meaningful results. External image pulls during the
test could interfere; the script checks original container identities but
cannot prevent unrelated concurrent activity.

The scheduler is restricted to the lone disposable parent by Freshdock's
opt-in labels. Production WUD remains running and its exact watcher filter
must exclude the temporary names. Existing opt-in Freshdock/Watchtower labels
cause an immediate refusal to avoid accidentally updating other containers.
No production container is intentionally recreated or unpaused.

For focused reruns, use `--automatic` or `--rollback`; `--all` is the full
validation. Automatic rollback may take over two minutes due to Freshdock's
health timeout. The test has finite runtime and performs best-effort cleanup
on ordinary errors.

**Neither test exercises a real Gluetun VPN kill switch or SMTP notification.**
Passing both provides stronger evidence for scheduler reliability but does not
authorize production migration.
