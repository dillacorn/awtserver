# Watchtower operations and historical verification

## Live 28-container enrollment verified (October 29, 2026)

**Host-confirmed successful deployment:** On `openmediavault`, the operator ran the pinned, guarded `enroll_existing_28.py --check`, then `--apply`. The helper validated the original exact 24-target Watchtower command/private manifest, Compose provenance, healthy Gluetun and all present clients, and the proposed 28-target Compose configuration before writing anything. It then changed **only** the private `/docker/watchtower-fork/compose.yml`, root-private `targets.json`, and installed `watchtower_verify.py`, and recreated **only** the `watchtower` container.

- **Independent verification passed twice**, including a separate `python3 /docker/watchtower-fork/watchtower_verify.py --verify`: `28 healthy targets`.
- Watchtower is `running` with image `nickfedor/watchtower:1.23.1`. The 05:00 `watchtower-fork-verify.timer` remains `active`; its service and SMTP configuration were untouched.
- The helper confirmed that existing application container IDs/states did not change. **No Gluetun, original Transmission, TRAWL, aMuTorrent, Prowlarr, or Tailscale service was recreated.**
- Root-private rollback backup: `/root/awtserver-watchtower-enrollment/20261029T181404Z` (contains the three replaced files). Retain it for manual recovery. This is a **host path**, not a checked-in secret.
- The selected policy is **24 → 28**, adding only `amutorrent`, `prowlarr`, `trawl` and `tailscale-amutorrent`. The server retains **one Transmission**. The unused [second-instance design](../../docs/optional/transmission-brother/OPERATIONS.md) is archived and is **not** enrolled.
- This resolves the earlier `Unapproved additional Gluetun namespace user: trawl` verification failure. **A complete unattended update of the expanded 28-app set, followed by the next 05:00 verification, has not yet been observed.** The verifier detects failures; it does not guarantee automatic rollback of failed application updates.

**Completed prerequisites:** The operator separately migrated TRAWL from standalone to the `privacy` Compose service (without changing Gluetun or Transmission IDs), verified Prowlarr's matching `cloudflare` tags and 1337x `ubuntu` search (80 results, one TRAWL success and zero failures), and identity-checked/deleted the stopped standalone TRAWL backup while preserving its root-only inspect JSON.

### Recovery and implementation

The reviewed [enrollment helper](enroll_existing_28.py) was a **one-time 24→28 migration**. Its read-only `--check` and scoped `--apply` both require the **original** exact 24-target command/manifest, so **do not rerun either against the successfully updated 28-target installation**. For subsequent status checks, use the installed read-only `watchtower_verify.py --verify`. For recovery, inspect the current live state and the root-private backup first; do not blindly restore an old 24-target allowlist, which would reinstate the unselected VPN-client verification failure.

The helper's apply mode used exact Compose provenance and health guards, atomically replaced the three private files, and invoked `docker compose ... up -d --no-deps --no-build --pull never watchtower`. A failure would have triggered a best-effort rollback to the original 24 targets; no such rollback was needed in the successful operator output. Watchtower remains scheduled for `0 45 2 * * *` (02:45 America/New_York), with independent 05:00 verification. No live-update outcome is implied by the guarded helper or GitHub CI.


---


**2026-10-21 update:** The server operator reports a successful overnight Watchtower update with applications remaining up. Earlier October 20 verification caveats below are historical snapshots.

---

# OMV maintained Watchtower fork

Active updater: [Nicholas Fedor's Watchtower](https://github.com/nicholas-fedor/watchtower),
pinned to `nickfedor/watchtower:1.23.1`.

## Production state (October 20, 2026)

The user verified an installation on host `openmediavault` using the
reviewed GitHub commit `ba59c8eb29fddffb6abf7376c4c584f512d6abe3`.
The recorded output confirms:

- The new Watchtower container is running with an **exact 24-container**
  positional allowlist and `0 45 2 * * *` cron, using
  `TZ=America/New_York` (02:45 local).
- Existing application containers were **not recreated** during installation.
- `gluetun`, `transmission`, and `mullvad-browser` are included;
  Vaultwarden's unsupported legacy Compose stack is excluded.
- The old updater was stopped with Docker restart disabled.
- A TLS SMTP setup message was accepted by the server.
- A 05:00 local root systemd verification timer was enabled.
- The first post-install 24-container verification succeeded.

The **first real unattended update**, actual SMTP inbox receipt, a
Shoutrrr delivery, and authenticated VPN recovery after a future Gluetun
update are **not yet verified** by this installation output.

## Repository and host cleanup

The superseded `docker/freshdock/` source tree, Freshdock-only tests and
workflows were removed from this repository. Historical changes remain in Git.

**Do not remove the old host directory before switching the verifier.**
The initially installed `/docker/watchtower-fork/replace_freshdock.py`
5 AM verifier still reads `/docker/freshdock/freshdock.toml` for failure
alerts. Deleting that directory first would silently break future warnings.

Two separately reviewed tools replace that dependency:

- `watchtower_verify.py`: independent, read-only verifier of exactly
  24 known services, Docker health, source Compose files, namespace
  dependencies, the Gluetun firewall constraints and the updater schedule.
  It sends a TLS alert on failure using only the root-private
  `/docker/watchtower-fork/alert_smtp.json`. It never changes containers.
- `retire_freshdock.py`: default **read-only** guarded retirement.
  `--apply` copies *only* required SMTP settings to the new 0600 file,
  tests real TLS SMTP, atomically changes the existing 05:00 verifier
  service to call the independent script, checks its systemd execution,
  and only then removes the stopped **Freshdock container**, old
  `/docker/freshdock` directory, and obsolete installer copy.
  It attempts removal of the unused old Docker image **without force**.
  It never runs `docker compose down`, recreates apps, deletes Docker
  volumes, or prunes unrelated images.

Retirement fails closed if the current host, old stopped container, timer,
network dependencies, Compose source paths or mounts differ from expectations.
If systemd or the TLS handoff fails **before deletion**, the old service
configuration is restored and the new files are removed. It will not
automatically repair an interrupted removal after the irreversible step:
the operator must inspect the actual state, not rerun blindly.

**Deployment is separate from GitHub.** Obtain both Python files from the
same reviewed, pinned commit. Verify their Git blob hashes, place them in
a private temporary directory on OMV, then run the helper first without
`--apply`, inspect PASS, and run `--apply`. The final exact commands are
supplied after CI validation. No host-side removal is done by GitHub Actions.

Some **legacy Freshdock labels and `compose.freshdock.yml` overlays may
remain attached to current application containers**. Removing those files
while Docker Compose's original configuration references them could break
future application recovery. Watchtower itself ignores the old Freshdock
labels. Removing or rewriting those application overlays is a separate
Compose migration, not part of the stopped-updater deletion.

## Why Watchtower replaced Freshdock

The unpatched Freshdock v1.7.1 stranded applications during the October 19–20
unattended updates with Docker HTTP 400 conflicting hostname/network-mode
errors. Watchtower v1.23.1 was subsequently tested on disposable GitHub-hosted
Docker networks, with both direct shared-namespace child updates and
parent-plus-two-dependent updates. [PR #18 CI](https://github.com/dillacorn/omv-remote-dots/pull/18)
includes real Gluetun v3.40.4 -> v3.41.3 fail-closed VPN tests with an invalid
WireGuard endpoint and active startup egress probes.

Important caveat: Watchtower's linked restart path **does not wait for VPN
health**, and its Docker create/start failure path **does not guarantee
rollback**. A disposable missing-bind-mount test confirmed that a failed
recreate can remove the original application container. The independent
05:00 verification timer adds failure **detection**, not automatic restoration.

The guarded 24-container allowlist ensures network parent and dependent
containers are both selected. It rejects unknown namespace children and
labels that hide the true parent. Real production authenticated VPN
reconnection and the first 02:45 cycle still need observation.

## Artifacts and tests

- `compose.yml` is **documentation only**, with an intentionally invalid
  positional target. The live private Compose file remains on the host at
  `/docker/watchtower-fork/compose.yml`.
- `replace_freshdock.py` documents the *already-completed initial migration*.
  It is not a post-retirement update command; its legacy verifier needs
  replacing before deleting the old files.
- `watchtower_verify.py` and `retire_freshdock.py` are the maintained
  standalone retirement/monitoring implementations.
- `tests/test_watchtower_verifier.py` covers independent monitoring,
  fail-closed VPN guards, SMTP TLS/0600 secrets, successful retirement
  without touching other containers, and restoration on systemd failure.
- `tests/watchtower_fork_live.py` and
  `tests/watchtower_fork_gluetun_live.py` run isolated real Docker tests.
- `.github/workflows/watchtower-fork-tests.yml` runs syntax, unit tests,
  Compose validation, and both disposable Docker suites.

Neither SnapRAID nor unrelated applications are modified by this repository
cleanup. No GitHub Release is required for these repository changes.
