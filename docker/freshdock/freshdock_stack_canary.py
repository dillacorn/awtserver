#!/usr/bin/env python3
"""Isolated Freshdock VPN-parent/child network-namespace test. No production changes.

Run on the live OMV host as root with --run; without --run, checks preflight only.
Production Transmission may be paused and SnapRAID may be active.
"""
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

HOST = "openmediavault"
IMAGE = "ghcr.io/turbootzz/freshdock:1.7.1"
ALPINE = "alpine:3.20.0"


class Refused(Exception):
    pass


def require(value, message):
    if not value:
        raise Refused(message)


def cmd(args, *, timeout=30, check=True):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise Refused(f"{args[0]} failed with status {result.returncode}")
    return result


def containers():
    ids = cmd(["docker", "ps", "-aq"]).stdout.split()
    return json.loads(cmd(["docker", "inspect", *ids], timeout=60).stdout) if ids else []


def single(name):
    data = json.loads(cmd(["docker", "inspect", "--type", "container", name]).stdout)
    require(len(data) == 1 and data[0]["Name"] == "/" + name,
            f"Unexpected Docker container name: {name}")
    return data[0]


def snapshot(rows):
    return {o["Name"]: (o["Id"], o["State"]["Status"]) for o in rows}


def preflight():
    require(os.geteuid() == 0, "Run as root")
    require(shutil.which("docker"), "Docker not available")
    require(cmd(["hostname"], timeout=5).stdout.strip() == HOST,
            "Not the verified OMV host")
    require(cmd(["docker", "compose", "version"], check=False).returncode == 0,
            "Docker Compose is not available")
    clock = datetime.now().strftime("%H%M")
    require(not ("0215" <= clock <= "0445"),
            "Scheduled updater/SnapRAID maintenance window: avoid overlapping tests")
    rows = containers()
    require(not any(o["Name"].startswith("/fdcanary") for o in rows),
            "Previous Freshdock canary containers remain; inspect them first")
    require(not any(o["Name"].startswith("/wudcanary") for o in rows),
            "Previous WUD canary containers remain; inspect them first")
    wud = single("wud")
    labels = wud["Config"].get("Labels") or {}
    require(labels.get("com.docker.compose.project") == "wud" and
            labels.get("com.docker.compose.service") == "wud" and
            labels.get("com.docker.compose.project.working_dir") == "/docker/wud",
            "Unexpected production WUD Compose identity")
    require(wud["State"]["Status"] == "running", "Production WUD not running")
    env = dict(x.split("=", 1) for x in wud["Config"]["Env"] if "=" in x)
    include = env.get("WUD_WATCHER_LOCAL_INCLUDE", "")
    require(include.startswith("^(?:") and include.endswith(")$") and
            env.get("WUD_WATCHER_LOCAL_WATCHBYDEFAULT") == "false" and
            env.get("WUD_WATCHER_LOCAL_WATCHEVENTS") == "false",
            "WUD watcher not strictly isolated")
    return snapshot(rows), include


def compose_content(parent, child):
    return f'''services:
  parent:
    image: {ALPINE}
    container_name: {parent}
    command: ["sleep", "3600"]
    restart: "no"
    labels:
      freshdock.enable: "true"
      freshdock.mode: "watch"
  client:
    image: {ALPINE}
    container_name: {child}
    command: ["sleep", "3600"]
    restart: "no"
    network_mode: "service:parent"
    depends_on:
      - parent
'''


def check_existing(before):
    after = snapshot(containers())
    changed = sorted(n for n, value in before.items() if after.get(n) != value)
    if changed:
        print("WARNING: PRE-EXISTING CONTAINERS CHANGED:", ", ".join(changed),
              flush=True)
        return False
    print("PASS: Pre-existing container IDs and states unchanged", flush=True)
    return True


def run_test():
    before, wud_regex = preflight()
    project = "fdcanary" + secrets.token_hex(5)
    parent, child, runner = (project + suffix for suffix in
                             ("-parent", "-client", "-runner"))
    require(not re.search(wud_regex, parent) and
            not re.search(wud_regex, child),
            "Production WUD could match the disposable test")
    with tempfile.TemporaryDirectory(prefix=project + "-", dir="/tmp") as tmp:
        source = Path(tmp) / "compose.yml"
        source.write_text(compose_content(parent, child))
        compose = ["docker", "compose", "-p", project, "-f", str(source)]
        did_start = False
        passed = False
        original = None
        try:
            print("===== Launching isolated Freshdock canary =====", flush=True)
            did_start = True
            startup = cmd(compose + ["up", "-d", "--no-build", "--pull", "always"],
                          timeout=240, check=False)
            require(startup.returncode == 0,
                    f"Test project could not start: {startup.stderr[-600:]}")
            original = single(parent)
            dependent = single(child)
            require(original["State"]["Status"] == "running" and
                    dependent["State"]["Status"] == "running" and
                    dependent["HostConfig"]["NetworkMode"] ==
                    "container:" + original["Id"],
                    "Initial child does not share parent namespace")
            print("PASS: Child initially shares parent's Docker network", flush=True)

            # Manual "recreate" uses the same health-gated recreation path as
            # Freshdock's automatic updates. Label-gated: only parent opted in.
            # No Freshdock daemon is installed or started in this test.
            trigger = ["docker", "run", "--rm", "--name", runner,
                       "--pull", "always", "--network", "bridge",
                       "-e", "FRESHDOCK_WATCH_ALL=false",
                       "-e", "FRESHDOCK_COMPOSE_AWARE=true",
                       "-e", "FRESHDOCK_CLEANUP=false",
                       "-e", "FRESHDOCK_PRUNE_DANGLING=false",
                       "-v", "/var/run/docker.sock:/var/run/docker.sock",
                       IMAGE, "recreate", parent]
            print("===== Freshdock 1.7.1: manually recreating test parent =====",
                  flush=True)
            result = cmd(trigger, timeout=360, check=False)
            for line in (result.stdout + "\n" + result.stderr).splitlines()[-45:]:
                print(line[:360])
            require(result.returncode == 0,
                    f"Freshdock exited with status {result.returncode}")
            new_parent, new_child = single(parent), single(child)
            moved_parent = new_parent["Id"] != original["Id"]
            child_running = new_child["State"]["Status"] == "running"
            attached = (new_child["HostConfig"]["NetworkMode"] ==
                        "container:" + new_parent["Id"])
            print("===== Verified Docker state =====", flush=True)
            print("Parent replaced:", moved_parent)
            print("Parent running:", new_parent["State"]["Status"] == "running")
            print("Dependent running:", child_running)
            print("Dependent attached to current parent:", attached)
            passed = (moved_parent and
                      new_parent["State"]["Status"] == "running" and
                      child_running and attached)
            print("RESULT:", "PASS" if passed else "FAIL",
                  "- Freshdock network-namespace reattachment test", flush=True)
        finally:
            if did_start:
                print("===== Cleaning ONLY disposable test project =====",
                      flush=True)
                cleanup = cmd(compose + ["down", "--remove-orphans", "--timeout", "10"],
                              timeout=120, check=False)
                if cleanup.returncode:
                    print("WARNING: Test cleanup failed; project:", project,
                          cleanup.stderr[-500:], flush=True)
                    passed = False
                else:
                    print("PASS: Test Compose project removed", flush=True)
            if not check_existing(before):
                passed = False
        require(passed, "Canary failed; see the Docker checks above")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true",
                        help="Create temporary containers and invoke Freshdock")
    args = parser.parse_args()
    try:
        if args.run:
            run_test()
        else:
            preflight()
            print("PASS: Read-only preflight; use --run to execute canary")
        return 0
    except (Refused, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print("STOP:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
