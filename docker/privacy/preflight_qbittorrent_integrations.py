#!/usr/bin/env python3
"""Read-only host-specific preflight for qBittorrent, Pi-hole and Watchtower.

Does not print credentials, DNS host entries, TLS key material or Compose JSON.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys

HOST = "openmediavault"
WATCH_ROOT = Path("/docker/watchtower-fork")
PRIVATE = Path("/docker/privacy")
QBIT_CONF = PRIVATE / "qbittorrent/config/qBittorrent/qBittorrent.conf"


class Stop(RuntimeError):
    pass


def need(ok, reason):
    if not ok:
        raise Stop(reason)


def run(*args, timeout=30, cwd=None, check=True):
    try:
        proc = subprocess.run(args, capture_output=True, text=True,
                              timeout=timeout, cwd=cwd)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise Stop(f"Command unavailable/timed out: {args[0]}") from err
    if check and proc.returncode:
        raise Stop(f"Command failed: {args[0]} (output suppressed)")
    return proc


def inspect(name):
    proc = run("docker", "inspect", name, check=False)
    return json.loads(proc.stdout)[0] if proc.returncode == 0 else None


def meta(c):
    return (c["Config"].get("Labels") or {})


def compose_files(c):
    raw = meta(c).get("com.docker.compose.project.config_files", "")
    need(raw, "Missing original Compose files label")
    paths = [Path(p) for p in raw.split(",")]
    need(all(p.is_absolute() and p.is_file() and not p.is_symlink()
             for p in paths), "Original Compose file missing/symlink")
    return paths


def effective(paths, project_dir):
    args = ["docker", "compose", "--project-directory", str(project_dir)]
    for path in paths:
        args.extend(["-f", str(path)])
    result = run(*args, "config", "--format", "json", timeout=60)
    return json.loads(result.stdout)["services"]


def main():
    need(os.geteuid() == 0 and socket.gethostname() == HOST,
         "Root on the exact openmediavault host required")
    names = ("gluetun", "transmission", "amutorrent", "trawl",
             "tailscale-transmission", "watchtower", "pihole", "nginx-pihole")
    containers = {n: inspect(n) for n in names}
    need(all(containers.values()), "One or more required containers missing")
    for n, c in containers.items():
        need(c["State"]["Status"] == "running", f"Container not running: {n}")
    need(not inspect("qbittorrent") and not inspect("tailscale-qbittorrent"),
         "Replacement container already exists; review before writing")
    init = inspect("qbittorrent-init")
    need(init and init["State"]["Status"] == "exited" and
         init["HostConfig"]["NetworkMode"] == "none",
         "Offline initializer is not stopped in isolated mode")
    need(QBIT_CONF.is_file() and not QBIT_CONF.is_symlink() and
         QBIT_CONF.stat().st_size > 0,
         "qBittorrent config not initialized")

    print("=== PRIVACY STACK ===")
    live = [PRIVATE / name for name in
            ("compose.yml", "compose.override.yml", "compose.amutorrent.yml",
             "compose.trawl.yml")]
    need(all(p.is_file() and not p.is_symlink() for p in live),
         "Current four-file Compose stack incomplete")
    source_services = effective(live, PRIVATE)
    need("transmission" in source_services and
         "qbittorrent" not in source_services and "trawl" in source_services,
         "Unexpected active privacy Compose services")
    print("PASS: Four-file effective privacy Compose contains Transmission, no qBittorrent")
    print("PASS: qBittorrent offline config exists; initializer stopped")
    print("PASS: No new qBittorrent or Tailscale container running")

    print("\n=== PI-HOLE / NGINX ===")
    pihole = containers["pihole"]
    nginx = containers["nginx-pihole"]
    need(meta(pihole).get("com.docker.compose.project") == "pihole",
         "Unexpected Pi-hole project")
    need(meta(nginx).get("com.docker.compose.project") == "pihole",
         "Unexpected nginx project")
    pfiles = compose_files(pihole)
    nfiles = compose_files(nginx)
    need(pfiles == nfiles,
         "Pi-hole and nginx have mismatching Compose provenance")
    print("Pi-hole Compose files (active container provenance):")
    for file in pfiles:
        print(" ", file.name)
    services = effective(pfiles, Path("/docker/pihole"))
    need("pihole" in services and "nginx" in services,
         "Effective Pi-hole Compose services unexpected")
    hosts = (services["pihole"].get("environment") or {}).get("FTLCONF_dns_hosts")
    need(isinstance(hosts, str) and hosts.strip(),
         "Pi-hole DNS hosts not in FTLCONF_dns_hosts string; manual review needed")
    print("DNS env contains Transmission host:", bool(re.search(
        r"(?im)^\s*\S+\s+transmission\.[A-Za-z0-9.-]+\s*$", hosts)))
    print("DNS env already contains qBittorrent host:", bool(re.search(
        r"(?im)^\s*\S+\s+qbittorrent\.[A-Za-z0-9.-]+\s*$", hosts)))
    mount = {m["Destination"]: m["Source"] for m in nginx["Mounts"]}
    print("nginx conf mount:", mount.get("/etc/nginx/conf.d", "UNAVAILABLE"))
    print("qBittorrent cert mount:",
          "present" if "/etc/nginx/qbittorrent-certs" in mount else "not present")
    print("nginx effective service certificate mounts:",
          len(services["nginx"].get("volumes", [])))
    test = run("docker", "exec", "nginx-pihole", "nginx", "-t",
               check=False, timeout=12)
    print("nginx -t:", "PASS" if test.returncode == 0 else "FAILED")
    need(test.returncode == 0, "Existing nginx configuration invalid")

    print("\n=== WATCHTOWER ===")
    verifier = WATCH_ROOT / "watchtower_verify.py"
    manifest = WATCH_ROOT / "targets.json"
    config = WATCH_ROOT / "compose.yml"
    for p in (verifier, manifest, config):
        need(p.is_file() and not p.is_symlink() and p.stat().st_uid == 0,
             f"Private Watchtower source missing/unsafe: {p.name}")
    need(stat.S_IMODE(manifest.stat().st_mode) & 0o077 == 0,
         "Watchtower manifest is not root-private")
    data = json.loads(manifest.read_text())
    targets = data.get("container_names")
    need(isinstance(targets, list) and len(targets) == len(set(targets)),
         "Invalid Watchtower target manifest")
    print("Selected target count:", len(targets))
    print("Transmission selected:", "transmission" in targets)
    print("Old Tailscale selected:", "tailscale-transmission" in targets)
    print("qBittorrent selected:", "qbittorrent" in targets)
    print("New Tailscale selected:", "tailscale-qbittorrent" in targets)
    print("Verifier SHA256:", hashlib.sha256(verifier.read_bytes()).hexdigest())
    print("Watchtower Compose SHA256:", hashlib.sha256(config.read_bytes()).hexdigest())
    print("Watchtower target manifest SHA256:",
          hashlib.sha256(manifest.read_bytes()).hexdigest())
    need(len(targets) == 28 and
         "transmission" in targets and
         "tailscale-transmission" in targets and
         "qbittorrent" not in targets and
         "tailscale-qbittorrent" not in targets,
         "Unexpected current Watchtower enrollment")

    print("\n=== NEW TAILSCALE MACHINE ===")
    auth = PRIVATE / "ts/qbittorrent/authkey.env"
    if auth.exists():
        need(auth.is_file() and not auth.is_symlink() and
             auth.stat().st_uid == 0 and
             stat.S_IMODE(auth.stat().st_mode) & 0o077 == 0,
             "Tailscale key file must be root-owned 0600")
        print("Auth key file: present (contents not read or printed)")
    else:
        print("Auth key file: not created; expected before sidecar registration")
    print("\nREAD-ONLY PREFLIGHT COMPLETE")
    print("No services, DNS settings, Watchtower targets or files changed")


if __name__ == "__main__":
    try:
        main()
    except (Stop, OSError, KeyError, ValueError, TypeError) as err:
        print("STOP:", err, file=sys.stderr)
        sys.exit(1)
