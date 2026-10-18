# WUD 9.4.1 shared-network Compose canary

This test is for the **Docker trigger configured in production**, not the
Docker Compose trigger. It creates a disposable Compose project with two Alpine
containers: a parent on its own network and a child using
`network_mode: service:vpn-parent`. A separate one-shot WUD 9.4.1 instance
(watcher restricted to the parent) tries to update the parent from
`alpine:3.20.10` to a newer published semver tag. The test then checks whether
the child is **still running in the newly created parent's namespace**.

**This disposable test can run while production Transmission is paused or SnapRAID is still stalled.** It does not touch those services or require an operational Gluetun namespace. However, Docker image pulls and container operations perform disk I/O, so an unhealthy disk or Docker daemon may cause errors or timeouts. The canary does not attempt hardware or production service recovery.

## Read-only preflight

Run on the confirmed `openmediavault` host as root:

```bash
python3 docker/wud/wud_stack_canary.py
```

## Disposable live WUD update test

```bash
python3 docker/wud/wud_stack_canary.py --run
```

No production Docker config, Gluetun, Transmission, Mullvad Browser, volumes,
network, WUD instance, SMTP settings or images are intentionally modified.
The test DOES pull small Alpine images, create an isolated Compose network and
two disposable containers, and start a second temporary WUD container with
access to Docker's socket. The temporary WUD watcher has an exact-name filter
and no exposed HTTP port or mail trigger. Strict preflights check production WUD settings, watcher label overrides,
canary name collisions, and the maintenance window; they do **not** require
healthy production applications or an idle SnapRAID scrub. The test cleans up its randomly named project after completion, even
on an ordinary test exception; if cleanup fails it reports the project name.

**Results:**
- `PASS`: WUD actually recreated the parent and the child is running on its
  current namespace.
- `FAIL`: WUD replaced the parent but stranded the dependent child.
- `INCONCLUSIVE`: WUD did not replace the parent (for example registry
  throttling, no semver update or trigger behavior); inspect the displayed logs.

A PASS validates only **this canary Docker-trigger dependency case**. It does
not prove VPN routing/kill-switch behavior, Compose-trigger behavior,
database compatibility, real Gluetun update sequencing, or successful
application-level healthchecks. Those require separate live integration tests
before enabling automatic privacy-stack updates.

Pre-existing production container identity/state snapshots are compared after
the test. If the host changes independently during the test, the script
reports that fact; it does not attempt to restore unrelated services.

## Offline checks

```bash
python3 -m py_compile docker/wud/wud_stack_canary.py tests/test_wud_stack_canary.py
python3 -m unittest discover -s tests -p 'test_wud_stack_canary.py' -v
```

**No host test has been performed from GitHub or a CI run.**
