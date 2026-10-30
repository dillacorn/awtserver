#!/usr/bin/env python3
"""Safely initialize qBittorrent without VPN/network or media access.

--check is read-only. --apply initializes only a temporary qBittorrent service.
No existing container, transmission state, media payload, or Watchtower file is edited.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import time

ROOT = Path("/docker/privacy")
BASE = ("compose.yml", "compose.override.yml", "compose.amutorrent.yml", "compose.trawl.yml")
OVERLAY = ROOT / "compose.qbittorrent-init.yml"
CONFIG_PARENT = ROOT / "qbittorrent"
CONFIG = CONFIG_PARENT / "config"
SOURCE_SHA256 = "d1fb4404fa0a149c07e4aa2a69038fd4199359abcceb5d8316c192f9a0bd9344"
APP_NAMES = ("gluetun", "transmission", "amutorrent", "prowlarr", "trawl",
             "tailscale-transmission", "watchtower")


class Stop(RuntimeError):
    pass


def need(condition, detail):
    if not condition:
        raise Stop(detail)


def run(*args, timeout=90, cwd=ROOT, check=True):
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True,
                                text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stop(f"Command unavailable or timed out: {args[0]}") from exc
    if check and result.returncode:
        # Compose stdout/stderr may contain interpolated credentials.
        raise Stop(f"Command failed: {args[0]} (status {result.returncode}; output suppressed)")
    return result


def inspect(name):
    result = run("docker", "inspect", name, timeout=25, check=False)
    return json.loads(result.stdout)[0] if result.returncode == 0 else None


def compose_command(files, *args):
    cmd = ["docker", "compose"]
    for file in files:
        cmd.extend(("-f", str(file)))
    return (*cmd, *args)


def effective(files):
    result = run(*compose_command(files, "config", "--format", "json"),
                 timeout=60)
    return json.loads(result.stdout)["services"]


def preflight(source):
    need(os.geteuid() == 0 and socket.gethostname() == "openmediavault",
         "Root on openmediavault required")
    need(ROOT.is_dir() and not ROOT.is_symlink(),
         "Expected Compose project directory missing/unsafe")
    need(source.is_file() and not source.is_symlink(),
         "Staging overlay source is not a regular file")
    need(hashlib.sha256(source.read_bytes()).hexdigest() == SOURCE_SHA256,
         "Overlay source digest mismatch; stop before writing")
    need(not OVERLAY.exists() and not OVERLAY.is_symlink(),
         "Initializer overlay already exists; inspect prior attempt")
    need(not CONFIG_PARENT.exists() and not CONFIG_PARENT.is_symlink(),
         "qBittorrent configuration already exists; preserve it")
    need(not inspect("qbittorrent") and not inspect("qbittorrent-init"),
         "Existing qBittorrent container detected; preserve it")

    base = [ROOT / file for file in BASE]
    need(all(file.is_file() and not file.is_symlink() for file in base),
         "Missing or unsafe live Compose file")

    original = effective(base)
    proposed = effective([*base, source])
    need(set(proposed) == set(original) | {"qbittorrent-init"},
         "Staging source changes unexpected service names")
    for name, value in original.items():
        need(proposed[name] == value,
             f"Staging source unexpectedly changes existing service {name}")

    service = proposed["qbittorrent-init"]
    need(service.get("network_mode") == "none" and
         not service.get("ports") and not service.get("depends_on") and
         not service.get("cap_add") and not service.get("privileged"),
         "Initializer is not isolated from network and existing services")
    need(service.get("restart") == "no",
         "Initializer restart policy is not disabled")
    mounts = service.get("volumes") or []
    need(len(mounts) == 1 and mounts[0].get("source") == str(CONFIG) and
         mounts[0].get("target") == "/config" and
         mounts[0].get("type") == "bind",
         "Initializer volume map changed")

    inventory = {}
    for name in APP_NAMES:
        item = inspect(name)
        need(item and item["State"]["Status"] == "running",
             f"Required existing container absent/stopped: {name}")
        inventory[name] = (item["Id"], item["State"]["Status"])

    for name in ("gluetun", "transmission", "amutorrent", "trawl"):
        label = inspect(name)["Config"].get("Labels") or {}
        need(label.get("com.docker.compose.project") == "privacy",
             f"Unexpected Compose project: {name}")

    need((inspect("gluetun")["State"].get("Health") or {}).get("Status") == "healthy",
         "Gluetun is not healthy")

    torrent_state = ROOT / "transmission/data"
    torrents = {p.name[:-8] for p in (torrent_state / "torrents").glob("*.torrent")}
    resumes = {p.name[:-7] for p in (torrent_state / "resume").glob("*.resume")}
    need(torrents and torrents == resumes,
         "Transmission torrent/resume filename mismatch; do not stage")
    print(f"PASS: {len(torrents)} Transmission torrent/resume filename pairs")
    print("PASS: Existing Compose services unchanged by offline overlay")
    print("PASS: No network, host ports, or media mounts on initializer")
    print("PASS: Existing privacy containers are running; Gluetun healthy")
    return base, inventory


def unchanged(inventory):
    for name, (identity, status) in inventory.items():
        item = inspect(name)
        need(item and (item["Id"], item["State"]["Status"]) == (identity, status),
             f"Existing container changed independently: {name}")


def apply(source, base, inventory):
    # Never overwrite existing files; fail recoverably if deployment is interrupted.
    fd = os.open(OVERLAY, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(source.read_bytes())
        handle.flush()
        os.fsync(handle.fileno())

    CONFIG_PARENT.mkdir(mode=0o750)
    CONFIG.mkdir(mode=0o750)
    os.chown(CONFIG_PARENT, 1000, 1000)
    os.chown(CONFIG, 1000, 1000)

    files = [*base, OVERLAY]
    print("Staged isolated initializer overlay and new config directory", flush=True)
    run(*compose_command(files, "pull", "qbittorrent-init"), timeout=240)
    unchanged(inventory)

    started = False
    try:
        run(*compose_command(files, "up", "-d", "--no-deps",
                             "--no-build", "--pull", "never", "qbittorrent-init"),
            timeout=100)
        started = True
        item = inspect("qbittorrent-init")
        need(item and item["HostConfig"]["NetworkMode"] == "none",
             "Initializer did not start with isolated network")
        need(item["Config"]["Labels"].get("com.docker.compose.project") == "privacy" and
             item["Config"]["Labels"].get("com.docker.compose.service") == "qbittorrent-init",
             "Unexpected initializer Compose identity")
        need(not item["HostConfig"].get("PortBindings") and
             len(item.get("Mounts", [])) == 1 and
             item["Mounts"][0]["Source"] == str(CONFIG) and
             item["Mounts"][0]["Destination"] == "/config",
             "Unexpected running initializer mounts/ports")
        conf = CONFIG / "qBittorrent/qBittorrent.conf"
        for _ in range(30):
            if conf.is_file() and conf.stat().st_size > 0:
                break
            time.sleep(2)
        need(conf.is_file() and conf.stat().st_size > 0,
             "qBittorrent did not create its configuration")
    finally:
        # Only a container created for this stage is stopped.
        if started:
            stop = run(*compose_command(files, "stop", "--timeout", "60",
                                        "qbittorrent-init"),
                       timeout=100, check=False)
            need(stop.returncode == 0, "Could not stop offline initializer")

    need(not inspect("qbittorrent-init")["State"]["Running"],
         "Offline initializer is still running")
    unchanged(inventory)
    print("PASS: qBittorrent config initialized offline; staging container stopped")
    print("PASS: All original application container IDs/states preserved")
    print(f"Config: {CONFIG / 'qBittorrent/qBittorrent.conf'}")
    print("NEXT: Do not start final qBittorrent until Watchtower cutover is prepared")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="Read-only preflight")
    action.add_argument("--apply", action="store_true", help="Initialize offline")
    parser.add_argument("--overlay-source", type=Path, required=True)
    args = parser.parse_args()
    try:
        base, inventory = preflight(args.overlay_source)
        if args.apply:
            apply(args.overlay_source, base, inventory)
        else:
            print("READ-ONLY: no files or containers changed")
        return 0
    except (Stop, OSError, ValueError, TypeError, KeyError, AssertionError) as exc:
        print("STOP:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
