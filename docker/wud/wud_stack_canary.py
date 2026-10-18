#!/usr/bin/env python3
"""Read-only preflight by default; --run tests WUD against a disposable Compose namespace stack."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

HOST = "openmediavault"
WUD_IMAGE = "getwud/wud:9.4.1"
PARENT_IMAGE = "alpine:3.20.10"
CLIENT_IMAGE = "alpine:3.24.2"
PRIVACY = ("gluetun", "transmission", "mullvad-browser")
MANAGED = ("audiobookshelf", "brave", "calibre", "immich_server",
           "jellyfin", "mullvad-browser", "transmission")

class Blocked(RuntimeError):
    pass

def require(ok, reason):
    if not ok:
        raise Blocked(reason)

def call(args, *, timeout=25, check=True):
    p = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if check and p.returncode:
        raise Blocked(f"Command failed: {args[0]} (code {p.returncode})")
    return p

def inspect(name):
    result = json.loads(call(["docker", "inspect", "--type", "container", name]).stdout)
    require(len(result) == 1 and result[0]["Name"] == "/" + name,
            f"Unexpected container identity: {name}")
    return result[0]

def all_containers():
    ids = call(["docker", "ps", "-aq"]).stdout.split()
    return json.loads(call(["docker", "inspect", *ids], timeout=40).stdout) if ids else []

def snapraid_active():
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmd = [x.decode(errors="replace") for x in
                   (proc / "cmdline").read_bytes().split(b"\0") if x]
        except OSError:
            continue
        if cmd and (Path(cmd[0]).name == "snapraid" or
                    any(Path(x).name == "snapraid-aio-script.sh" for x in cmd[1:])):
            return True
    return False

def check_disk_errors():
    p = call(["journalctl", "-k", "--since", "20 minutes ago",
              "--no-pager", "-o", "cat"], timeout=20, check=False)
    require(p.returncode == 0, "Cannot check recent kernel disk errors")
    bad = re.search(r"ata13:.*(?:reset|frozen)|ata13\.00:.*(?:timeout|failed)|"
                    r"I/O error, dev sdb\b|Buffer I/O error, dev sdb\b", p.stdout, re.I)
    require(not bad, "Recent sdb/ata13 disk errors; resolve SATA before testing")

def compose_labels(obj, project, service, directory):
    labels = obj["Config"].get("Labels") or {}
    require(labels.get("com.docker.compose.project") == project and
            labels.get("com.docker.compose.service") == service and
            labels.get("com.docker.compose.project.working_dir") == directory,
            f"{service}: unexpected Compose identity/location")

def baseline():
    require(os.geteuid() == 0, "Root required")
    require(shutil.which("docker"), "Docker unavailable")
    require(call(["hostname"], timeout=5).stdout.strip() == HOST, "Wrong host")
    require(call(["docker", "compose", "version"], check=False).returncode == 0,
            "Docker Compose unavailable")
    now = datetime.now().strftime("%H%M")
    require(not ("0215" <= now <= "0445"), "Inside scheduled WUD/Docker/SnapRAID window")
    require(not snapraid_active(), "SnapRAID still running")
    check_disk_errors()
    current = all_containers()
    require(not any(str((c.get("Config", {}).get("Labels") or {}).get("wud.watch", "")).lower()
                    == "true" for c in current),
            "Existing wud.watch=true label may bypass isolated watcher filter")
    require(not any(c["Name"].startswith("/wudcanary") for c in current),
            "Leftover canary container detected; review before running again")
    wud = inspect("wud")
    compose_labels(wud, "wud", "wud", "/docker/wud")
    require(wud["Config"]["Image"] == WUD_IMAGE and
            wud["State"]["Status"] == "running" and
            (wud["State"].get("Health") or {}).get("Status") == "healthy",
            "Expected production WUD 9.4.1 not healthy")
    env = dict(x.split("=", 1) for x in wud["Config"]["Env"] if "=" in x)
    regex = env.get("WUD_WATCHER_LOCAL_INCLUDE", "")
    require(regex and env.get("WUD_WATCHER_LOCAL_WATCHBYDEFAULT") == "false" and
            env.get("WUD_WATCHER_LOCAL_WATCHEVENTS") == "false",
            "Production WUD watcher filters differ")
    vpn = inspect("gluetun")
    compose_labels(vpn, "privacy", "gluetun", "/docker/privacy")
    require(vpn["State"]["Status"] == "running" and
            (vpn["State"].get("Health") or {}).get("Status") == "healthy",
            "Gluetun unhealthy")
    for name in MANAGED:
        require(inspect(name)["State"]["Status"] != "paused",
                f"{name} paused; restore normal operation first")
    for name in PRIVACY[1:]:
        obj = inspect(name)
        compose_labels(obj, "privacy", name, "/docker/privacy")
        require(obj["State"]["Status"] == "running" and
                obj["HostConfig"]["NetworkMode"] == "container:" + vpn["Id"],
                f"{name} not running inside current Gluetun namespace")
    route = call(["docker", "exec", "gluetun", "ip", "-4", "route",
                  "get", "1.1.1.1"], timeout=15).stdout
    require(re.search(r"\bdev tun0\b", route),
            "Gluetun VPN route unavailable")
    return {o["Name"]: (o["Id"], o["State"]["Status"]) for o in current}, regex

def compose_yaml(parent, client):
    return f'''services:
  vpn-parent:
    image: {PARENT_IMAGE}
    container_name: {parent}
    command: ["sleep", "3600"]
    restart: "no"
  vpn-client:
    image: {CLIENT_IMAGE}
    container_name: {client}
    command: ["sleep", "3600"]
    network_mode: "service:vpn-parent"
    depends_on:
      - vpn-parent
    restart: "no"
'''

def unchanged(before):
    current = {c["Name"]: (c["Id"], c["State"]["Status"]) for c in all_containers()}
    diff = sorted(x for x, value in before.items() if current.get(x) != value)
    if diff:
        print("WARNING: Pre-existing containers changed:", ", ".join(diff))
        return False
    print("PASS: All pre-existing container IDs/states unchanged")
    return True

def test():
    before, production_regex = baseline()
    project = "wudcanary" + secrets.token_hex(5)
    parent, client, runner = (project + "-" + x for x in ("parent", "client", "runner"))
    require(not re.search(production_regex, parent) and
            not re.search(production_regex, client),
            "Production WUD could watch the canary; stopping")
    require(not any(name.startswith("/" + project) for name in before),
            "Unexpected canary collision")
    with tempfile.TemporaryDirectory(prefix=project + "-", dir="/tmp") as tmp:
        compose = Path(tmp) / "compose.yml"
        compose.write_text(compose_yaml(parent, client))
        cmd = ["docker", "compose", "-p", project, "-f", str(compose)]
        cleanup_required = False
        verdict = "INCONCLUSIVE"
        try:
            print("===== Starting disposable shared-namespace Compose stack =====", flush=True)
            cleanup_required = True
            setup = call(cmd + ["up", "-d", "--no-build", "--pull", "always"],
                         timeout=240, check=False)
            if setup.returncode:
                print(setup.stderr[-800:])
                raise Blocked("Canary Compose startup failed")
            original_parent = inspect(parent)
            original_client = inspect(client)
            require(original_parent["State"]["Status"] == "running" and
                    original_client["State"]["Status"] == "running" and
                    original_client["HostConfig"]["NetworkMode"] ==
                    "container:" + original_parent["Id"],
                    "Initial network dependency failed")
            print("PASS: Test client shares original parent namespace", flush=True)
            # Actual image update through WUD; only this disposable parent is watched.
            args = ["docker", "run", "--rm", "--pull=never", "--name", runner,
                    "--network", "bridge",
                    "-e", "WUD_RUN_MODE=oneshot",
                    "-e", "WUD_WATCHER_LOCAL_INCLUDE=^" + parent + "$",
                    "-e", "WUD_WATCHER_LOCAL_WATCHBYDEFAULT=false",
                    "-e", "WUD_WATCHER_LOCAL_WATCHDIGESTDEFAULT=false",
                    "-e", "WUD_TRIGGER_DOCKER_CANARY_AUTO=true",
                    "-e", "WUD_TRIGGER_DOCKER_CANARY_EVENTS=available",
                    "-e", "WUD_TRIGGER_DOCKER_CANARY_ROLLBACK=true",
                    "-e", "WUD_TRIGGER_DOCKER_CANARY_ROLLBACKGRACE=15000",
                    "-e", "WUD_TRIGGER_DOCKER_CANARY_PRUNE=false",
                    "-e", "WUD_TRIGGER_DOCKER_CANARY_SELFUPDATE=false",
                    "-e", "WUD_SERVER_ENABLED=false",
                    "-v", "/var/run/docker.sock:/var/run/docker.sock",
                    WUD_IMAGE, "watch", "--format=json"]
            print("===== Running real WUD 9.4.1 Docker update trigger =====", flush=True)
            result = call(args, timeout=300, check=False)
            print("WUD return code:", result.returncode)
            log_lines = [x for x in result.stderr.splitlines()
                         if re.search(r"trigger\.docker|update|fail|error|rollback|container:",
                                      x, re.I)]
            for line in log_lines[-35:]:
                print(line[:360])
            require(result.returncode == 0, "WUD one-shot scan/trigger failed")
            new_parent = inspect(parent)
            for _ in range(12):
                if new_parent["Id"] != original_parent["Id"]:
                    break
                time.sleep(5)
                new_parent = inspect(parent)
            new_client = inspect(client)
            print("===== Results =====")
            print("Parent replaced:", new_parent["Id"] != original_parent["Id"])
            print("Parent image:", new_parent["Config"]["Image"])
            print("Parent state:", new_parent["State"]["Status"])
            print("Client state:", new_client["State"]["Status"])
            correct = (new_client["HostConfig"]["NetworkMode"] ==
                       "container:" + new_parent["Id"])
            print("Client attached to current parent:", correct)
            if new_parent["Id"] == original_parent["Id"]:
                verdict = "INCONCLUSIVE: No WUD image replacement detected"
            elif (new_parent["State"]["Status"] == "running" and
                  new_client["State"]["Status"] == "running" and correct):
                verdict = "PASS: WUD updated parent without stranding its client"
            else:
                verdict = "FAIL: WUD replaced parent but dependent was stranded"
            print("RESULT:", verdict)
        finally:
            if cleanup_required:
                print("===== Removing ONLY disposable canary Compose project =====",
                      flush=True)
                done = call(cmd + ["down", "--remove-orphans", "--timeout", "10"],
                            timeout=100, check=False)
                if done.returncode:
                    print("WARNING: Canary cleanup failed; inspect project:", project,
                          done.stderr[-500:])
                else:
                    print("PASS: Canary Compose project removed")
            unchanged(before)
        require(verdict.startswith("PASS:"), verdict)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true",
                        help="Create disposable stack and exercise real WUD update")
    args = parser.parse_args()
    try:
        if args.run:
            test()
        else:
            baseline()
            print("PASS: Read-only preflight. --run enables isolated live canary test.")
        return 0
    except (Blocked, OSError, ValueError, subprocess.TimeoutExpired) as e:
        print("STOP:", e, file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
