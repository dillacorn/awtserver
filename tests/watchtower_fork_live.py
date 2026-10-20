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
        self.data = {}
        for service in ("parent", "app1", "app2"):
            bind = Path(self.temp.name) / service
            bind.mkdir()
            (bind / "keep.txt").write_text("persistent-" + service)
            self.data[service] = bind
        parent_image = MOVING if mode == "parent" else OLD
        child_image = MOVING if mode == "child" else OLD
        self.config.write_text(f"""services:
  parent:
    container_name: {self.parent}
    image: {parent_image}
    command: ["sleep", "3600"]
    restart: "no"
    environment: ["WT_TEST_ENV=keep-parent"]
    labels: {{wt-test-protected: "keep-parent"}}
    volumes: ["{self.data['parent']}:/persist"]
  app1:
    container_name: {self.children[0]}
    image: {child_image}
    command: ["sleep", "3600"]
    network_mode: service:parent
    restart: "no"
    depends_on: [parent]
    environment: ["WT_TEST_ENV=keep-app1"]
    labels: {{wt-test-protected: "keep-app1"}}
    volumes: ["{self.data['app1']}:/persist"]
  app2:
    container_name: {self.children[1]}
    image: {child_image}
    command: ["sleep", "3600"]
    network_mode: service:parent
    restart: "no"
    depends_on: [parent]
    environment: ["WT_TEST_ENV=keep-app2"]
    labels: {{wt-test-protected: "keep-app2"}}
    volumes: ["{self.data['app2']}:/persist"]
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

    def protected_snapshot(self):
        result = {}
        for name in (self.parent, *self.children):
            c = inspect(name)
            result[name] = {
                "environment": sorted(c["Config"]["Env"]),
                "labels": c["Config"]["Labels"],
                "mounts": sorted((m["Source"], m["Destination"], m["RW"])
                                 for m in c["Mounts"]),
                "binds": c["HostConfig"]["Binds"],
                "restart": c["HostConfig"]["RestartPolicy"],
                "cap_add": c["HostConfig"]["CapAdd"],
                "privileged": c["HostConfig"]["Privileged"],
            }
        return result

    def assert_preserved(self, snapshot):
        for name, expected in snapshot.items():
            c = inspect(name)
            require(c is not None, f"{name}: missing after update")
            current = {
                "environment": sorted(c["Config"]["Env"]),
                "labels": c["Config"]["Labels"],
                "mounts": sorted((m["Source"], m["Destination"], m["RW"])
                                 for m in c["Mounts"]),
                "binds": c["HostConfig"]["Binds"],
                "restart": c["HostConfig"]["RestartPolicy"],
                "cap_add": c["HostConfig"]["CapAdd"],
                "privileged": c["HostConfig"]["Privileged"],
            }
            require(current == expected, f"{name}: configuration or mounts changed: "
                    + ", ".join(k for k in expected if current[k] != expected[k]))
        for service, bind in self.data.items():
            require((bind / "keep.txt").read_text() == "persistent-" + service,
                    f"{service}: persistent bind-mount data was altered")

    def watchtower(self, *names, notification_file=None):
        target = [
            self.parent if name == "parent"
            else self.children[0] if name == "child"
            else self.children[1] if name == "child2"
            else (_ for _ in ()).throw(ValueError("Unknown test target"))
            for name in names
        ]
        name = self.id + "-watchtower"
        # No scheduler active on OMV, no notification and strict positionals.
        options = ["--rm", "--name", name,
                   "-v", "/var/run/docker.sock:/var/run/docker.sock",
                   "-e", "TZ=America/New_York"]
        if notification_file is not None:
            options += ["-v", str(notification_file) + ":/run/secrets/notification_url:ro",
                        "-e", "WATCHTOWER_NOTIFICATION_URL=/run/secrets/notification_url"]
        p = docker("run", *options,
                   WATCHTOWER, "--run-once", "--no-startup-message", "--stop-timeout", "3s",
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
        protected = stack.protected_snapshot()
        # No credentials in the disposable CI test: logger:// verifies that
        # this version resolves its notification URL from a bind-mounted file.
        notification = Path(stack.temp.name) / "notification_url"
        notification.write_text("logger://\n")
        output = stack.watchtower("child", notification_file=notification)
        # The 'notify=no' log field is unrelated to whether Shoutrrr
        # successfully used the logger transport. Assert the emitted report.
        require('msg="Shoutrrr: Found new image:' in output and
                stack.children[0] in output,
                "Secret-file Shoutrrr logger did not receive the update report")
        stack.assert_running()
        stack.assert_preserved(protected)
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
        protected = stack.protected_snapshot()
        # All network dependents must be part of the watched scope.
        # v1.23.1 left them stale when only the parent was selected.
        output = stack.watchtower("parent", "child", "child2")
        stack.assert_running()
        stack.assert_preserved(protected)
        parent_stop = output.find('msg="Stopping container" container=' + stack.parent)
        parent_start = output.find('msg="Started new container" container=' + stack.parent)
        linked_stops = [output.find('msg="Stopping linked container" container=' + n)
                        for n in stack.children]
        linked_starts = [output.find('msg="Started new container" container=' + n)
                         for n in stack.children]
        require(parent_stop >= 0 and parent_start > parent_stop and
                all(0 <= n < parent_stop for n in linked_stops) and
                all(n > parent_start for n in linked_starts),
                "Dependent stop/start order was not safe")
        require(inspect(stack.parent)["Image"] == latest and
                inspect(stack.parent)["Id"] != before[stack.parent],
                "Parent was not updated")
        # Even unselected children must survive a changed parent namespace.
        for name in stack.children:
            require(inspect(name)["Id"] != before[name],
                    f"{name}: dependent was not rebuilt onto new parent")
        print("PASS: parent updated and both dependents reattached", flush=True)


def test_automatic_scheduler(latest):
    print("===== real unattended Watchtower polling of TWO clients =====", flush=True)
    docker("tag", OLD, MOVING)
    with TestStack("child") as stack:
        prior = {n: inspect(n)["Id"] for n in stack.children}
        original_parent = inspect(stack.parent)["Id"]
        protected = stack.protected_snapshot()
        updater = stack.id + "-scheduler"
        docker("run", "-d", "--rm", "--name", updater,
               "-v", "/var/run/docker.sock:/var/run/docker.sock",
               "-e", "TZ=America/New_York",
               WATCHTOWER, "--interval", "5", "--no-startup-message",
               "--stop-timeout", "3s",
               *stack.children, timeout=90)
        try:
            deadline = time.monotonic() + 160
            while time.monotonic() < deadline:
                time.sleep(3)
                try:
                    stack.assert_running()
                    if (all(inspect(n)["Id"] != prior[n] and
                            inspect(n)["Image"] == latest for n in stack.children)):
                        break
                except RuntimeError:
                    pass
            else:
                raise RuntimeError("Unattended Watchtower scheduler did not "
                                   "update both network-sharing clients")
            require(inspect(stack.parent)["Id"] == original_parent,
                    "Scheduler changed untargeted network parent")
            stack.assert_preserved(protected)
            print("PASS: automatic polling updated both network-sharing clients",
                  flush=True)
        finally:
            result = docker("logs", "--tail", "45", updater, check=False)
            print("===== unattended scheduler log =====", flush=True)
            print(result.stdout[-6500:], flush=True)
            docker("stop", "--time", "20", updater,
                   check=False, timeout=45)
            require(docker("inspect", updater, check=False).returncode != 0,
                    "Disposable unattended scheduler did not clean up")


def test_registry_failure():
    print("===== unavailable registry: original container must survive =====",
          flush=True)
    fake = "127.0.0.1:49999/ci-expected-unreachable:latest"
    name = "wtci" + uuid.uuid4().hex[:9] + "-registry-failure"
    docker("tag", OLD, fake)
    docker("run", "-d", "--name", name, "--restart", "no",
           fake, "sleep", "3600")
    try:
        before = inspect(name)
        p = docker("run", "--rm", "--name", name + "-watchtower",
                   "-v", "/var/run/docker.sock:/var/run/docker.sock",
                   WATCHTOWER, "--run-once", "--no-startup-message", "--stop-timeout", "3s",
                   name, check=False, timeout=120)
        current = inspect(name)
        require(current and current["Id"] == before["Id"] and
                current["State"]["Running"],
                "Registry failure altered/stopped a running application")
        require(any(x in p.stdout.lower() for x in
                    ("error", "failed", "refused", "unavailable")),
                "Registry failure did not produce an observable diagnostic")
        print("PASS: failed registry check reported and original preserved",
              flush=True)
    finally:
        docker("rm", "-f", name, check=False)
        docker("image", "rm", fake, check=False)


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
        test_automatic_scheduler(latest)
        test_registry_failure()
    finally:
        # Revert tag only on the disposable CI runner.
        docker("pull", MOVING, timeout=300, check=False)
    print("PASS: ALL ISOLATED WATCHTOWER NETWORK TESTS", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError) as e:
        sys.exit(f"FAIL: {e}")
