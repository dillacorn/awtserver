# Maintained Watchtower fork: Freshdock replacement for OMV

Target: [nicholas-fedor/watchtower](https://github.com/nicholas-fedor/watchtower)
v**1.23.1** (`nickfedor/watchtower:1.23.1`, 2026-10-13).
See [Watchtower documentation](https://watchtower.nickfedor.com/v1.23.0/).

## Incident / decision

The running, unpatched `ghcr.io/turbootzz/freshdock:1.7.1` caused
Docker HTTP 400 `conflicting options: hostname and the network mode`
on shared-network clients, stopping and archiving Ntfy on October 19 and
Ntfy, Jellyfin and FreshRSS on October 20. The three original applications
were restored and verified running behind their original Tailscale parents.
Freshdock has been **stopped with Docker restart=no**.

A tested source patch for Freshdock exists separately in draft PR #17; that
patch is **not deployed** and is not needed for the fork migration.

## Scope and protection

`replace_freshdock.py` has read-only default; apply is explicit.
It validates the real OMV host, Docker and Compose, and the currently
**stopped** Freshdock daemon. It requires exactly 21 currently running
Freshdock nightly opt-ins and the three additional intended VPN stack
containers, for a strict **24-container** Watchtower *positional allowlist*.

Unlike Freshdock, Watchtower can target these names without changing
application labels, image IDs, bind mounts or Compose configurations.
Therefore **no existing application is recreated during updater installation**.

The new updater includes **Gluetun, Transmission and Mullvad Browser**, not a
permanent exclusion. Before permitting them it checks the Gluetun health
status, both applications' `HostConfig.NetworkMode` against the *current*
Gluetun ID, and rejects additional unknown Gluetun namespace users. The
automatic future Gluetun update/kill-switch still requires real validation;
matching a network namespace is not a VPN egress test.

**Existing Vaultwarden and nginx-vaultwarden are intentionally excluded**
because their legacy Compose source was not established. They must not be
silently enrolled. No other containers are selected by default.

## Verified constraint: no partial network groups

The first real Docker CI run (2026-10-20) confirmed a direct update of a
network-sharing application **passes**, but updating *only the parent*
without selecting its two running dependents left those dependents
attached to the old container ID. The runner correctly FAILED.

The guarded migration now verifies that **every network-sharing
dependent (including stopped containers) of every targeted parent is on
the same exact target list**, and rejects explicit/Compose dependency labels
that hide the true network parent.
It refuses partial network groups. [The successful follow-up Docker canary
(run 39410256380)](https://github.com/dillacorn/omv-remote-dots/actions/runs/39410256380)
updated the parent and reattached BOTH selected dependents, verified running
on the new parent's namespace. Its direct-child update also passed.
Watchtower dependency ordering is not a guarantee of repairing dependents
that are omitted from the watched scope.

## SMTP and scheduling

Schedule: `0 45 2 * * *` (six-field seconds/minutes/hours Watchtower cron)
with `TZ=America/New_York`. This matches 02:45 local time and retains the
existing private SMTP destination and credentials.

The original `/docker/freshdock/freshdock.toml` is parsed privately and
converted to a Shoutrrr SMTP URL with explicit `ExplicitTLS`/STARTTLS
(port 587) or `ImplicitTLS` (465). STARTTLS on 587 is explicitly required (fail closed if the SMTP server
does not advertise STARTTLS); 465 uses implicit TLS from the outset.
The URL is stored at
`/docker/watchtower-fork/notification_url` mode 0600; Watchtower reads
it from `/run/secrets/notification_url`. Docker inspect and Compose
environment reveal **only the secret file path**, never the password.

Watchtower does not provide Freshdock's equivalent preflight
health-gated rollback guarantee. The v1.23.1 batch update implementation
stops dependents, replaces the parent, and starts dependents in graph order,
but **does not wait for the new parent's Docker health status** before starting
its children. Its health-waiting rolling restart feature explicitly does not
support linked containers. Thus namespace reattachment alone **does not
prove the VPN kill switch is engaged before Transmission/Mullvad Browser starts**.
The actual Gluetun startup and firewall sequence must be established before
unattended production VPN-parent updates can be approved.

The v1.23.1 application-create/start failure path records failures but does
**not automatically restore the previous application container**. The old
image remains available when cleanup is disabled, but recovery would require
an explicit, separately validated procedure. SMTP notification delivery can
also fail independently, so a log or successful daemon startup is not proof
an outage will be noticed.

**Production deployment remains blocked on VPN readiness/egress assurance and
a failure-response plan**, even if all isolated Docker network tests pass.
Do not silently drop the VPN trio from the requested 24-target scope.
An alternative to evaluate if the fork cannot provide this guarantee is a
health-gated coordinated Compose update for the complete VPN group, or a
tested change to Watchtower's dependency-restart lifecycle. Either approach
requires inspecting actual OMV Compose identities and should be validated
on disposable stacks first, not improvised against production.

## Guarded host migration

No OMV commands are executed by GitHub Actions, and committing/merging
this repository does not deploy anything. After a successful CI test and
review, use a *pinned SHA* from this PR, never an unreviewed floating URL.

1. Copy the exact `docker/watchtower/replace_freshdock.py` from the
   reviewed commit to a private temporary location on OMV.
2. Run `python3 /path/to/replace_freshdock.py` for a read-only check.
3. Only after it reports an exact list of 24 targets and current healthy VPN
   namespaces, run `python3 /path/to/replace_freshdock.py --apply`.
4. The installer stages files only under `/docker/watchtower-fork`, pulls
   pinned Watchtower v1.23.1, starts its daemon, and verifies all original
   container IDs and states were left unchanged. On a failed installation,
   it disables/stops the new Watchtower daemon; Freshdock remains stopped.
5. Review the new Watchtower logs, confirm SMTP delivery using a controlled
   event, and verify the *first real scheduled update* before calling the
   migration complete.

The public `compose.yml` in this directory is **documentation only** and
contains a deliberately unmatchable sentinel positional target. Do not
run it directly. Only the private generated file has actual target names.

**Do not start Freshdock again.** Do not run both updater daemons together.
Do not delete Freshdock's private files, original volumes, old images or any
app container. Do not run this migration while SnapRAID is actively running.

The source helper `docker/restart_defined_compose.sh` is adjusted in this
branch to target the new directory, not the retired daemon. Existing
copies on the server do not change until separately updated.

## Testing requirement

CI: `.github/workflows/watchtower-fork-tests.yml`

- Python migration unit tests and syntax
- Docker Compose syntax validation
- Real `nickfedor/watchtower:1.23.1` Docker canary: direct update of
  `network_mode: service:parent` app, with untouched parent/sibling
- Real parent update with two network-sharing dependent applications,
  all verified running and attached to the updated parent
- Real always-running Watchtower daemon with short polling interval
  automatically updates two selected network-sharing applications, preserves
  their parent and exits cleanly on disposal. **PASS**:
  [GitHub Actions run 39410790762](https://github.com/dillacorn/omv-remote-dots/actions/runs/39410790762);
  run logs: scanned=2, updated=2, failed=0. The same run verified direct
  child updates and parent/two-child reattachment again (all green).

If any live test fails, this migration is **BLOCKED**. It is not permission
to deploy the same untested behavior to the live OMV host.
