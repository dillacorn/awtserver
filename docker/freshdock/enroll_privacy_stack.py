#!/usr/bin/env python3
"""Safely add Gluetun, Transmission and Mullvad Browser to Freshdock nightly updates.

Default is READ ONLY. --apply changes only these three containers and adds
/docker/privacy/compose.freshdock.yml. Fail closed on unexpected live drift.
Do not print raw inspect or Compose JSON: those contain credentials.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

import audit_enrollment as audit
import enroll_services as base
import enroll_services_verified as verified

PROJECT = "privacy"
DIRECTORY = "/docker/privacy"
SERVICES = ("gluetun", "transmission", "mullvad-browser")
OTHER = ("tailscale-transmission", "tailscale-mullvad")
CRON = "45 2 * * *"
OVERLAY = Path(DIRECTORY) / "compose.freshdock.yml"
SNAPSHOTS = Path("/docker/freshdock/snapshots")


class Stop(RuntimeError):
    pass


def need(value, message):
    if not value:
        raise Stop(message)


def call(*args, timeout=90, check=True):
    try:
        p = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stop(f"{args[0]} unavailable or timed out") from exc
    if check and p.returncode:
        raise Stop(f"{args[0]} returned {p.returncode}")
    return p


def containers():
    return {c["Name"].lstrip("/"): c for c in
            json.loads(call("docker", "inspect",
                            *call("docker", "ps", "-aq").stdout.split(),
                            timeout=90).stdout)}


def labels(c):
    return c["Config"].get("Labels") or {}


def namespace(c):
    pid = c["State"].get("Pid", 0)
    return os.readlink(f"/proc/{pid}/ns/net") if pid else None


def healthy_vpn(c):
    if c["State"].get("Status") != "running":
        return False
    if (c["State"].get("Health") or {}).get("Status") != "healthy":
        return False
    p = call("docker", "exec", "gluetun",
             "ip", "-4", "route", "get", "1.1.1.1",
             check=False)
    return p.returncode == 0 and bool(re.search(r"\bdev tun0\b", p.stdout))


def policy():
    return {"freshdock.enable": "true",
            "freshdock.mode": "nightly",
            "freshdock.schedule": CRON,
            "freshdock.notify": "true"}


def overlay_text():
    result = [
        "# Managed labels for the verified VPN privacy trio only.",
        "# Include as LAST Compose -f file for future Dockge/manual recreations.",
        "services:",
    ]
    for service in SERVICES:
        result += [
            f"  {service}:",
            "    labels:",
            '      freshdock.enable: "true"',
            '      freshdock.mode: "nightly"',
            f'      freshdock.schedule: "{CRON}"',
            '      freshdock.notify: "true"',
        ]
    return "\n".join(result) + "\n"


def compose(files, extra=()):
    args = ["docker", "compose", "-p", PROJECT,
            "--project-directory", DIRECTORY]
    for f in (*files, *extra):
        args += ["-f", str(f)]
    return args


def plan():
    need(os.geteuid() == 0 and socket.gethostname() == "openmediavault",
         "Expected root on openmediavault")
    hhmm = datetime.now().strftime("%H%M")
    need(not ("0215" <= hhmm <= "0445"), "Daily update/maintenance window")
    need(not OVERLAY.exists() and not OVERLAY.is_symlink(),
         "Existing privacy Freshdock overlay; refuse overwrite")
    by_name = containers()
    need("wud" not in by_name, "WUD must not be present")
    fd = by_name.get("freshdock")
    need(fd and fd["State"]["Status"] == "running" and
         fd["Config"]["Image"] == "ghcr.io/turbootzz/freshdock:1.7.1",
         "Freshdock 1.7.1 daemon not running")
    env = {v.split("=", 1)[0]: v.split("=", 1)[1]
           for v in fd["Config"].get("Env", []) if "=" in v}
    need(env.get("FRESHDOCK_WATCH_ALL") == "false" and
         env.get("FRESHDOCK_COMPOSE_AWARE") == "true",
         "Freshdock must use scoped Compose-aware mode")
    already = {n for n, c in by_name.items()
               if labels(c).get("freshdock.enable") == "true"}
    need(len(already) == 21 and not (already & set(SERVICES + OTHER)),
         "Expected 21 previously enrolled apps and no privacy opt-ins")
    # The earlier 21/21 production audit established the count and update
    # policy, but not a reliable hardcoded name inventory. Re-read the actual
    # running, opted-in services and refuse any scope/policy drift.
    protected = set(SERVICES + OTHER + ("vaultwarden", "nginx-vaultwarden"))
    need(not (already & protected),
         "Protected VPN/Vaultwarden service already enrolled")
    for name in sorted(already):
        c = by_name[name]
        need(c["State"]["Status"] == "running" and
             not c["State"].get("Paused") and
             all(labels(c).get(k) == v for k, v in policy().items()),
             f"{name}: currently enrolled state/Freshdock policy drift")
        meta = labels(c)
        need(all(meta.get("com.docker.compose." + key)
                 for key in ("project", "service",
                             "project.working_dir", "project.config_files")),
             f"{name}: Compose ownership metadata missing")
        origin = meta["com.docker.compose.project.config_files"]
        need(all(Path(x).is_file() for x in origin.split(",") if x),
             f"{name}: referenced Compose source missing")
    need(all(n in by_name for n in SERVICES + OTHER),
         "Privacy Compose project no longer has all five containers")
    for n in SERVICES + OTHER:
        c = by_name[n]
        need(c["State"]["Status"] == "running" and
             not c["State"].get("Paused") and
             labels(c).get("com.docker.compose.project") == PROJECT and
             labels(c).get("com.docker.compose.service") == n,
             f"{n}: state or Compose ownership changed")
        need((c["State"].get("Health") or {}).get("Status") != "unhealthy",
             f"{n}: unhealthy")
    g = by_name["gluetun"]
    need(healthy_vpn(g), "Gluetun is not healthy or tun0 is not routed")
    ns = namespace(g)
    need(ns is not None, "Gluetun namespace missing")
    for n in SERVICES[1:]:
        c = by_name[n]
        need(c["HostConfig"]["NetworkMode"] == "container:" + g["Id"] and
             namespace(c) == ns, f"{n}: VPN namespace drifted")
    # The three targets need identical, current Compose sources. The two
    # Tailscale proxies are deliberately outside the operation and can have
    # older Compose provenance without making the target source ambiguous.
    files = None
    for n in SERVICES:
        key, svc = audit.source_group(by_name[n])
        project, directory, origins = key
        need((project, directory, svc) == (PROJECT, DIRECTORY, n),
             f"{n}: unexpected source ownership")
        need(files is None or files == origins,
             f"{n}: active Compose source set differs")
        files = origins
    need(files and all(str(f).startswith(DIRECTORY + "/") for f in files),
         "Compose files not under expected directory")
    hashes, tree = audit.project_config(PROJECT, DIRECTORY, files)
    need(set(tree.get("services", {})) == set(SERVICES + OTHER),
         "Privacy project service set differs")
    for n in SERVICES:
        c = by_name[n]
        spec = tree["services"][n]
        need(labels(c).get("com.docker.compose.config-hash") == hashes.get(n),
             f"{n}: Compose source hash differs from running container")
        need(spec.get("image") == c["Config"].get("Image"),
             f"{n}: image reference drift")
        image_id = call("docker", "image", "inspect", spec["image"],
                        "--format", "{{.Id}}").stdout.strip()
        need(image_id == c["Image"], f"{n}: local image ID drift")
        differences = verified.validate_runtime(c, spec, by_name, PROJECT, tree)
        need(not differences, f"{n}: " + ", ".join(differences))
    for n in SERVICES[1:]:
        need(tree["services"][n].get("network_mode") == "service:gluetun",
             f"{n}: source would bypass VPN")
    # The overlay must be a strict label-only change to the *entire* project.
    return by_name, files, tree


def verify_after(before):
    now = containers()
    g = now["gluetun"]
    need(healthy_vpn(g), "New Gluetun is not healthy/tun0 routed")
    ns = namespace(g)
    need(ns is not None, "New Gluetun namespace absent")
    for name in SERVICES:
        c = now.get(name)
        need(c and c["State"]["Status"] == "running" and
             c["Image"] == before[name]["Image"],
             f"{name}: image ID or running state differs")
        old_mounts = {
            m["Destination"]: (m["Type"], m.get("Source"),
                               bool(m.get("RW")))
            for m in before[name].get("Mounts", [])
        }
        new_mounts = {
            m["Destination"]: (m["Type"], m.get("Source"),
                               bool(m.get("RW")))
            for m in c.get("Mounts", [])
        }
        need(old_mounts == new_mounts,
             f"{name}: persistent mounts or access policy changed")
        need(all(labels(c).get(k) == v for k, v in policy().items()),
             f"{name}: missing nightly update labels")
        need(namespace(c) == ns, f"{name}: not on Gluetun namespace")
        if name != "gluetun":
            need(c["HostConfig"]["NetworkMode"] == "container:" + g["Id"],
                 f"{name}: stale network owner ID")
        need(OVERLAY.as_posix() in labels(c).get(
            "com.docker.compose.project.config_files", ""),
            f"{name}: overlay missing from project provenance")
    for name in OTHER:
        need(now[name]["Id"] == before[name]["Id"] and
             now[name]["State"]["Status"] == "running",
             f"{name}: unrelated Tailscale proxy changed")
    for name, c in before.items():
        if name in SERVICES:
            continue
        need(now.get(name) and now[name]["Id"] == c["Id"] and
             now[name]["State"]["Status"] == c["State"]["Status"],
             f"{name}: unrelated container changed")
    current = {n for n, c in now.items()
               if labels(c).get("freshdock.enable") == "true"}
    originally = {n for n, c in before.items()
                  if labels(c).get("freshdock.enable") == "true"}
    need(current == originally | set(SERVICES) and len(current) == 24,
         "Expected exactly 24 opted-in apps")


def apply(before, files, tree):
    need(SNAPSHOTS.is_dir(), "Existing private snapshot directory missing")
    snap = SNAPSHOTS / ("privacy-before-" + datetime.now().strftime(
        "%Y%m%d-%H%M%S") + ".json")
    changed = False
    try:
        # Keep the original inspect records private. Never print credentials.
        fd = os.open(str(snap), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({n: before[n] for n in SERVICES + OTHER}, f)
        fd = os.open(str(OVERLAY), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "w") as f:
            f.write(overlay_text())
        original_cmd = compose(files)
        updated_cmd = compose(files, (OVERLAY,))
        updated = json.loads(call(
            *updated_cmd, "config", "--format", "json", timeout=45).stdout)
        reduced = base.without_freshdock(updated, SERVICES)
        need(reduced == tree, "Overlay changes something beyond approved labels")
        for name in SERVICES:
            need(all(updated["services"][name]["labels"].get(k) == v
                     for k, v in policy().items()),
                 f"{name}: Freshdock effective labels incorrect")
        print("PASS: Private snapshot and label-only Compose overlay verified.",
              flush=True)
        changed = True
        # Keep torrent/browser traffic off throughout the parent replacement.
        call("docker", "stop", "--time", "20", "transmission", "mullvad-browser",
             timeout=60)
        print("Clients stopped. Recreating only Gluetun first...",
              flush=True)
        call(*updated_cmd, "up", "-d", "--no-deps", "--no-build",
             "--pull", "never", "--force-recreate", "gluetun",
             timeout=240)
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            gluetun = containers().get("gluetun")
            if gluetun and healthy_vpn(gluetun):
                break
            time.sleep(2)
        else:
            raise Stop("Recreated Gluetun did not become VPN healthy")
        # --no-deps cannot recreate Tailscale proxies; the Gluetun parent
        # already passed its health check before either client starts.
        print("VPN healthy. Recreating Transmission and Mullvad Browser...",
              flush=True)
        call(*updated_cmd, "up", "-d", "--no-deps", "--no-build",
             "--pull", "never", "--force-recreate",
             "transmission", "mullvad-browser", timeout=240)
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            now = containers()
            if (now.get("gluetun") and healthy_vpn(now["gluetun"]) and
                    all(now.get(n) and now[n]["State"]["Status"] == "running"
                        for n in SERVICES)):
                break
            time.sleep(2)
        else:
            raise Stop("Privacy clients did not become running after VPN restoration")
        verify_after(before)
        print("PASS: 24/24 enabled, VPN healthy, both clients attached; "
              "Tailscale proxies and existing images preserved.", flush=True)
        print("PASS: All three privacy containers now receive automatic "
              "nightly updates at 02:45.", flush=True)
    except (Exception, KeyboardInterrupt):
        if not changed:
            # Overlay is created by this invocation only (preflight rejects an
            # existing path), so a failed validation can safely clean it up.
            # No container has been touched in this case.
            if OVERLAY.is_file() and not OVERLAY.is_symlink():
                OVERLAY.unlink()
        if changed:
            # Do not let partially labelled privacy clients run on an unverified
            # namespace or let the daemon update an incomplete privacy rollout.
            for n in ("transmission", "mullvad-browser"):
                call("docker", "stop", "--time", "20", n, check=False)
            call("docker", "update", "--restart=no", "freshdock", check=False)
            call("docker", "stop", "--time", "20", "freshdock", check=False)
            print("PARTIAL: Clients stopped, Freshdock disabled for safety. "
                  "Review private snapshot and retained overlay.", file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        before, files, tree = plan()
        print("PASS: Running Gluetun, Transmission and Mullvad Browser verified.")
        print("PASS: Current VPN namespace, Compose hashes, images and mounts match.")
        print("PASS: Existing 21 Freshdock opt-ins unchanged.")
        if not args.apply:
            print("READ ONLY: Use --apply for the reviewed privacy enrollment.")
        else:
            apply(before, files, tree)
        return 0
    except (Stop, audit.Stop, verified.Refused, base.Stop,
            OSError, KeyError, ValueError, subprocess.TimeoutExpired) as e:
        print("STOP:", str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
