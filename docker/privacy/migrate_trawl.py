#!/usr/bin/env python3
"""Guarded migration of standalone TRAWL to the existing privacy Compose project.

Default --check is read-only. --apply changes only the TRAWL container and
adds its overlay. It never recreates Gluetun, Transmission, or other services.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path("/docker/privacy")
BASE = ("compose.yml", "compose.override.yml", "compose.amutorrent.yml")
OVERLAY = "compose.trawl.yml"
IMAGE = "ghcr.io/germondai/trawl:1.9.3-baseline"
ENV = {
    "SESSION_CACHE_DRIVER": "memory",
    "BROWSER_POOL_SIZE": "1",
    "MCP_ENABLED": "false",
    "METRICS_DASHBOARD_ENABLED": "false",
}


class Stop(Exception):
    pass


def need(condition, reason):
    if not condition:
        raise Stop(reason)


def command(*args, cwd=ROOT, check=True):
    try:
        result = subprocess.run(
            args, cwd=cwd, text=True, capture_output=True, timeout=90
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stop(f"Command unavailable/timed out: {args[0]}") from exc
    if check and result.returncode:
        # Do not echo compose interpolation output: it may contain private data.
        raise Stop(f"Command failed (exit {result.returncode}): {' '.join(args[:3])}")
    return result


def inspect(name):
    result = command("docker", "inspect", name, check=False)
    if result.returncode:
        return None
    return json.loads(result.stdout)[0]


def cfg_env(container):
    return dict(pair.split("=", 1) for pair in
                (container["Config"].get("Env") or []) if "=" in pair)


def service_labels(container):
    return container["Config"].get("Labels") or {}


def health():
    # The current standalone TRAWL already exposes /health on shared localhost.
    result = command(
        "docker", "exec", "gluetun", "wget", "-qO-",
        "http://127.0.0.1:8191/health", check=False
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def compose_args(files):
    args = ["docker", "compose"]
    for f in files:
        args.extend(("-f", str(f)))
    return args


def strict_files(source):
    need(ROOT.is_dir() and not ROOT.is_symlink(), "Privacy directory unavailable")
    base = [ROOT / name for name in BASE]
    for file in base:
        need(file.is_file() and not file.is_symlink(),
             f"Expected live Compose source missing/unsafe: {file}")
    target = ROOT / OVERLAY
    need(source.is_file() and not source.is_symlink(),
         "Reviewed TRAWL overlay file missing")
    if target.exists() or target.is_symlink():
        need(target.is_file() and not target.is_symlink(),
             "Live TRAWL overlay is not a normal file")
        need(target.read_bytes() == source.read_bytes(),
             "Existing live TRAWL overlay differs from reviewed source")
    return base, target


def preflight(source):
    need(os.geteuid() == 0 and socket.gethostname() == "openmediavault",
         "Root on openmediavault required")
    need(command("docker", "compose", "version").returncode == 0,
         "Docker Compose unavailable")
    base, target = strict_files(source)
    gluetun, trawl = inspect("gluetun"), inspect("trawl")
    need(gluetun and trawl, "Gluetun and original standalone TRAWL required")
    need(gluetun["State"]["Status"] == "running", "Gluetun not running")
    need((gluetun["State"].get("Health") or {}).get("Status") == "healthy",
         "Gluetun not healthy")
    need(trawl["State"]["Status"] == "running", "Standalone TRAWL not running")
    need(not service_labels(trawl).get("com.docker.compose.project"),
         "TRAWL already Compose-managed; do not migrate again")
    need(trawl["Config"]["Image"] == IMAGE, "Unexpected TRAWL image")
    need(trawl["HostConfig"].get("NetworkMode") == "container:" + gluetun["Id"],
         "TRAWL not sharing current Gluetun network namespace")
    need(trawl["HostConfig"].get("ShmSize") == 1024 ** 3,
         "TRAWL shared-memory allocation changed")
    need(not trawl.get("Mounts"), "TRAWL has unexpected persistent mounts")
    need(not trawl["HostConfig"].get("Privileged") and
         not trawl["HostConfig"].get("CapAdd"),
         "TRAWL has unexpected elevated privileges")
    need(not trawl["HostConfig"].get("PortBindings"),
         "TRAWL has unexpected host port bindings")
    need(trawl["HostConfig"]["RestartPolicy"]["Name"] == "unless-stopped",
         "TRAWL restart policy differs from tested configuration")
    running_env = cfg_env(trawl)
    for key, expected in ENV.items():
        need(running_env.get(key) == expected,
             f"TRAWL environment differs for {key}")
    # Ensure no startup command or entrypoint override (relative to the image).
    image = json.loads(command("docker", "image", "inspect", IMAGE).stdout)[0]
    for field in ("Entrypoint", "Cmd"):
        need(trawl["Config"].get(field) == image["Config"].get(field),
             f"TRAWL custom {field} requires manual review")

    labels = service_labels(gluetun)
    expected_files = ",".join(str(path) for path in base)
    need(labels.get("com.docker.compose.project") == "privacy" and
         labels.get("com.docker.compose.service") == "gluetun" and
         labels.get("com.docker.compose.project.config_files") == expected_files,
         "Live privacy Compose provenance changed")
    before = json.loads(command(*compose_args(base), "config",
                                "--format", "json").stdout)
    after = json.loads(command(*compose_args([*base, source]), "config",
                               "--format", "json").stdout)
    old_services, new_services = before["services"], after["services"]
    need("trawl" not in old_services, "TRAWL already exists in live Compose")
    need(set(new_services) == set(old_services) | {"trawl"},
         "Reviewed overlay unexpectedly changes service list")
    for name, old in old_services.items():
        need(new_services[name] == old,
             f"Overlay unexpectedly modifies existing service: {name}")
    new = new_services["trawl"]
    need(new.get("image") == IMAGE and
         new.get("network_mode") == "service:gluetun" and
         new.get("shm_size") == 1024 ** 3 and
         new.get("restart") == "unless-stopped",
         "TRAWL Compose service does not match reviewed runtime")
    need(not new.get("volumes") and not new.get("ports") and
         not new.get("privileged") and not new.get("cap_add"),
         "TRAWL Compose adds unexpected privileges, mounts or ports")
    for key, expected in ENV.items():
        need(new.get("environment", {}).get(key) == expected,
             f"TRAWL Compose environment differs: {key}")
    need(health(), "Existing TRAWL /health check failed")
    unsafe = [
        str(p) for p in (ROOT, ROOT / "compose.override.yml")
        if p.stat().st_mode & stat.S_IWOTH
    ]
    return base, target, gluetun, unsafe


def rollback(old_name, installed_new, added_overlay, target):
    print("Migration failed; attempting TRAWL-only rollback", file=sys.stderr)
    current = inspect("trawl")
    if current and service_labels(current).get("com.docker.compose.service") == "trawl":
        command("docker", "rm", "-f", "trawl", check=False)
    old = inspect(old_name)
    if old and not inspect("trawl"):
        command("docker", "rename", old_name, "trawl")
        command("docker", "update", "--restart", "unless-stopped", "trawl")
        command("docker", "start", "trawl")
        if not health():
            print("WARNING: Restored original TRAWL did not pass /health",
                  file=sys.stderr)
    if added_overlay and not inspect("trawl") and target.is_file():
        # Retain overlay for inspection if original recovery failed.
        print("WARNING: Retaining staged overlay after incomplete rollback",
              file=sys.stderr)
    elif added_overlay and inspect("trawl") and target.is_file():
        target.unlink()


def apply(source, base, target, gluetun):
    backups = Path("/root/awtserver-trawl-migration")
    need(not backups.is_symlink(), "Backup directory is a symlink")
    backups.mkdir(mode=0o700, exist_ok=True)
    need(backups.stat().st_mode & 0o077 == 0,
         "Backup directory permissions unsafe")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    original = inspect("trawl")
    old_id = original["Id"]
    old_name = "trawl-standalone-backup-" + stamp.lower()
    need(not inspect(old_name), "Backup TRAWL container name is occupied")
    backup_file = backups / (old_name + ".json")
    fd = os.open(backup_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(original, handle, indent=2)
    added_overlay = not target.exists()
    if added_overlay:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "wb") as handle:
            handle.write(source.read_bytes())
    need(target.read_bytes() == source.read_bytes(),
         "Live overlay changed during preparation")
    files = [*base, target]
    renamed = False
    try:
        command("docker", "update", "--restart", "no", "trawl")
        command("docker", "stop", "trawl")
        command("docker", "rename", "trawl", old_name)
        renamed = True
        command(*compose_args(files), "up", "-d", "--no-deps",
                "--no-build", "--pull", "never", "trawl")
        current = inspect("trawl")
        need(current and current["State"]["Status"] == "running",
             "Compose TRAWL did not start")
        need(service_labels(current).get("com.docker.compose.project") == "privacy" and
             service_labels(current).get("com.docker.compose.service") == "trawl",
             "New TRAWL is not owned by privacy Compose")
        need(current["HostConfig"].get("NetworkMode") == "container:" + gluetun["Id"],
             "New TRAWL not attached to current VPN namespace")
        need(health(), "New TRAWL /health failed")
    except Exception:
        # A stopped/renamed original container is retained for rollback.
        if renamed:
            rollback(old_name, True, added_overlay, target)
        else:
            if inspect("trawl") and inspect("trawl")["Id"] == old_id:
                command("docker", "update", "--restart",
                        "unless-stopped", "trawl", check=False)
                command("docker", "start", "trawl", check=False)
            if added_overlay and target.is_file():
                target.unlink()
        raise
    print("PASS: Only TRAWL migrated to privacy Compose")
    print("Original stopped backup container:", old_name)
    print("IMPORTANT: Watchtower cannot enroll while this stopped original still shares Gluetun.")
    print("After independent Prowlarr/TRAWL checks, remove ONLY that named stopped backup container.")
    print("Original inspect backup (root-only):", backup_file)
    print("Keep the new overlay in all future privacy Compose commands:", target)
    print("Watchtower remains on its ORIGINAL 24-target policy until full enrollment.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="read-only preflight (default)")
    mode.add_argument("--apply", action="store_true", help="migrate only standalone TRAWL")
    parser.add_argument("--overlay-source", type=Path,
                        default=Path(__file__).with_name(OVERLAY),
                        help="reviewed Compose overlay from the same commit")
    args = parser.parse_args()
    try:
        base, target, gluetun, unsafe = preflight(args.overlay_source)
        print("PASS: Existing TRAWL and proposed privacy Compose overlay match")
        print("PASS: Existing Gluetun, Transmission, other services unchanged by overlay")
        if unsafe:
            print("WARNING: World-writable Compose path(s):", ", ".join(unsafe))
            print("Review OMV owners/ACLs and remove world-write before deployment.")
        if not args.apply:
            print("READ-ONLY: No containers or files modified")
            return 0
        need(not unsafe, "Refusing --apply with world-writable Compose sources")
        apply(args.overlay_source, base, target, gluetun)
        return 0
    except (Stop, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print("STOP:", str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
