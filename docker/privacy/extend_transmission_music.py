#!/usr/bin/env python3
"""One-time guarded /Music bind mount for the existing Transmission service.

--check is read-only. --apply creates only the final Compose overlay and
recreates only transmission; failure attempts a Transmission-only rollback.
No host media content, Transmission data, Gluetun, or aMuTorrent is modified.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path("/docker/privacy")
BASE = (
    "compose.yml", "compose.override.yml", "compose.amutorrent.yml",
    "compose.trawl.yml", "compose.amutorrent-media.yml",
)
OVERLAY = ROOT / "compose.transmission-music.yml"
EXPECTED = """# Add the existing mergerfs Music directory to the single Transmission client.
# Keep all original privacy Compose files including the aMuTorrent media overlay.
# Load last; change/recreate ONLY transmission, not gluetun or amutorrent.
services:
  transmission:
    volumes:
      - /srv/mergerfs/data/root/Music:/Music:rw
"""
NEW_DEST = "/Music"
NEW_SOURCE = "/srv/mergerfs/data/root/Music"
EXISTING = {
    "/AudioBooks": "/srv/mergerfs/data/root/AudioBooks",
    "/Books": "/srv/mergerfs/data/root/Books",
    "/Movies": "/srv/mergerfs/data/root/Movies",
    "/Shows": "/srv/mergerfs/data/root/Shows",
    "/downloads": "/srv/mergerfs/data/root/downloads",
    "/config": "/docker/privacy/transmission/data",
    "/watch": "/docker/privacy/transmission/watch",
}
AM_MEDIA = {
    "/Movies": "/srv/mergerfs/data/root/Movies",
    "/Shows": "/srv/mergerfs/data/root/Shows",
    "/AudioBooks": "/srv/mergerfs/data/root/AudioBooks",
    "/Music": NEW_SOURCE,
}


class Stop(RuntimeError):
    pass


def require(ok, message):
    if not ok:
        raise Stop(message)


def run(argv, *, timeout=90, check=True):
    try:
        result = subprocess.run(
            argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stop("Command unavailable or timed out: " + argv[0]) from exc
    if check and result.returncode:
        # Docker Compose may print interpolated secrets; suppress raw output.
        raise Stop(f"Command {argv[0]} failed ({result.returncode}); details suppressed")
    return result


def compose(files, *args, check=True):
    argv = ["docker", "compose", "-p", "privacy",
            "--project-directory", str(ROOT)]
    for file in files:
        argv += ["-f", str(file)]
    return run(argv + list(args), timeout=170, check=check)


def effective(files):
    return json.loads(compose(files, "config", "--format", "json").stdout)["services"]


def inspect(name):
    result = run(["docker", "inspect", name], timeout=25, check=False)
    return json.loads(result.stdout)[0] if result.returncode == 0 else None


def inventory():
    ids = run(["docker", "ps", "-aq"], timeout=30).stdout.split()
    require(bool(ids), "Docker inventory unexpectedly empty")
    data = json.loads(run(["docker", "inspect", *ids], timeout=90).stdout)
    return {c["Name"].lstrip("/"): c for c in data}


def check_other_containers(saved):
    current = inventory()
    for name, expected in saved.items():
        c = current.get(name)
        require(c and (c["Id"], c["State"]["Status"]) == expected,
                "Unrelated Docker container changed: " + name)


def mount_map(info):
    return {m["Destination"]: m for m in info["Mounts"]}


def require_mounts(info, expected):
    actual = mount_map(info)
    for dest, source in expected.items():
        m = actual.get(dest)
        require(m and m.get("Type") == "bind" and
                m.get("Source") == source and m.get("RW") is True,
                f"Incorrect existing runtime bind mount: {dest}")


def check_compose_volume(volumes, dest, source):
    found = [v for v in volumes if v.get("target") == dest]
    require(len(found) == 1 and found[0].get("type") == "bind" and
            found[0].get("source") == source and
            found[0].get("read_only") is not True,
            f"Incorrect effective Compose volume for {dest}")


def uid_gid(info):
    env = dict(v.split("=", 1) for v in info["Config"].get("Env") or []
               if "=" in v)
    uid, gid = env.get("PUID"), env.get("PGID")
    require(uid and gid and uid.isdecimal() and gid.isdecimal(),
            "Transmission PUID/PGID not found")
    return uid, gid


def preflight(candidate):
    require(os.geteuid() == 0 and socket.gethostname() == "openmediavault",
            "Root on openmediavault required")
    require(ROOT.is_dir() and not ROOT.is_symlink(),
            "Unexpected privacy Compose project directory")
    require(candidate.is_file() and not candidate.is_symlink() and
            candidate.read_text() == EXPECTED,
            "Candidate differs from the single reviewed Music mount")
    require(not OVERLAY.exists() and not OVERLAY.is_symlink(),
            "Music overlay already present; refuse overwrite/reapplication")
    base = [ROOT / file for file in BASE]
    require(all(p.is_file() and not p.is_symlink() for p in base),
            "Full five-file privacy Compose set not available")
    before = effective(base)
    after = effective([*base, candidate])
    require(set(before) == set(after), "Candidate adds/removes Compose services")
    for name in before:
        if name != "transmission":
            require(before[name] == after[name],
                    "Candidate unexpectedly changes " + name)
    current = before["transmission"]
    updated = after["transmission"]
    require(current.get("network_mode") == updated.get("network_mode") ==
            "service:gluetun", "Transmission VPN namespace changed")
    require({k: v for k, v in current.items() if k != "volumes"} ==
            {k: v for k, v in updated.items() if k != "volumes"},
            "Candidate changes Transmission beyond bind mounts")
    previous_volumes = current.get("volumes") or []
    next_volumes = updated.get("volumes") or []
    require(len(next_volumes) == len(previous_volumes) + 1 and
            next_volumes[:len(previous_volumes)] == previous_volumes,
            "Candidate changes existing Transmission mount list")
    for dest, source in EXISTING.items():
        check_compose_volume(previous_volumes, dest, source)
    check_compose_volume(next_volumes, NEW_DEST, NEW_SOURCE)

    pool = Path(NEW_SOURCE)
    require(pool.is_dir() and not pool.is_symlink(),
            "Mergerfs Music source unavailable or symlinked")
    all_containers = inventory()
    for name in ("gluetun", "transmission", "amutorrent", "watchtower"):
        require(name in all_containers and
                all_containers[name]["State"]["Status"] == "running",
                "Required privacy or Watchtower container not running: " + name)
    transmission = all_containers["transmission"]
    vpn = all_containers["gluetun"]
    amutorrent = all_containers["amutorrent"]
    for name, info in (("transmission", transmission), ("amutorrent", amutorrent)):
        labels = info["Config"].get("Labels") or {}
        require(labels.get("com.docker.compose.project") == "privacy" and
                labels.get("com.docker.compose.service") == name,
                "Unexpected Docker Compose project/service: " + name)
    require((vpn["State"].get("Health") or {}).get("Status") == "healthy",
            "Current Gluetun is not healthy")
    require_mounts(transmission, EXISTING)
    require(NEW_DEST not in mount_map(transmission),
            "Transmission already has a /Music mount")
    require_mounts(amutorrent, AM_MEDIA)
    uid, gid = uid_gid(transmission)
    others = {name: (c["Id"], c["State"]["Status"])
              for name, c in all_containers.items() if name != "transmission"}
    print("PASS: Verified live privacy/Transmission identity and five Compose files")
    print("PASS: Existing Transmission and aMuTorrent media mounts preserved")
    print("PASS: Only Transmission gains /Music; Gluetun and all other services unchanged")
    return base, others, transmission["Id"], uid, gid


def wait_transmission(uid, gid, expected_mounts):
    access_script = "test -d /Music && test -r /Music && test -w /Music && test -x /Music"
    for attempt in range(40):
        tr = inspect("transmission")
        if tr and tr["State"]["Status"] == "running":
            try:
                require_mounts(tr, expected_mounts)
                proc = run(["docker", "top", "transmission"], timeout=15, check=False)
                access = run(["docker", "exec", "-u", uid + ":" + gid,
                              "transmission", "sh", "-c", access_script],
                             timeout=12, check=False)
                if (proc.returncode == 0 and
                        "transmission-daemon" in proc.stdout and
                        access.returncode == 0):
                    return tr
            except Stop:
                pass
        time.sleep(2)
    raise Stop("Transmission process or /Music read/write permission unavailable")


def apply(base, others, old_id, uid, gid):
    # Exclusive create avoids replacing anything from another operation.
    fd = os.open(OVERLAY, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w") as file:
        file.write(EXPECTED)
        file.flush()
        os.fsync(file.fileno())

    try:
        compose([*base, OVERLAY], "up", "-d", "--no-deps",
                "--no-build", "--pull", "never", "transmission")
        tr = wait_transmission(uid, gid, {**EXISTING, NEW_DEST: NEW_SOURCE})
        require(tr["Id"] != old_id, "Transmission was not recreated")
        check_other_containers(others)
    except Exception as exc:
        print("STOP: Music mount verification failed; restoring Transmission-only Compose",
              file=sys.stderr)
        try:
            require(OVERLAY.is_file() and not OVERLAY.is_symlink() and
                    OVERLAY.read_text() == EXPECTED,
                    "Music overlay changed during apply; manual recovery required")
            OVERLAY.unlink()
            compose(base, "up", "-d", "--no-deps", "--no-build",
                    "--pull", "never", "transmission")
            restored = inspect("transmission")
            require(restored and restored["State"]["Status"] == "running",
                    "Transmission rollback not running")
            require_mounts(restored, EXISTING)
            require(NEW_DEST not in mount_map(restored),
                    "/Music still mounted after rollback")
            check_other_containers(others)
            print("PASS: Previous Transmission mount configuration restored",
                  file=sys.stderr)
        except Exception as rollback_exc:
            print("WARNING: Automatic rollback unverified: " +
                  str(rollback_exc), file=sys.stderr)
        raise Stop("Transmission-only Music mount update not completed") from exc

    print("PASS: Transmission /Music is mounted and writable by Transmission's UID/GID")
    print("PASS: Transmission daemon running; other container IDs/states unchanged")
    print("PASS: All four aMuTorrent mounts preserved")
    print("Active sixth privacy Compose overlay:", OVERLAY)
    print("IMPORTANT: Include all SIX privacy Compose files in future updates")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    exclusive = parser.add_mutually_exclusive_group(required=True)
    exclusive.add_argument("--check", action="store_true")
    exclusive.add_argument("--apply", action="store_true")
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    try:
        base, others, old_id, uid, gid = preflight(args.candidate)
        if args.apply:
            apply(base, others, old_id, uid, gid)
        else:
            print("READ-ONLY PASS; no host files or containers changed")
        return 0
    except (Stop, OSError, KeyError, TypeError, ValueError) as exc:
        print("STOP:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
