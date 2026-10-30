#!/usr/bin/env python3
"""One-time guarded aMuTorrent AudioBooks/Music mount extension.

--check: read-only; --apply: updates ONLY the existing media overlay and
recreates ONLY the existing amutorrent service (with rollback on failure).
No media content is copied, touched, renamed, or removed.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path("/docker/privacy")
BASE = ("compose.yml", "compose.override.yml",
        "compose.amutorrent.yml", "compose.trawl.yml")
OVERLAY = ROOT / "compose.amutorrent-media.yml"
BACKUPS = Path("/root/awtserver-amutorrent-media-backups")
OLD = "# Only two extra paths for the existing aMuTorrent container.\n# Needed to clear CategoryModal read+write access warnings for /Movies and /Shows.\n# Add after all currently active privacy Compose overlays; recreate only amutorrent.\n# This intentionally does not change /downloads or any other service.\nservices:\n  amutorrent:\n    volumes:\n      - /srv/mergerfs/data/root/Movies:/Movies:rw\n      - /srv/mergerfs/data/root/Shows:/Shows:rw\n"
NEW = "# Add category paths for the existing aMuTorrent service only.\n# Keep the original Movies/Shows mounts, and add AudioBooks/Music.\n# Append this file after compose.trawl.yml in the complete privacy Compose set.\n# No changes to Transmission, Gluetun, Watchtower or default downloads.\nservices:\n  amutorrent:\n    volumes:\n      - /srv/mergerfs/data/root/Movies:/Movies:rw\n      - /srv/mergerfs/data/root/Shows:/Shows:rw\n      - /srv/mergerfs/data/root/AudioBooks:/AudioBooks:rw\n      - /srv/mergerfs/data/root/Music:/Music:rw\n"
OLD_MOUNTS = {
    "/Movies": "/srv/mergerfs/data/root/Movies",
    "/Shows": "/srv/mergerfs/data/root/Shows",
}
EXTRA_MOUNTS = {
    "/AudioBooks": "/srv/mergerfs/data/root/AudioBooks",
    "/Music": "/srv/mergerfs/data/root/Music",
}
ALL_MOUNTS = {**OLD_MOUNTS, **EXTRA_MOUNTS}


class Stop(RuntimeError):
    pass


def need(ok, detail):
    if not ok:
        raise Stop(detail)


def run(args, timeout=120, check=True):
    try:
        result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True,
                                timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise Stop(f"Command unavailable/timed out: {args[0]}") from err
    if check and result.returncode:
        # Compose output may expose environment secrets; do not echo it.
        raise Stop(f"Command {args[0]} exited {result.returncode} (output suppressed)")
    return result


def inspect(name):
    result = run(["docker", "inspect", name], timeout=25, check=False)
    return json.loads(result.stdout)[0] if result.returncode == 0 else None


def compose_cmd(files, *tail):
    args = ["docker", "compose", "-p", "privacy",
            "--project-directory", str(ROOT)]
    for file in files:
        args.extend(("-f", str(file)))
    return args + list(tail)


def effective(files):
    output = run(compose_cmd(files, "config", "--format", "json"),
                 timeout=60).stdout
    return json.loads(output)["services"]


def inventory():
    ids = run(["docker", "ps", "-aq"], timeout=25).stdout.split()
    need(ids, "No Docker containers found")
    data = json.loads(run(["docker", "inspect", *ids], timeout=75).stdout)
    return {c["Name"].lstrip("/"): c for c in data}


def inventory_unchanged(before):
    current = inventory()
    for name, identity in before.items():
        c = current.get(name)
        need(c and (c["Id"], c["State"]["Status"]) == identity,
             f"Unrelated container identity/state changed: {name}")


def validate_volumes(volumes, mapping):
    by_target = {entry["target"]: entry for entry in volumes}
    need(len(by_target) == len(volumes), "Duplicate volume targets")
    for dest, source in mapping.items():
        v = by_target.get(dest)
        need(v and v.get("source") == source and v.get("type") == "bind" and
             v.get("read_only") is not True,
             f"Unexpected Compose mount: {dest}")


def preflight(candidate):
    need(os.geteuid() == 0 and socket.gethostname() == "openmediavault",
         "Only root on host openmediavault may execute this")
    need(ROOT.is_dir() and not ROOT.is_symlink(),
         "Privacy project path missing or unsafe")
    need(candidate.is_file() and not candidate.is_symlink() and
         candidate.read_text() == NEW,
         "Candidate overlay differs from reviewed four-mount content")
    need(OVERLAY.is_file() and not OVERLAY.is_symlink() and
         OVERLAY.read_text() == OLD,
         "Installed media overlay differs from verified two-mount baseline")
    metadata = OVERLAY.stat()
    need(metadata.st_uid == 0 and
         stat.S_IMODE(metadata.st_mode) & 0o022 == 0,
         "Existing media overlay ownership/permissions unsafe")
    base = [ROOT / f for f in BASE]
    need(all(file.is_file() and not file.is_symlink() for file in base),
         "One or more of the four live base Compose files are unavailable")
    before = effective([*base, OVERLAY])
    after = effective([*base, candidate])
    need(set(before) == set(after), "Candidate changes service list")
    for name in before:
        if name != "amutorrent":
            need(before[name] == after[name],
                 f"Candidate changes unrelated Compose service: {name}")
    original = before.get("amutorrent")
    updated = after.get("amutorrent")
    need(original and updated and
         original.get("network_mode") == updated.get("network_mode") ==
         "service:gluetun",
         "aMuTorrent Gluetun network mode changed")
    old_without = {k: v for k, v in original.items() if k != "volumes"}
    new_without = {k: v for k, v in updated.items() if k != "volumes"}
    need(old_without == new_without,
         "Candidate changes aMuTorrent configuration beyond volumes")
    old_volumes = original.get("volumes") or []
    new_volumes = updated.get("volumes") or []
    need(len(new_volumes) == len(old_volumes) + 2 and
         new_volumes[:len(old_volumes)] == old_volumes,
         "Candidate changed existing aMuTorrent volumes")
    validate_volumes(old_volumes, OLD_MOUNTS)
    validate_volumes(new_volumes, ALL_MOUNTS)

    fleet = inventory()
    for name in ("amutorrent", "transmission", "gluetun", "watchtower"):
        need(name in fleet and fleet[name]["State"]["Status"] == "running",
             f"Required running container absent: {name}")
    am = fleet["amutorrent"]
    vpn = fleet["gluetun"]
    labels = am["Config"].get("Labels") or {}
    need(labels.get("com.docker.compose.project") == "privacy" and
         labels.get("com.docker.compose.service") == "amutorrent",
         "Current aMuTorrent Compose identity differs")
    need(am["Config"].get("User") == "1001:1000",
         "Current aMuTorrent UID:GID differs from verified deployment")
    need(am["HostConfig"]["NetworkMode"] == "container:" + vpn["Id"] and
         (vpn["State"].get("Health") or {}).get("Status") == "healthy",
         "aMuTorrent is not using the healthy current Gluetun namespace")
    current_mounts = {m["Destination"]: m for m in am["Mounts"]}
    for dest, source in OLD_MOUNTS.items():
        m = current_mounts.get(dest)
        need(m and m.get("Source") == source and m.get("RW"),
             f"Existing live mount absent/changed: {dest}")
    for dest in EXTRA_MOUNTS:
        need(dest not in current_mounts, f"New media path already mounted: {dest}")
    for dest, source in ALL_MOUNTS.items():
        p = Path(source)
        need(p.is_dir() and not p.is_symlink(),
             f"Mergerfs directory missing or unsafe: {dest}")
    other = {name: (c["Id"], c["State"]["Status"])
             for name, c in fleet.items() if name != "amutorrent"}
    print("PASS: Current privacy stack and original Movies/Shows mounts match")
    print("PASS: Proposed Compose preserves all services and adds only AudioBooks/Music")
    print("PASS: Transmission and Gluetun remain running; Watchtower unchanged")
    return base, other, metadata, am["Id"]


def atomic_write(path, content, uid, gid, mode):
    fd, temp = tempfile.mkstemp(prefix=".amutorrent-media-stage-", dir=ROOT)
    try:
        os.fchmod(fd, mode)
        os.fchown(fd, uid, gid)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        fd = -1
        os.replace(temp, path)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.lexists(temp):
            os.unlink(temp)


def save_backup(content):
    need(not BACKUPS.is_symlink(), "Backup parent may not be a symlink")
    BACKUPS.mkdir(mode=0o700, exist_ok=True)
    need(BACKUPS.stat().st_uid == 0 and
         stat.S_IMODE(BACKUPS.stat().st_mode) & 0o077 == 0,
         "Backup directory permissions unsafe")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = BACKUPS / (timestamp + "-" + str(os.getpid()))
    destination.mkdir(mode=0o700)
    backup = destination / OVERLAY.name
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    return backup


def wait_health():
    # The live aMuTorrent container has Health=none. Require the actual
    # application /health HTTP endpoint to respond, not Docker's optional
    # HEALTHCHECK metadata. Run the probe inside the same container.
    health_script = """const http = require('node:http');
const req = http.get('http://127.0.0.1:4000/health', (r) => {
  r.resume();
  r.on('end', () => { process.exitCode = (r.statusCode === 200 ? 0 : 1); });
});
req.setTimeout(4000, () => req.destroy(new Error('health timeout')));
req.on('error', () => { process.exitCode = 1; });
"""
    for attempt in range(30):
        am = inspect("amutorrent")
        if am and am["State"]["Status"] == "running":
            result = run(["docker", "exec", "amutorrent", "node", "-e",
                          health_script], timeout=12, check=False)
            if result.returncode == 0:
                return am
        time.sleep(2)
    raise Stop("aMuTorrent HTTP /health did not return 200")


def validate_runtime(expected):
    am = wait_health()
    mounts = {m["Destination"]: m for m in am["Mounts"]}
    for dest, source in expected.items():
        m = mounts.get(dest)
        need(m and m.get("Source") == source and m.get("RW"),
             f"Runtime mount not writable or wrong: {dest}")
    # Same access check aMuTorrent uses internally; no file is created.
    script = """const fs=require('node:fs');
for (const dir of ['/Movies','/Shows','/AudioBooks','/Music']) {
  fs.accessSync(dir, fs.constants.R_OK | fs.constants.W_OK);
  console.log('PASS: '+dir+' R_OK/W_OK');
}"""
    result = run(["docker", "exec", "amutorrent", "node", "-e", script],
                 timeout=20)
    for dest in expected:
        need(f"PASS: {dest} R_OK/W_OK" in result.stdout,
             f"aMuTorrent user lacks read/write access to {dest}")
    return am


def apply(base, others, metadata, am_id):
    original = OVERLAY.read_bytes()
    need(original == OLD.encode(), "Overlay changed after preflight")
    backup = save_backup(original)
    print("Backup:", backup, flush=True)
    atomic_write(OVERLAY, NEW.encode(), metadata.st_uid, metadata.st_gid,
                 stat.S_IMODE(metadata.st_mode))
    files = [*base, OVERLAY]
    try:
        run(compose_cmd(files, "up", "-d", "--no-deps",
                        "--no-build", "--pull", "never", "amutorrent"),
            timeout=150)
        am = validate_runtime(ALL_MOUNTS)
        need(am["Id"] != am_id, "Expected aMuTorrent-only recreation did not occur")
        inventory_unchanged(others)
    except Exception as exc:
        print("STOP: Apply verification failed; attempting aMuTorrent-only rollback",
              file=sys.stderr)
        try:
            need(OVERLAY.read_bytes() == NEW.encode(),
                 "Live overlay changed; preserving for manual inspection")
            atomic_write(OVERLAY, original, metadata.st_uid,
                         metadata.st_gid, stat.S_IMODE(metadata.st_mode))
            run(compose_cmd(files, "up", "-d", "--no-deps",
                            "--no-build", "--pull", "never", "amutorrent"),
                timeout=150)
            restored = wait_health()
            live = {m["Destination"]: m for m in restored["Mounts"]}
            need(all(live.get(dest, {}).get("Source") == source and
                     live[dest].get("RW") for dest, source in OLD_MOUNTS.items()),
                 "Original media mounts were not restored")
            need(all(dest not in live for dest in EXTRA_MOUNTS),
                 "Additional mounts remain after rollback")
            inventory_unchanged(others)
            print("PASS: Original two-mount aMuTorrent configuration restored",
                  file=sys.stderr)
        except Exception as rollback_exc:
            print("WARNING: Automatic rollback unverified: " + str(rollback_exc),
                  file=sys.stderr)
            print("Original overlay backup retained:", backup, file=sys.stderr)
        raise Stop("Mount extension not completed") from exc

    print("PASS: aMuTorrent has writable Movies, Shows, AudioBooks and Music mounts")
    print("PASS: aMuTorrent health restored and other container IDs/states unchanged")
    print("PASS: Transmission, Gluetun and Watchtower were not modified")
    print("Active Compose overlay:", OVERLAY)
    print("Keep this fifth overlay in all future privacy Compose operations")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    flags = parser.add_mutually_exclusive_group(required=True)
    flags.add_argument("--check", action="store_true")
    flags.add_argument("--apply", action="store_true")
    parser.add_argument("--candidate", required=True, type=Path)
    args = parser.parse_args()
    try:
        base, others, metadata, am_id = preflight(args.candidate)
        if args.apply:
            apply(base, others, metadata, am_id)
        else:
            print("READ-ONLY PASS: no changes made")
        return 0
    except (Stop, OSError, KeyError, TypeError, ValueError) as exc:
        print("STOP:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
