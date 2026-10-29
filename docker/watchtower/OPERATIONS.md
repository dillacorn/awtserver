# Watchtower operations and historical verification

## Additional VPN clients and second Transmission (2026-10-29)

**Migration progress, October 29:** TRAWL is now Compose-managed in `privacy` and its local `/health` passed with unchanged Gluetun/Transmission IDs. The stopped original backup `trawl-standalone-backup-20261029t172518z` remains for rollback. **Do not expand Watchtower yet:** Prowlarr proxy/indexer integration is not yet reverified, the backup must be deliberately retired after successful verification, and the second Transmission/Tailscale services do not exist. The installed manifest and 24-target verifier remain unchanged.


**Existing live issue:** Read-only diagnostics on `openmediavault` show the 24-target Watchtower list and private `targets.json` are unchanged. The verifier already fails with `Unapproved additional Gluetun namespace user: trawl`. Current `amutorrent`, `prowlarr`, and standalone `trawl` share Gluetun's namespace but are not selected for Watchtower updates. This requires a safe group migration, not suppression of the namespace guard.

This branch's `watchtower_verify.py` supports only two exact policies: the original **24** targets or the expanded **30**. The six additions are `amutorrent`, `prowlarr`, `trawl`, `tailscale-amutorrent`, `transmission-brother`, and `tailscale-transmission-brother`. Neither a partial extension nor an unrecognized namespace client can pass. The selected TRAWL **must be Compose-managed** because the verifier requires Compose source metadata for every Watchtower target. All selected Gluetun clients must be attached to the **current** Gluetun namespace and cannot have firewall administration capabilities.

**Not yet deployed:** the live private `/docker/watchtower-fork/compose.yml` and root mode-0600 `targets.json` still require a separate guarded enrollment process. Replacing only the verifier will not select additional containers. The `05:00` service must run the matching updated verifier, and the new updater command must exactly equal the private manifest list with schedule `0 45 2 * * *`. Do not change the 24-target list until all six new containers exist and TRAWL has been migrated to its reviewed Compose overlay, with a tested rollback. Keep the original Watchtower configuration and manifest in dated root-only backups.

Before enrolling: verify live Compose file sets, firewall ports, Tailscale identities and passwords, Gluetun container namespace users, and the separate Transmission settings and volumes. Migrate TRAWL in isolation without recreating the VPN parent, then carry out any Gluetun firewall change in a planned maintenance window. Never run broad `docker compose up -d` or `down`. On completion verify `python3 /docker/watchtower-fork/watchtower_verify.py --verify` **without notifications** and test authenticated VPN egress and Prowlarr/TRAWL behavior. Watchtower's restart ordering does not guarantee VPN health before dependent services start; 05:00 detection is not automatic recovery.

See the [second Transmission operations guide](../privacy/TRANSMISSION-BROTHER-OPERATIONS.md) for the verified source paths and isolated deployment design.

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
