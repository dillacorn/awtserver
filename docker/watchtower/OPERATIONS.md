# Watchtower operations and historical verification

## Enroll current VPN applications (October 29, 2026)

The live Watchtower fork still selects **24** containers, so its independent verifier fails for additional Gluetun namespace users. This is an **existing 24-target enrollment problem**, not a requirement for a second Transmission.

**Confirmed host progress:** `trawl` was migrated from a standalone container into Compose project `privacy`. Gluetun and the original Transmission container IDs were unchanged. Prowlarr's saved `cloudflare` tags matched the TRAWL proxy and the 1337x indexer; a `ubuntu` search returned 80 results and one successful TRAWL request (zero failures). The old stopped TRAWL container `trawl-standalone-backup-20261029t172518z` was identity-checked and removed. Its root-only Docker inspect JSON was retained.

**The only proposed Watchtower change is 24 → 28 selected containers**: add `amutorrent`, `prowlarr`, `trawl`, and `tailscale-amutorrent`. No additional Transmission container, RPC port, VPN peer port, or Tailscale device is part of this policy. The updated verifier recognizes the original 24 and exact 28 policy, rejects partial enrollment, and requires every selected Gluetun consumer to share the **current** healthy parent namespace without elevated network privileges. It also requires valid Compose sources and a matching strict Watchtower positional target list.

**Not installed on the host:** The private `/docker/watchtower-fork/compose.yml`, root-owned mode-0600 `targets.json`, and independent 05:00 verifier still require a guarded, coordinated update. The GitHub code change does not update the running Watchtower.

The [guarded enrollment helper](enroll_existing_28.py) provides a **read-only** `--check` and separate `--apply`. Stage it together with the same revision of `watchtower_verify.py` in a private root-only directory. The read-only check inspects the running Watchtower, private JSON Compose file and 24-target manifest, Compose provenance, root-only credentials, the 05:00 verification timer, all 28 selected containers, current Gluetun namespace dependencies, and candidate Compose syntax **without writing any files**. Any unexpected change stops the enrollment.

The apply mode saves the three original files (private Watchtower Compose, target manifest, installed verifier) to a timestamped root-only backup under `/root/awtserver-watchtower-enrollment/`; replaces **only** those three files; recreates **only** the Watchtower container with `docker compose ... up -d --no-deps --no-build --pull never watchtower`; and independently verifies exactly 28 enrolled targets and unchanged application container IDs/states. On failure it attempts to restore the three saved files and the old 24-target Watchtower configuration. The existing 24-target verifier would still fail on excluded Gluetun clients after such a rollback. Retain backups for manual recovery.

Run and review the live `--check` before applying anything. The helper does not perform live unattended image updates, does not repair a failure in Gluetun's own update process, and does not alter Transmission or any application containers.
 Before enrollment, verify the actual Compose provenance (including the new `/docker/privacy/compose.trawl.yml` overlay), current target list, container health, and dependencies. Back up the private files and installed verifier; update the **exact 28-target** updater command and private manifest together; recreate **only** Watchtower; install the matching verifier; run `python3 /docker/watchtower-fork/watchtower_verify.py --verify` and verify post-update monitoring. Do not run an unscoped `docker compose up -d` or restart Gluetun to accomplish this change.

The normal/default `privacy` configuration retains a **single existing Transmission**. An abandoned two-instance design is kept [only as optional historical reference](../../docs/optional/transmission-brother/OPERATIONS.md); it is not a production dependency, an automatic service, or a requirement for healthy Watchtower verification.


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
