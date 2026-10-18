#!/usr/bin/env python3
"""Live, disposable Freshdock 1.7.1 scheduler + rollback tests for OMV.

Default is a read-only preflight. --automatic / --rollback / --all create
temporary Docker Compose containers and a temporary image tag. No production
Compose application is intentionally stopped, unpaused or reconfigured.
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
import time

FRESHDOCK_IMAGE = "ghcr.io/turbootzz/freshdock:1.7.1"
OLD_IMAGE = "alpine:3.20.0"
MOVING_TAG = "alpine:3.20"
LIMIT = 220


class Unsafe(RuntimeError):
    pass


def require(ok, message):
    if not ok:
        raise Unsafe(message)


def docker(args, timeout=30, check=True):
    p = subprocess.run(["docker", *args], text=True, capture_output=True,
                       timeout=timeout)
    if check and p.returncode:
        raise Unsafe(f"docker {args[0]} failed (exit {p.returncode})")
    return p


def all_containers():
    ids = docker(["ps", "-aq"]).stdout.split()
    return json.loads(docker(["inspect", *ids], timeout=60).stdout) if ids else []


def by_name(name):
    data = json.loads(docker(["inspect", "--type", "container", name]).stdout)
    require(len(data) == 1 and data[0]["Name"] == "/" + name,
            f"Unexpected container identity {name}")
    return data[0]


def snapshot(rows):
    return {c["Name"]: (c["Id"], c["State"]["Status"]) for c in rows}


def is_freshdock_opt_in(obj):
    labels = obj.get("Config", {}).get("Labels") or {}
    return (str(labels.get("freshdock.enable", "")).lower() == "true" or
            str(labels.get("com.centurylinklabs.watchtower.enable", "")).lower() == "true")


def preflight():
    require(os.geteuid() == 0, "Run as root on OMV")
    require(shutil.which("docker"), "Docker binary not installed")
    require(subprocess.run(["hostname"], text=True, capture_output=True,
                           timeout=5).stdout.strip() == "openmediavault",
            "Unexpected host")
    require(docker(["info"], check=False, timeout=20).returncode == 0,
            "Docker daemon unavailable")
    require(docker(["compose", "version"], check=False).returncode == 0,
            "Docker Compose unavailable")
    now = datetime.now().strftime("%H%M")
    require(not ("0215" <= now <= "0445"),
            "Scheduled WUD / SnapRAID window; run outside that window")
    rows = all_containers()
    require(not any(c["Name"].startswith("/fdautocanary") for c in rows),
            "Previous Freshdock auto-canary container still exists")
    require(not any(is_freshdock_opt_in(c) for c in rows),
            "A pre-existing container opts into Freshdock. Refusing temporary scheduler.")
    require(not any((c["Config"].get("Image") or "").removeprefix("docker.io/library/")
                    == MOVING_TAG for c in rows),
            f"Existing container refers to {MOVING_TAG}")
    require(docker(["image", "inspect", MOVING_TAG], check=False).returncode != 0,
            f"{MOVING_TAG} already exists: refusing to modify its tag")
    wud = by_name("wud")
    labels = wud["Config"].get("Labels") or {}
    require(labels.get("com.docker.compose.project") == "wud"
            and labels.get("com.docker.compose.service") == "wud"
            and labels.get("com.docker.compose.project.working_dir") == "/docker/wud"
            and wud["State"]["Status"] == "running",
            "Unexpected WUD container identity or state")
    env = dict(v.split("=", 1) for v in wud["Config"]["Env"] if "=" in v)
    allow = env.get("WUD_WATCHER_LOCAL_INCLUDE", "")
    require(allow.startswith("^(?:") and allow.endswith(")$")
            and env.get("WUD_WATCHER_LOCAL_WATCHBYDEFAULT") == "false"
            and env.get("WUD_WATCHER_LOCAL_WATCHEVENTS") == "false",
            "Production WUD watcher is not safely allowlisted")
    return snapshot(rows), allow


def stack(parent, child, rollback):
    health = ("cat /etc/alpine-release | grep -qx '3.20.0'"
              if rollback else "test -r /etc/alpine-release")
    return f'''services:
  parent:
    image: {MOVING_TAG}
    container_name: {parent}
    command: ["sleep", "3600"]
    restart: "no"
    labels:
      freshdock.enable: "true"
      freshdock.mode: "live"
      wud.watch: "false"
    healthcheck:
      test: ["CMD-SHELL", "{health}"]
      interval: 2s
      timeout: 2s
      retries: 2
  child:
    image: {OLD_IMAGE}
    container_name: {child}
    command: ["sleep", "3600"]
    restart: "no"
    network_mode: "service:parent"
    depends_on:
      parent:
        condition: service_healthy
    labels:
      wud.watch: "false"
'''


def wait_ready(name, timeout=30):
    for _ in range(timeout):
        c = by_name(name)
        if c["State"]["Status"] == "running" and (
            c["State"].get("Health") or {}).get("Status") == "healthy":
            return c
        time.sleep(1)
    raise Unsafe(f"{name} did not pass initial healthcheck")


def verify_existing(before):
    after = snapshot(all_containers())
    diffs = sorted(n for n, state in before.items() if after.get(n) != state)
    if diffs:
        print("WARNING: Existing containers changed:", ", ".join(diffs),
              flush=True)
        return False
    print("PASS: All pre-existing container IDs and states unchanged", flush=True)
    return True


def log_tail(name):
    p = docker(["logs", "--tail", "70", name], timeout=20, check=False)
    lines = (p.stdout + "\n" + p.stderr).splitlines()
    print("===== Freshdock scheduler log (last 70 lines) =====", flush=True)
    for line in lines[-70:]:
        print(line[:400])
    return "\n".join(lines).lower()


def run_stage(rollback):
    # Each stage creates its own random project, fresh old-image alias and
    # scheduler instance, so an image pulled in the prior stage cannot hide an
    # available update. The alias did not exist before this test.
    before, allowlist = preflight()
    project = "fdautocanary" + secrets.token_hex(5)
    parent, child, runner = [project + "-" + x for x in ("parent", "child", "runner")]
    require(not re.search(allowlist, parent) and
            not re.search(allowlist, child) and
            not re.search(allowlist, runner),
            "Production WUD might target disposable test containers")
    created_tag = False
    may_have_created_stack = False
    may_have_created_runner = False
    clean = True
    passed = False
    with tempfile.TemporaryDirectory(prefix=project + "-", dir="/tmp") as tmp:
        config = Path(tmp) / "compose.yml"
        config.write_text(stack(parent, child, rollback))
        compose = ["compose", "-p", project, "-f", str(config)]
        try:
            print("===== Pulling disposable old Alpine image =====", flush=True)
            docker(["pull", OLD_IMAGE], timeout=240)
            old_id = docker(["image", "inspect", OLD_IMAGE, "--format", "{{.Id}}"]).stdout.strip()
            require(docker(["image", "inspect", MOVING_TAG], check=False).returncode != 0,
                    "Moving tag appeared while pulling old image")
            print("===== Creating test-only old local tag =====", flush=True)
            docker(["tag", OLD_IMAGE, MOVING_TAG])
            created_tag = True
            require(docker(["image", "inspect", MOVING_TAG, "--format", "{{.Id}}"]).stdout.strip()
                    == old_id, "Moving tag did not resolve to old image")
            print("===== Starting disposable Compose stack =====", flush=True)
            may_have_created_stack = True
            up = docker(compose + ["up", "-d", "--no-build", "--pull", "never"],
                        timeout=120, check=False)
            require(up.returncode == 0, f"Test stack startup failed: {up.stderr[-500:]}")
            old_parent = wait_ready(parent)
            original_child = by_name(child)
            require(original_child["State"]["Status"] == "running" and
                    original_child["HostConfig"]["NetworkMode"] ==
                    "container:" + old_parent["Id"], "Initial namespace incorrect")
            actual = docker(["exec", parent, "cat", "/etc/alpine-release"]).stdout.strip()
            require(actual == "3.20.0",
                    f"Expected old Alpine release 3.20.0, got {actual!r}")
            print("PASS: Old parent healthy and child shares its namespace", flush=True)
            # Only this parent is Freshdock-enabled; the production containers
            # are neither changed nor selected by the temporary scheduler.
            print("===== Starting Freshdock live automatic updater =====", flush=True)
            may_have_created_runner = True
            run = docker(["run", "-d", "--rm", "--pull", "always",
                          "--name", runner, "--network", "bridge",
                          "-e", "FRESHDOCK_WATCH_ALL=false",
                          "-e", "FRESHDOCK_DEFAULT_MODE=watch",
                          "-e", "FRESHDOCK_COMPOSE_AWARE=true",
                          "-e", "FRESHDOCK_CLEANUP=false",
                          "-e", "FRESHDOCK_PRUNE_DANGLING=false",
                          "-v", "/var/run/docker.sock:/var/run/docker.sock",
                          FRESHDOCK_IMAGE, "run", "--interval", "5",
                          "--tick", "2"], timeout=240, check=False)
            require(run.returncode == 0,
                    f"Temporary scheduler startup failed: {run.stderr[-400:]}")
            print("PASS: Freshdock scheduler started (no manual recreate)", flush=True)
            deadline = time.monotonic() + LIMIT
            seen_new = False
            log = ""
            while time.monotonic() < deadline:
                time.sleep(3)
                try:
                    current = by_name(parent)
                    dep = by_name(child)
                except (Unsafe, ValueError):
                    continue  # brief gap between Docker stop / create
                if current["Id"] != old_parent["Id"]:
                    seen_new = True
                attached = dep["HostConfig"]["NetworkMode"] == "container:" + current["Id"]
                if not rollback:
                    passed = (seen_new and current["State"]["Status"] == "running"
                              and (current["State"].get("Health") or {}).get("Status")
                              == "healthy" and dep["State"]["Status"] == "running"
                              and attached and current["Image"] != old_parent["Image"])
                    if passed:
                        break
                else:
                    # On rollback, archive is renamed back to original ID and
                    # dependent must be RECREATED onto its restored namespace.
                    if seen_new and current["Id"] == old_parent["Id"] and attached:
                        if ((current["State"].get("Health") or {}).get("Status")
                                == "healthy" and dep["State"]["Status"] == "running"
                                and dep["Id"] != original_child["Id"]):
                            passed = True
                            break
            log = log_tail(runner)
            if rollback:
                require("roll" in log, "Rollback not confirmed in scheduler logs")
            print("===== Docker verification =====", flush=True)
            current = by_name(parent)
            dep = by_name(child)
            print("Mode:", "AUTOMATIC ROLLBACK" if rollback else "AUTOMATIC UPDATE")
            print("Parent replacement observed:", seen_new)
            print("Parent ID restored:", current["Id"] == old_parent["Id"])
            print("Parent health:", (current["State"].get("Health") or {}).get("Status"))
            print("Parent image changed:", current["Image"] != old_parent["Image"])
            print("Dependent state:", dep["State"]["Status"])
            print("Dependent attached to current parent:",
                  dep["HostConfig"]["NetworkMode"] == "container:" + current["Id"])
            print("RESULT:", "PASS" if passed else "FAIL", flush=True)
        finally:
            print("===== Cleanup of disposable test only =====", flush=True)
            if may_have_created_runner:
                try:
                    docker(["stop", "--time", "20", runner], timeout=45, check=False)
                    # --rm removes the runner when it exits.
                    check = docker(["inspect", "--type", "container", runner],
                                   check=False)
                    if check.returncode == 0:
                        print("WARNING: Temporary runner still exists:", runner,
                              flush=True)
                        clean = False
                except (OSError, subprocess.TimeoutExpired) as e:
                    print("WARNING: Runner cleanup error:", type(e).__name__,
                          flush=True)
                    clean = False
            if may_have_created_stack:
                try:
                    down = docker(compose + ["down", "--remove-orphans",
                                           "--timeout", "10"],
                                  timeout=100, check=False)
                    if down.returncode:
                        print("WARNING: Test stack cleanup failed:", project,
                              down.stderr[-400:], flush=True)
                        clean = False
                except (OSError, subprocess.TimeoutExpired) as e:
                    print("WARNING: Stack cleanup error:", type(e).__name__,
                          flush=True)
                    clean = False
            if created_tag:
                try:
                    removed = docker(["image", "rm", MOVING_TAG], timeout=50,
                                     check=False)
                    if removed.returncode:
                        print("WARNING: Test tag cleanup failed:", MOVING_TAG,
                              removed.stderr[-300:], flush=True)
                        clean = False
                except (OSError, subprocess.TimeoutExpired) as e:
                    print("WARNING: Image tag cleanup error:", type(e).__name__,
                          flush=True)
                    clean = False
            try:
                if not verify_existing(before):
                    clean = False
            except (OSError, subprocess.TimeoutExpired) as e:
                print("WARNING: Could not audit existing containers:",
                      type(e).__name__, flush=True)
                clean = False
        require(clean, "Disposable cleanup or production identity audit failed")
        require(passed, "Freshdock automatic test did not meet success criteria")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--automatic", action="store_true",
                      help="real scheduler digest detection and automatic network repair")
    mode.add_argument("--rollback", action="store_true",
                      help="automatic failed healthcheck and dependent rollback repair")
    mode.add_argument("--all", action="store_true",
                      help="both tests, each with its own isolated project")
    opts = p.parse_args()
    try:
        if opts.all:
            run_stage(False)
            run_stage(True)
        elif opts.automatic:
            run_stage(False)
        elif opts.rollback:
            run_stage(True)
        else:
            preflight()
            print("PASS: Read-only preflight. Use --all to run both disposable tests.")
        return 0
    except (Unsafe, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print("STOP:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
