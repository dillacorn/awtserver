#!/usr/bin/env python3
"""Guarded qBittorrent -> Transmission rollback; preserves all torrent data.

--check is read-only. --apply stops ONLY qBittorrent and its new Tailscale
sidecar, brings back the SAME existing Transmission container, and restores
the original exact-28 Watchtower files from the 29-target transition backup.

Requires an explicit --backup-dir from the successful transition output.
Only the stopped qBittorrent container is removed with explicit authorization;
its /config bind mount and all torrent payloads remain untouched. Existing
Pi-hole records/cert mounts and independent Tailscale identities remain.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import socket
import stat
import subprocess
import sys
import time

import enroll_qbittorrent_29 as enroll
import watchtower_verify_qbittorrent as verify

ROOT = Path("/docker/watchtower-fork")
BACKUP_ROOT = Path("/root/awtserver-qbittorrent-watchtower-transition")
EXPECTED_RESTARTS = {"qbittorrent": "unless-stopped",
                     "tailscale-qbittorrent": "unless-stopped",
                     "transmission": "no"}


class Stop(RuntimeError):
    pass


def need(value, message):
    if not value:
        raise Stop(message)


def run(*args, timeout=90, check=True):
    try:
        proc = subprocess.run(args, cwd=ROOT, text=True, capture_output=True,
                              timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as err:
        raise Stop(f"Command unavailable or timed out: {args[0]}") from err
    if check and proc.returncode:
        raise Stop(f"Command failed: {args[0]} (status {proc.returncode}; private output suppressed)")
    return proc


def inventory():
    return verify.docker_inventory()


def current_state(names):
    return {n: (c["Id"], c["State"]["Status"])
            for n, c in inventory().items() if n in names}


def assert_unrelated(before):
    after = current_state(before)
    need(after == before, "Unrelated containers changed during rollback")


def private(path, expected_uid=0):
    need(path.is_file() and not path.is_symlink(),
         f"Expected root-private file absent: {path.name}")
    metadata = path.stat()
    need(metadata.st_uid == expected_uid and stat.S_IMODE(metadata.st_mode) & 0o077 == 0,
         f"File not root-private: {path.name}")
    return path.read_bytes()


def parse(raw):
    return json.loads(raw)


def check_backup(directory, expected_uid=0):
    need(directory.parent == BACKUP_ROOT and
         re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", directory.name) and
         directory.is_dir() and not directory.is_symlink(),
         "Backup must be the original timestamped Watchtower transition backup")
    need(directory.stat().st_uid == expected_uid and
         stat.S_IMODE(directory.stat().st_mode) & 0o077 == 0,
         "Watchtower backup directory not root-private")
    originals = {path: private(directory / path.name, expected_uid=expected_uid)
                 for path in (enroll.COMPOSE, enroll.MANIFEST, enroll.VERIFIER)}
    doc = parse(originals[enroll.COMPOSE])
    manifest = parse(originals[enroll.MANIFEST])
    names = manifest.get("container_names")
    need(isinstance(names, list) and len(names) == 28 and
         set(names) == verify.EXPANDED,
         "Backup does not contain exactly the pre-migration 28 targets")
    need(manifest.get("schedule") == verify.SCHEDULE and
         doc["services"]["watchtower"].get("command") ==
         enroll.expected_cmd(names),
         "Backup Watchtower command or schedule mismatches 28-target policy")
    need(doc["services"]["watchtower"].get("image") ==
         "nickfedor/watchtower:1.23.1", "Unexpected original Watchtower image")
    source = originals[enroll.VERIFIER]
    need(b"transmission" in source and
         b"Unapproved additional Gluetun namespace user" in source and
         b"qbittorrent" not in source.lower(),
         "Original verifier is not the expected pre-migration policy")
    return originals, names


def check_current():
    originals = {path: private(path) for path in
                 (enroll.COMPOSE, enroll.MANIFEST, enroll.VERIFIER)}
    names = parse(originals[enroll.MANIFEST]).get("container_names")
    need(isinstance(names, list) and len(names) == 29 and
         set(names) == verify.QBIT_TRANSITION,
         "Current Watchtower is not at the approved qBittorrent 29-target policy")
    doc = parse(originals[enroll.COMPOSE])
    need(doc["services"]["watchtower"].get("command") ==
         enroll.expected_cmd(names), "Watchtower Compose and manifest disagree")
    need(hashlib.sha256(originals[enroll.VERIFIER]).digest() ==
         hashlib.sha256(Path(verify.__file__).read_bytes()).digest(),
         "Installed Watchtower verifier differs from reviewed migration source")
    return originals, names


def preflight(backup_dir):
    need(os.geteuid() == 0 and socket.gethostname() == "openmediavault",
         "Root on openmediavault required")
    original, old_names = check_backup(backup_dir)
    current_files, q_names = check_current()
    fleet = inventory()
    for name in ("gluetun", "transmission", "qbittorrent",
                 "tailscale-transmission", "tailscale-qbittorrent", "watchtower"):
        need(name in fleet, f"Required container absent: {name}")
    gluetun = fleet["gluetun"]
    need(gluetun["State"]["Status"] == "running" and
         (gluetun["State"].get("Health") or {}).get("Status") == "healthy",
         "Gluetun not running/healthy")
    need(fleet["transmission"]["State"]["Status"] == "exited" and
         all(fleet[n]["State"]["Status"] == "running" for n in
             ("qbittorrent", "tailscale-qbittorrent", "watchtower")),
         "Expected qBittorrent running and original Transmission stopped")
    need(fleet["transmission"]["HostConfig"]["NetworkMode"] ==
         "container:" + gluetun["Id"] and
         fleet["qbittorrent"]["HostConfig"]["NetworkMode"] ==
         "container:" + gluetun["Id"],
         "Clients must belong to the same current Gluetun parent")
    qbit = fleet["qbittorrent"]
    labels = qbit["Config"].get("Labels") or {}
    need(labels.get("com.docker.compose.project") == "privacy" and
         labels.get("com.docker.compose.service") == "qbittorrent",
         "qBittorrent is not the expected privacy Compose container")
    mounts = {m["Destination"]: m for m in qbit["Mounts"]}
    need(mounts.get("/config", {}).get("Source") ==
         "/docker/privacy/qbittorrent/config" and
         mounts["/config"].get("Type") == "bind",
         "qBittorrent /config must remain a persistent bind mount")
    need(not qbit["HostConfig"].get("PortBindings"),
         "qBittorrent has unexpected host port bindings")
    for name, expected in EXPECTED_RESTARTS.items():
        actual = fleet[name]["HostConfig"]["RestartPolicy"]["Name"]
        need(actual == expected,
             f"{name}: unexpected restart policy {actual}; review manually")
    need(fleet["watchtower"]["Config"]["Cmd"] ==
         enroll.expected_cmd(q_names), "Running Watchtower differs from installed policy")
    need(run("systemctl", "is-active", "--quiet",
             "watchtower-fork-verify.timer", check=False).returncode == 0,
         "Watchtower verifier timer not active")

    # Verify that the stored Transmission state remains in place.
    data = Path("/docker/privacy/transmission/data")
    torrents = {p.name[:-8] for p in (data / "torrents").glob("*.torrent")}
    resume = {p.name[:-7] for p in (data / "resume").glob("*.resume")}
    need(torrents and torrents == resume,
         "Transmission torrent/resume records are not matched")
    ignored = {"transmission", "qbittorrent", "tailscale-qbittorrent", "watchtower"}
    protected = {name: (item["Id"], item["State"]["Status"])
                 for name, item in fleet.items() if name not in ignored}
    print(f"PASS: {len(torrents)} matched Transmission metadata records")
    print("PASS: Verified old 28-target backup and current 29-target manifest")
    print("PASS: Transmission stopped; qBittorrent and its Tailscale sidecar running")
    print("PASS: Original Tailscale Transmission machine retained")
    return original, old_names, current_files, protected


def rpc():
    # No credentials are needed to check Transmission RPC's 409 session
    # challenge. 401 can indicate the expected HTTP basic-auth gate.
    script = """const http = require('node:http');
const req = http.get('http://127.0.0.1:9091/transmission/rpc',
  (res) => {
    const ok = (res.statusCode === 409 &&
        Boolean(res.headers['x-transmission-session-id'])) ||
      (res.statusCode === 401);
    res.resume();
    if (!ok) process.exitCode = 1;
  });
req.setTimeout(5000, () => { req.destroy(); process.exitCode = 1; });
req.on('error', () => { process.exitCode = 1; });
"""
    for attempt in range(15):
        result = run("docker", "exec", "amutorrent", "node", "-e",
                     script, timeout=12, check=False)
        if result.returncode == 0:
            return True
        time.sleep(2)
    return False


def assert_running_state(name, running):
    c = inventory().get(name)
    need(c and c["State"]["Running"] == running,
         f"{name}: unexpected running state")


def apply(original, old_names, current_files, protected, allow_remove):
    # Check the current manifest again before the first state change.
    need(check_current()[0] == current_files,
         "Live Watchtower files changed after preflight")

    print("Stopping new qBittorrent (data preserved)", flush=True)
    run("docker", "update", "--restart", "no", "qbittorrent")
    run("docker", "stop", "--timeout", "120", "qbittorrent", timeout=155)
    assert_running_state("qbittorrent", False)
    print("Stopping only the NEW qBittorrent Tailscale sidecar", flush=True)
    run("docker", "update", "--restart", "no", "tailscale-qbittorrent")
    run("docker", "stop", "--timeout", "45", "tailscale-qbittorrent", timeout=75)
    assert_running_state("tailscale-qbittorrent", False)

    # The legacy Watchtower verifier rejects *all* unselected Gluetun
    # children, even stopped ones. Remove only the stopped, identity-checked
    # ephemeral qBittorrent container, never -v or any persistent data.
    # Recreate it later from Compose if switching back to qBittorrent.
    need(allow_remove, "Stopped qBittorrent container must be removed for the original "
         "28-target verifier. Re-run with --allow-remove-container only if approved.")
    saved_qbit = inventory()["qbittorrent"]
    need(saved_qbit["State"]["Status"] == "exited" and
         saved_qbit["Config"].get("Labels", {}).get(
             "com.docker.compose.service") == "qbittorrent" and
         {m["Destination"]: m for m in saved_qbit["Mounts"]}.get(
             "/config", {}).get("Source") ==
         "/docker/privacy/qbittorrent/config",
         "Cannot safely remove the staged qBittorrent container")
    run("docker", "rm", "qbittorrent")
    need("qbittorrent" not in inventory(),
         "Stopped qBittorrent container still present")

    # The existing Transmission container and all its persistent mounts are
    # unchanged: restore its prior restart policy and start the original ID.
    original_id = inventory()["transmission"]["Id"]
    print("Starting the existing Transmission container", flush=True)
    run("docker", "update", "--restart", "unless-stopped", "transmission")
    run("docker", "start", "transmission")
    need(inventory()["transmission"]["Id"] == original_id,
         "Transmission container identity unexpectedly changed")
    need(rpc(), "Transmission RPC did not recover; preserve checkpoint for inspection")

    # Copy only the three saved, verified private Watchtower policy files.
    # Any failure leaves all original torrent/qBittorrent data intact.
    print("Restoring exact 28-target Watchtower policy", flush=True)
    for path, saved in original.items():
        enroll.write_atomic(path, saved)
        need(private(path) == saved, f"Watchtower restore readback mismatch: {path.name}")
    run(*enroll.compose_cmd("up", "-d", "--no-deps", "--no-build",
                            "--pull", "never", "watchtower"), timeout=120)
    verified = run("python3", str(enroll.VERIFIER), "--verify", timeout=90)
    need("28 healthy targets" in verified.stdout,
         "Restored Watchtower did not verify 28 healthy targets")
    assert_unrelated(protected)
    print("PASS: Original Transmission RPC responding")
    print("PASS: New qBittorrent and its Tailscale sidecar stopped, data retained")
    print("PASS: Watchtower original 28-target exact policy restored and verified")
    print("NOTE: Pi-hole/new Tailscale DNS entries not deleted; old Transmission endpoint remains")
    print("NOTE: Reconfigure aMuTorrent's download client to Transmission in its UI")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", type=Path, required=True)
    flags = parser.add_mutually_exclusive_group()
    flags.add_argument("--check", action="store_true")
    flags.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-remove-container", action="store_true",
                        help="Explicitly permit removing ONLY the stopped qBittorrent container, never volumes")
    args = parser.parse_args()
    try:
        original, names, current, protected = preflight(args.backup_dir)
        if args.apply:
            need(args.allow_remove_container,
                 "Rollback requires explicit --allow-remove-container; persistent data is preserved")
            apply(original, names, current, protected, args.allow_remove_container)
        else:
            print("READ-ONLY PASS: no changes made")
        return 0
    except (Stop, verify.Stop, enroll.Stop, OSError,
            KeyError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        print("STOP:", exc, file=sys.stderr)
        print("If any rollback step already ran, inspect container states and Watchtower files before retrying.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
