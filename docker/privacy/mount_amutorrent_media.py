#!/usr/bin/env python3
"""Guarded aMuTorrent-only media mount extension on the observed OMV host.

--check: no writes.
--apply: adds exactly two writable bind mounts and recreates ONLY amutorrent.
Original Transmission, Gluetun, Jellyfin, and download paths are not edited.
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
BASE = ["compose.yml", "compose.override.yml",
        "compose.amutorrent.yml", "compose.trawl.yml"]
OVERLAY = ROOT / "compose.amutorrent-media.yml"
EXPECTED = """# Only two extra paths for the existing aMuTorrent container.
# Needed to clear CategoryModal read+write access warnings for /Movies and /Shows.
# Add after all currently active privacy Compose overlays; recreate only amutorrent.
# This intentionally does not change /downloads or any other service.
services:
  amutorrent:
    volumes:
      - /srv/mergerfs/data/root/Movies:/Movies:rw
      - /srv/mergerfs/data/root/Shows:/Shows:rw
"""
SOURCES = {
    "/Movies": "/srv/mergerfs/data/root/Movies",
    "/Shows": "/srv/mergerfs/data/root/Shows",
}


class Stop(RuntimeError):
    pass


def need(ok, reason):
    if not ok:
        raise Stop(reason)


def command(args, *, check=True, timeout=90):
    try:
        result = subprocess.run(args, cwd=ROOT, capture_output=True,
                                text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise Stop(f"Command unavailable or timed out: {args[0]}") from err
    if check and result.returncode:
        # Docker Compose can output interpolated secrets; never expose stderr.
        raise Stop(f"Command failed: {args[0]} (status {result.returncode})")
    return result


def inspect(name):
    result = command(["docker", "inspect", name], check=False, timeout=25)
    return json.loads(result.stdout)[0] if result.returncode == 0 else None


def compose(files, *suffix):
    args = ["docker", "compose"]
    for file in files:
        args.extend(["-f", str(file)])
    return command(args + list(suffix), timeout=120)


def effective(files):
    return json.loads(compose(files, "config", "--format", "json").stdout)["services"]


def preflight(source):
    need(os.geteuid() == 0 and socket.gethostname() == "openmediavault",
         "Run only as root on the verified openmediavault host")
    need(ROOT.is_dir() and not ROOT.is_symlink(), "Unexpected project directory")
    need(source.is_file() and not source.is_symlink() and
         source.read_text() == EXPECTED,
         "Overlay source differs from the reviewed two mounts")
    need(not OVERLAY.exists() and not OVERLAY.is_symlink(),
         "Live media overlay exists; stop and inspect, do not overwrite")
    files = [ROOT / name for name in BASE]
    need(all(p.is_file() and not p.is_symlink() for p in files),
         "Live four-file Compose set unavailable")
    before = effective(files)
    after = effective([*files, source])
    need(set(before) == set(after), "Overlay changes service names")
    for name in before:
        if name != "amutorrent":
            need(before[name] == after[name],
                 f"Overlay unexpectedly changes existing service: {name}")
    old = before["amutorrent"]
    new = after["amutorrent"]
    old_mounts = old.get("volumes") or []
    new_mounts = new.get("volumes") or []
    need(new.get("network_mode") == old.get("network_mode") == "service:gluetun",
         "Unexpected aMuTorrent networking")
    other_old = dict(old)
    other_new = dict(new)
    other_old.pop("volumes", None)
    other_new.pop("volumes", None)
    need(other_old == other_new, "Overlay changed aMuTorrent beyond mounts")
    need(len(new_mounts) == len(old_mounts) + 2 and
         new_mounts[:len(old_mounts)] == old_mounts,
         "Existing aMuTorrent mounts not preserved")
    for dest, path in SOURCES.items():
        matching = [v for v in new_mounts if v.get("target") == dest]
        need(len(matching) == 1 and matching[0].get("source") == path and
             matching[0].get("read_only") is not True and
             matching[0].get("type") == "bind",
             f"Unexpected new volume for {dest}")
        p = Path(path)
        need(p.is_dir() and not p.is_symlink(), f"Source directory unavailable: {dest}")
    tr = inspect("transmission")
    am = inspect("amutorrent")
    vpn = inspect("gluetun")
    need(tr and am and vpn and
         all(c["State"]["Status"] == "running" for c in (tr, am, vpn)),
         "Transmission, aMuTorrent, or Gluetun is unavailable")
    need((vpn["State"].get("Health") or {}).get("Status") == "healthy",
         "Gluetun health failed")
    need(am["Config"].get("User") == "1001:1000",
         "Unexpected aMuTorrent UID/GID")
    old_live = {m["Destination"]: m for m in am["Mounts"]}
    tr_live = {m["Destination"]: m for m in tr["Mounts"]}
    for dest, path in SOURCES.items():
        need(dest not in old_live, f"aMuTorrent already has {dest} mounted")
        need(dest in tr_live and tr_live[dest]["Source"] == path and
             tr_live[dest]["RW"],
             f"Transmission mount mismatch: {dest}")
    inventory_ids = command(["docker", "ps", "-aq"]).stdout.split()
    containers = json.loads(command(["docker", "inspect", *inventory_ids],
                                    timeout=75).stdout)
    saved = {c["Name"].lstrip("/"): (c["Id"], c["State"]["Status"])
             for c in containers if c["Name"] != "/amutorrent"}
    print("PASS: Effective Compose changes only aMuTorrent's two writable mounts")
    print("PASS: Transmission and host media paths match existing mounts")
    print("PASS: Default download directory and all other services unchanged")
    return files, saved


def verify_unrelated(saved):
    ids = command(["docker", "ps", "-aq"]).stdout.split()
    current = json.loads(command(["docker", "inspect", *ids], timeout=75).stdout)
    observed = {c["Name"].lstrip("/"): (c["Id"], c["State"]["Status"])
                for c in current}
    for name, ident in saved.items():
        need(observed.get(name) == ident, f"Unrelated container changed: {name}")


def apply(source, files, saved):
    fd = os.open(OVERLAY, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w") as out:
        out.write(EXPECTED)
        out.flush()
        os.fsync(out.fileno())
    all_files = [*files, OVERLAY]
    try:
        compose(all_files, "up", "-d", "--no-deps", "--no-build",
                "--pull", "never", "amutorrent")
        am = inspect("amutorrent")
        need(am and am["State"]["Status"] == "running",
             "aMuTorrent not running after recreate")
        mounts = {m["Destination"]: m for m in am["Mounts"]}
        for dest, path in SOURCES.items():
            need(dest in mounts and mounts[dest]["Source"] == path and
                 mounts[dest]["RW"], f"Runtime mount incorrect: {dest}")
        # No writes to the library. Node's fs.access verifies both R_OK/W_OK.
        script = """const fs = require('node:fs');
for (const dir of ['/Movies','/Shows']) {
  fs.accessSync(dir, fs.constants.R_OK | fs.constants.W_OK);
  console.log('PASS:', dir, 'readable and writable');
}"""
        command(["docker", "exec", "amutorrent", "node", "-e", script])
        verify_unrelated(saved)
    except Exception as exc:
        print("STOP: Mount application failed; attempting aMuTorrent-only rollback",
              file=sys.stderr)
        # Restore only aMuTorrent from original Compose files.
        rollback = command(["docker", "compose",
                            *[a for f in files for a in ("-f", str(f))],
                            "up", "-d", "--no-deps", "--no-build",
                            "--pull", "never", "amutorrent"], check=False,
                           timeout=120)
        if rollback.returncode == 0 and OVERLAY.is_file() and \
                OVERLAY.read_text() == EXPECTED:
            OVERLAY.unlink()
            print("Rollback: original aMuTorrent Compose restored; staged overlay removed",
                  file=sys.stderr)
        else:
            print("WARNING: aMuTorrent rollback not verified; staged overlay retained",
                  file=sys.stderr)
        raise Stop("aMuTorrent mount change not verified") from exc
    print("PASS: aMuTorrent has both writable media mounts")
    print("PASS: All unrelated container identities/states preserved")
    print("New active privacy overlay:", OVERLAY)
    print("IMPORTANT: Include this overlay in every future privacy Compose command")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    flags = parser.add_mutually_exclusive_group()
    flags.add_argument("--check", action="store_true")
    flags.add_argument("--apply", action="store_true")
    parser.add_argument("--overlay-source", type=Path, required=True)
    args = parser.parse_args()
    try:
        files, saved = preflight(args.overlay_source)
        if args.apply:
            apply(args.overlay_source, files, saved)
        else:
            print("READ-ONLY PASS; nothing changed")
        return 0
    except (Stop, OSError, ValueError, KeyError, TypeError) as err:
        print("STOP:", err, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
