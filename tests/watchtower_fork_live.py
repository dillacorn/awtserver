#!/usr/bin/env python3
"""Live isolated Watchtower v1.23.1 networking regression. GitHub-hosted ONLY.

Tests replacement of a directly updated network-sharing child and parent
replacement with two children. No OMV access, private tokens, or SMTP.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

WATCHTOWER = "nickfedor/watchtower:1.23.1"
OLD = "alpine:3.20.0"
MOVING = "alpine:3.20"


def cmd(*args, check=True, timeout=180):
    p = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f"{list(args[:3])!r} failed: {p.stdout[-2000:]}")
    return p


def docker(*args, **kw):
    return cmd("docker", *args, **kw)


def require(ok, msg):
    if not ok:
        raise RuntimeError(msg)


def inspect(name):
    p = docker("inspect", "--type", "container", name, check=False)
    return json.loads(p.stdout)[0] if p.returncode == 0 else None


def image_id(ref):
    return docker("image", "inspect", ref, "--format", "{{.Id}}").stdout.strip()


class TestStack:
    def __init__(self, mode):
        self.id = "wtci" + uuid.uuid4().hex[:9]
        self.parent = self.id + "-parent"
        self.children = [self.id + "-app1", self.id + "-app2"]
        self.mode = mode
        self.temp = tempfile.TemporaryDirectory(prefix=self.id)
        self.config = Path(self.temp.name) / "compose.yml"
        parent_image = MOVING if mode == "parent" else OLD
        child_image = MOVING if mode == "child" else OLD
        self.config.write_text(f"""services:
  parent:
    container_name: {self.parent}
    image: {parent_image}
    command: ["sleep", "3600"]
    restart: "no"
  app1:
    container_name: {self.children[0]}
    image: {child_image}
    command: ["sleep", "3600"]
    network_mode: service:parent
    restart: "no"
    depends_on: [parent]
  app2:
    container_name: {self.children[1]}
    image: {child_image}
    command: ["sleep", "3600"]
    network_mode: service:parent
    restart: "no"
    depends_on: [parent]
""")

    def compose(self, *args, **kw):
        return cmd("docker", "compose", "-p", self.id, "-f",
                   str(self.config), *args, **kw)

    def __enter__(self):
        self.compose("up", "-d", "--no-build", "--pull", "never")
        self.assert_running()
        return self

    def assert_running(self):
        parent = inspect(self.parent)
        require(parent and parent["State"]["Running"], "Parent absent/not running")
        for child_name in self.children:
            child = inspect(child_name)
            require(child and child["State"]["Running"],
                    f"{child_name}: child absent/not running")
            require(child["HostConfig"]["NetworkMode"] == "container:" + parent["Id"],
                    f"{child_name}: dependent stale/incorrect network namespace")
            require(child["Config"]["Image"] in (OLD, MOVING),
                    f"{child_name}: image reference changed")
        return parent

    def watchtower(self, *names):
        target = [
            self.parent if name == "parent"
            else self.children[0] if name == "child"
            else self.children[1] if name == "child2"
            else (_ for _ in ()).throw(ValueError("Unknown test target"))
            for name in names
        ]
        name = self.id + "-watchtower"
        # No scheduler active on OMV, no notification and strict positionals.
        p = docker("run", "--rm", "--name", name,
                   "-v", "/var/run/docker.sock:/var/run/docker.sock",
                   "-e", "TZ=America/New_York",
                   WATCHTOWER, "--run-once", "--no-startup-message",
                   *target, timeout=270, check=False)
        print("===== Watchtower v1.23.1 logs =====", flush=True)
        print(p.stdout[-7000:], flush=True)
        require(p.returncode == 0,
                f"Watchtower exited {p.returncode}; update failed")
        return p.stdout

    def __exit__(self, *_):
        self.compose("down", "--remove-orphans", "--timeout", "10",
                     check=False, timeout=90)
        stray = docker("ps", "-aq", "--filter", "name=" + self.id).stdout.split()
        if stray:
            docker("rm", "-f", *stray, check=False)
        self.temp.cleanup()


def test_child(latest):
    print("===== direct network-sharing application update =====", flush=True)
    docker("tag", OLD, MOVING)
    with TestStack("child") as stack:
        old_parent = inspect(stack.parent)["Id"]
        old_child = inspect(stack.children[0])["Id"]
        other_child = inspect(stack.children[1])["Id"]
        stack.watchtower("child")
        stack.assert_running()
        require(inspect(stack.parent)["Id"] == old_parent,
                "Updating child unexpectedly recreated network parent")
        require(inspect(stack.children[0])["Id"] != old_child and
                inspect(stack.children[0])["Image"] == latest,
                "Watchtower did not update directly targeted network-sharing app")
        require(inspect(stack.children[1])["Id"] == other_child,
                "Untargeted sibling was unexpectedly recreated")
        print("PASS: updated network-sharing app, preserved parent/other client",
              flush=True)


def test_parent(latest):
    print("===== parent update and TWO independent network clients =====", flush=True)
    docker("tag", OLD, MOVING)
    with TestStack("parent") as stack:
        before = {n: inspect(n)["Id"] for n in
                  [stack.parent, *stack.children]}
        # All network dependents must be part of the watched scope.
        # v1.23.1 left them stale when only the parent was selected.
        stack.watchtower("parent", "child", "child2")
        stack.assert_running()
        require(inspect(stack.parent)["Image"] == latest and
                inspect(stack.parent)["Id"] != before[stack.parent],
                "Parent was not updated")
        # Even unselected children must survive a changed parent namespace.
        for name in stack.children:
            require(inspect(name)["Id"] != before[name],
                    f"{name}: dependent was not rebuilt onto new parent")
        print("PASS: parent updated and both dependents reattached", flush=True)


def main():
    require(os.environ.get("GITHUB_ACTIONS") == "true",
            "Only run in isolated GitHub Actions environment")
    require(docker("info", check=False).returncode == 0,
            "Docker daemon unavailable")
    docker("pull", WATCHTOWER, timeout=300)
    docker("pull", OLD, timeout=300)
    docker("pull", MOVING, timeout=300)
    latest = image_id(MOVING)
    require(latest != image_id(OLD),
            "Alpine 3.20.0 is no longer stale relative to 3.20")
    try:
        test_child(latest)
        test_parent(latest)
    finally:
        # Revert tag only on the disposable CI runner.
        docker("pull", MOVING, timeout=300, check=False)
    print("PASS: ALL ISOLATED WATCHTOWER NETWORK TESTS", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError) as e:
        sys.exit(f"FAIL: {e}")
