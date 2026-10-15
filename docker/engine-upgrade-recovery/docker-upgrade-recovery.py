#!/usr/bin/env python3
"""Recover previously running Docker containers after APT updates the runtime.

The APT hook uses the version-1 DPkg::Pre-Install-Pkgs filename protocol.
Only runtime package updates arm a snapshot. No Compose projects are created.
"""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from contextlib import contextmanager

STATE_DIR = Path("/var/lib/omv-docker-upgrade-recovery")
PENDING = "pending.json"
RESULT = "last-result.json"
MAX_AGE = 3600  # Never act on an old APT snapshot.
MAX_ATTEMPTS = 8  # Timer retries recoverable startup failures.
MIN_AGE = 30  # Let APT and Docker settle before the first attempt.
PACKAGE = re.compile(r"^(?:docker-ce|docker-ce-cli|docker-ce-rootless-extras|docker\.io|containerd|containerd\.io|moby-engine|moby-containerd)_[^/]+\.deb$")
RECOVER_POLICIES = {"always", "unless-stopped"}
APT_LOCKS = ("/var/lib/dpkg/lock-frontend", "/var/lib/dpkg/lock")


def log(message):
    print(f"omv-docker-upgrade-recovery: {message}", flush=True)


def command(*args, timeout=20, check=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"{args[0]} failed (status {result.returncode}): {result.stderr.strip()[:300]}")
    return result.stdout.strip()


def unit_invocation(name):
    return command("systemctl", "show", "--property=InvocationID", "--value", name)


def markers():
    return {"docker": unit_invocation("docker.service"),
            "containerd": unit_invocation("containerd.service")}


def docker_entries():
    ids = command("docker", "ps", "--no-trunc", "--quiet").splitlines()
    entries = []
    for start in range(0, len(ids), 50):
        lines = command("docker", "inspect", "--format",
                        "{{.Id}}|{{.Name}}|{{.State.Status}}|{{.HostConfig.RestartPolicy.Name}}|{{.State.Paused}}",
                        *ids[start:start + 50]).splitlines()
        for line in lines:
            cid, name, state, policy, paused = line.split("|", 4)
            if state == "running" and paused == "false" and policy in RECOVER_POLICIES:
                entries.append({"id": cid, "name": name.lstrip("/"), "policy": policy})
    return entries


@contextmanager
def state_lock():
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    with (STATE_DIR / "lock").open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def load(name):
    path = STATE_DIR / name
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save(name, content):
    path = STATE_DIR / name
    temp = STATE_DIR / (name + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        os.chmod(temp, 0o600)
        json.dump(content, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def is_runtime_package(line):
    return bool(PACKAGE.fullmatch(os.path.basename(line.strip())))


def snapshot(package_lines):
    if not any(is_runtime_package(line) for line in package_lines):
        return
    try:
        with state_lock():
            existing = load(PENDING)
            if existing and time.time() - existing.get("created", 0) < MAX_AGE:
                log("Existing recovery snapshot retained; not overwriting the pre-upgrade running set")
                return
            entries = docker_entries()
            before = markers()
            if not all(before.values()):
                log("WARNING: missing systemd invocation markers; cannot arm recovery")
                return
            if not entries:
                log("No running Docker services with restart policies to protect")
                return
            save(PENDING, {"created": time.time(), "markers": before,
                           "containers": entries, "attempts": 0})
            log(f"Protected {len(entries)} running container(s) before Docker runtime package upgrade")
    except Exception as exc:
        # This APT notification hook must never prevent package maintenance,
        # including if the state file is corrupt or Docker CLI output changes.
        log(f"WARNING: unable to record pre-upgrade state: {exc}")


def apt_busy():
    handles = []
    try:
        for path in APT_LOCKS:
            if not os.path.exists(path):
                continue
            fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
            handles.append(fd)
            try:
                fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
        return False
    finally:
        for fd in handles:
            os.close(fd)


def inspect_one(cid):
    out = command("docker", "inspect", "--format",
                  "{{.Id}}|{{.State.Status}}|{{.HostConfig.RestartPolicy.Name}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
                  cid, check=False)
    if not out:
        return None
    parts = out.split("|", 3)
    if len(parts) != 4 or parts[0] != cid:
        raise RuntimeError("unexpected docker inspect output")
    return {"id": parts[0], "state": parts[1], "policy": parts[2], "health": parts[3]}


def finish(state, problems):
    result = {"finished": time.time(), "created": state["created"],
              "protected": len(state["containers"]), "problems": problems}
    save(RESULT, result)
    (STATE_DIR / PENDING).unlink(missing_ok=True)
    log(f"Recovery completed: {len(state['containers'])} protected, {len(problems)} unresolved")


def recover(dry_run=False):
    try:
        with state_lock():
            state = load(PENDING)
            if not state:
                if dry_run:
                    log("No pending APT Docker-runtime recovery")
                return
            age = time.time() - state["created"]
            if not dry_run and apt_busy():
                return
            if not dry_run and age < MIN_AGE:
                return
            if age > MAX_AGE:
                log("ERROR: recovery snapshot expired; refusing automatic container starts")
                if not dry_run:
                    finish(state, ["Recovery window expired before completion"])
                return
            after = markers()
            if not all(after.values()):
                log("WARNING: Docker or containerd service not ready")
                return
            if after == state["markers"]:
                log("Docker and containerd did not restart; no recovery necessary")
                if not dry_run:
                    finish(state, [])
                return
            # Docker may be running but its API not yet ready.
            command("docker", "info", "--format", "{{.ServerVersion}}")
            problems = []
            retries = []
            started = []
            for entry in state["containers"]:
                cid, name = entry["id"], entry["name"]
                current = inspect_one(cid)
                if current is None:
                    problems.append(f"{name}: original container ID missing or replaced; NOT recreating")
                    continue
                if current["state"] == "running":
                    if current["health"] == "unhealthy":
                        problems.append(f"{name}: running but unhealthy; manual diagnosis required")
                    continue
                if current["policy"] not in RECOVER_POLICIES:
                    problems.append(f"{name}: restart policy changed to {current['policy']}; skipping")
                    continue
                if current["state"] in ("paused", "restarting", "removing"):
                    if current["state"] == "restarting":
                        retries.append(f"{name}: Docker is already restarting it")
                    else:
                        problems.append(f"{name}: state {current['state']}; skipping")
                    continue
                if current["state"] not in ("created", "exited", "dead"):
                    problems.append(f"{name}: unexpected state {current['state']}; skipping")
                    continue
                if dry_run:
                    log(f"DRY RUN: would docker start {name} ({cid[:12]})")
                    continue
                try:
                    command("docker", "start", cid, timeout=30)
                    started.append(name)
                    log(f"Started previously running container {name} ({cid[:12]})")
                except (RuntimeError, subprocess.TimeoutExpired) as exc:
                    retries.append(f"{name}: start failed: {exc}")
            if dry_run:
                for issue in problems + retries:
                    log(f"WARNING: {issue}")
                return
            attempts = state.get("attempts", 0) + 1
            state["attempts"] = attempts
            if (retries or started) and attempts < MAX_ATTEMPTS:
                save(PENDING, state)
                for issue in problems + retries:
                    log(f"WARNING: {issue}")
                if started:
                    log(f"Will verify {len(started)} newly started container(s) on next timer check")
                if retries:
                    log(f"Will retry transient failures ({attempts}/{MAX_ATTEMPTS})")
                return
            if started:
                problems.append(f"Started {', '.join(started)} but could not verify they remained running; inspect manually")
            for issue in problems + retries:
                log(f"WARNING: {issue}")
            finish(state, problems + retries)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        log(f"WARNING: recovery check failed, will retry: {exc}")


def status():
    with state_lock():
        for name in (PENDING, RESULT):
            value = load(name)
            log(f"{name}: {json.dumps(value, indent=2) if value else 'none'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("snapshot", "recover", "status"))
    parser.add_argument("--dry-run", action="store_true", help="Preview recovery without starting containers")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("must run as root")
    if args.action == "snapshot":
        snapshot(sys.stdin)
    elif args.action == "recover":
        recover(dry_run=args.dry_run)
    else:
        status()


if __name__ == "__main__":
    main()
