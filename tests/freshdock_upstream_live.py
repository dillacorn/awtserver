#!/usr/bin/env python3
"""GitHub Actions-only, REAL Docker regression of Freshdock namespace updates.

Uses isolated Docker Compose stacks, a disposable local registry, and a locally
built Freshdock binary. No OMV endpoints, credentials or production images.
Expected stages: original (reproduce HTTP 400), patched (prove recovery,
direct child updates, parent repair, scheduled updates, and health rollback).
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

IMAGE = "alpine:3.20.0"
REGISTRY_IMAGE = "registry:2"


def run(args, timeout=180, check=True, env=None):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, timeout=timeout, env=env)
    if check and p.returncode:
        raise RuntimeError(f"{args[:3]} returned {p.returncode}:\n{p.stdout[-2500:]}")
    return p


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def docker(*args, timeout=180, check=True):
    return run(["docker", *args], timeout=timeout, check=check)


def inspect(name):
    p = docker("inspect", "--type", "container", name, check=False)
    return json.loads(p.stdout)[0] if p.returncode == 0 else None


def image_id(name):
    p = docker("image", "inspect", name, "--format", "{{.Id}}")
    return p.stdout.strip()


def wait_for(check, deadline=110, period=2, description="condition"):
    until = time.monotonic() + deadline
    while time.monotonic() < until:
        if check():
            return
        time.sleep(period)
    raise RuntimeError(f"Timeout waiting for {description}")


def running(c):
    return c and c["State"]["Status"] == "running"


def healthy(c):
    return running(c) and (c["State"].get("Health") or {}).get("Status") == "healthy"


def namespace(c):
    return c["HostConfig"]["NetworkMode"]


def ci_env():
    env = dict(os.environ)
    env.update(FRESHDOCK_WATCH_ALL="false",
               FRESHDOCK_COMPOSE_AWARE="false",
               FRESHDOCK_CLEANUP="false",
               FRESHDOCK_PRUNE_DANGLING="false",
               FRESHDOCK_DEFAULT_MODE="watch",
               NO_COLOR="1")
    env.pop("FRESHDOCK_CONFIG", None)
    return env


class Fixture:
    def __init__(self, stage):
        self.stage = stage
        self.id = "fdci" + uuid.uuid4().hex[:9]
        self.parent = self.id + "-parent"
        self.children = [self.id + "-childa", self.id + "-childb"]
        self.registry = self.id + "-registry"
        self.tag = f"localhost:5000/{self.id}/app:latest"
        self.temp = tempfile.TemporaryDirectory(prefix=self.id + "-")
        self.folder = Path(self.temp.name)
        self.compose_file = self.folder / "compose.yml"
        self.dockerfile = self.folder / "Dockerfile"
        self.daemon = None

    def compose(self):
        return ["docker", "compose", "-p", self.id, "-f",
                str(self.compose_file)]

    def build(self, mode):
        self.dockerfile.write_text(
            "FROM alpine:3.20.0\n"
            "ARG BUILD_MODE=good\n"
            "RUN echo \"$BUILD_MODE\" > /ci-build && "
            'if [ "$BUILD_MODE" != "bad" ]; then touch /ci-healthy; fi\n'
            "EXPOSE 80\n"
            'CMD ["sleep", "3600"]\n'
        )
        print(f"BUILD {mode}: publishing disposable {self.tag}", flush=True)
        run(["docker", "build", "--quiet", "--build-arg",
             f"BUILD_MODE={mode}", "-t", self.tag, str(self.folder)],
            timeout=300)
        docker("push", self.tag, timeout=300)
        return image_id(self.tag)

    def __enter__(self):
        docker("pull", IMAGE, timeout=300)
        docker("pull", REGISTRY_IMAGE, timeout=300)
        docker("run", "-d", "--name", self.registry, "--rm",
               "-p", "127.0.0.1:5000:5000", REGISTRY_IMAGE)
        wait_for(lambda: run(
            ["curl", "-fsS", "http://127.0.0.1:5000/v2/"],
            timeout=10, check=False).returncode == 0,
            description="disposable local registry", deadline=20)
        self.build("old")
        self.compose_file.write_text(f"""services:
  parent:
    image: {IMAGE}
    container_name: {self.parent}
    command: ["sleep", "3600"]
    restart: "no"
    labels:
      freshdock.enable: "true"
      freshdock.mode: "watch"
  childa:
    image: {self.tag}
    container_name: {self.children[0]}
    network_mode: "service:parent"
    command: ["sleep", "3600"]
    restart: "no"
    depends_on:
      - parent
    labels:
      freshdock.enable: "true"
      freshdock.mode: "live"
      freshdock.notify: "false"
    healthcheck:
      test: ["CMD-SHELL", "test -f /ci-healthy"]
      interval: 2s
      timeout: 2s
      retries: 3
  childb:
    image: {self.tag}
    container_name: {self.children[1]}
    network_mode: "service:parent"
    command: ["sleep", "3600"]
    restart: "no"
    depends_on:
      - parent
    labels:
      freshdock.enable: "true"
      freshdock.mode: "live"
      freshdock.notify: "false"
    healthcheck:
      test: ["CMD-SHELL", "test -f /ci-healthy"]
      interval: 2s
      timeout: 2s
      retries: 3
""")
        run(self.compose() + ["up", "-d", "--no-build", "--pull", "never"],
            timeout=150)
        wait_for(lambda: all(healthy(inspect(n)) for n in self.children),
                 deadline=55, description="both disposable children healthy")
        self.assert_network()
        for name in self.children:
            c = inspect(name)
            print("CREATED", name, "hostname =", c["Config"].get("Hostname"),
                  "exposed ports =", bool(c["Config"].get("ExposedPorts")),
                  "network mode =", namespace(c)[:24], flush=True)
        return self

    def assert_network(self):
        parent = inspect(self.parent)
        require(running(parent), "Test network parent is not running")
        for name in self.children:
            child = inspect(name)
            require(healthy(child), f"{name} unhealthy or missing")
            require(namespace(child) == "container:" + parent["Id"],
                    f"{name} not attached to current parent")
            require(child["Config"]["Image"] == self.tag,
                    f"{name} image reference became pinned")
        return parent

    def stop_daemon(self):
        if self.daemon:
            self.daemon.terminate()
            try:
                stdout, _ = self.daemon.communicate(timeout=25)
            except subprocess.TimeoutExpired:
                self.daemon.kill()
                stdout, _ = self.daemon.communicate(timeout=10)
            print("===== Freshdock scheduler logs (tail) =====")
            print("\n".join(stdout.splitlines()[-50:]))
            self.daemon = None
            return stdout
        return ""

    def start_daemon(self, binary):
        log = self.folder / "scheduler.log"
        self.daemon_file = log.open("w+")
        self.daemon = subprocess.Popen(
            [str(binary), "run", "--interval", "4", "--tick", "1"],
            cwd=self.folder, env=ci_env(),
            stdout=self.daemon_file, stderr=subprocess.STDOUT, text=True)

    def daemon_log(self):
        if not hasattr(self, "daemon_file"):
            return ""
        self.daemon_file.flush()
        return (self.folder / "scheduler.log").read_text(errors="replace")

    def __exit__(self, kind, value, traceback):
        if self.daemon:
            self.daemon.terminate()
            try:
                self.daemon.wait(timeout=25)
            except subprocess.TimeoutExpired:
                self.daemon.kill()
                self.daemon.wait()
            self.daemon = None
            try:
                self.daemon_file.flush()
                print("===== Freshdock scheduler log tail =====")
                print("\n".join(self.daemon_log().splitlines()[-80:]))
            finally:
                self.daemon_file.close()
        # Strictly limited to the randomized disposable project/registry.
        run(self.compose() + ["down", "--remove-orphans", "--timeout", "10"],
            timeout=80, check=False)
        ids = docker("ps", "-aq", "--filter", "name=" + self.id,
                     check=False).stdout.split()
        if ids:
            docker("rm", "-f", *ids, check=False)
        docker("rm", "-f", self.registry, check=False)
        self.temp.cleanup()


def original_stage(binary):
    print("===== EXPECTED-FAIL original Freshdock 1.7.1 =====", flush=True)
    with Fixture("original") as fixture:
        child = fixture.children[0]
        before = inspect(child)["Id"]
        result = run([str(binary), "recreate", child], env=ci_env(),
                     timeout=120, check=False)
        print(result.stdout[-3500:], flush=True)
        after = inspect(child)
        archives = docker("ps", "-a", "--format", "{{.Names}}",
                          "--filter", "name=" + child + "-old-").stdout
        require(result.returncode != 0 and
                "conflicting options: hostname and the network mode" in result.stdout
                and after is None and child + "-old-" in archives,
                "Original v1.7.1 did not reproduce the exact Docker HTTP 400/"
                "stranded-archive bug. Inspect fixture fields before changing test.")
        print("PASS: Original v1.7.1 precisely reproduced the user-observed "
              "Ntfy create error and stranded archive.", flush=True)


def patched_stage(binary):
    print("===== PATCHED Freshdock real Docker regression =====", flush=True)
    with Fixture("patched") as fixture:
        parent_before = inspect(fixture.parent)["Id"]
        first = fixture.children[0]

        print("TEST 1: direct recreation of network-sharing child", flush=True)
        initial_id = inspect(first)["Id"]
        result = run([str(binary), "recreate", first], env=ci_env(), timeout=150)
        print(result.stdout[-700:], flush=True)
        require(inspect(first)["Id"] != initial_id,
                "Direct child update did not recreate container")
        fixture.assert_network()
        print("PASS: direct child recreation preserved network and image ref", flush=True)

        print("TEST 2: parent replacement reattaches BOTH children", flush=True)
        prior = {n: inspect(n)["Id"] for n in fixture.children}
        result = run([str(binary), "recreate", fixture.parent],
                     env=ci_env(), timeout=150)
        print(result.stdout[-700:], flush=True)
        require(inspect(fixture.parent)["Id"] != parent_before,
                "Parent replacement did not occur")
        require(all(inspect(n)["Id"] != prior[n] for n in fixture.children),
                "One or both dependents not recreated with parent")
        fixture.assert_network()
        print("PASS: both children reattached to new parent", flush=True)

        print("TEST 3: real scheduler automatically updates both child images",
              flush=True)
        old_image = inspect(first)["Image"]
        new_image = fixture.build("new")
        require(new_image != old_image, "Image did not change")
        fixture.start_daemon(binary)

        def have_update():
            try:
                fixture.assert_network()
                return all(inspect(n)["Image"] == new_image for n in fixture.children)
            except (RuntimeError, KeyError, TypeError):
                return False
        wait_for(have_update, deadline=140,
                 description="both auto-updated child containers")
        fixture.assert_network()
        print("PASS: scheduler updated BOTH children and retained tag refs",
              flush=True)

        print("TEST 4: force unhealthy release; verify automatic rollback",
              flush=True)
        good = {n: inspect(n)["Image"] for n in fixture.children}
        bad_image = fixture.build("bad")
        require(bad_image != new_image, "Bad release did not change image")
        wait_for(lambda: ("roll" in fixture.daemon_log().lower() and
                          all(healthy(inspect(n)) and
                              inspect(n)["Image"] == good[n]
                              for n in fixture.children)),
                 deadline=180, description="automatic healthy rollback")
        fixture.assert_network()
        print("PASS: unhealthy release rolled back without stranding clients",
              flush=True)
        # Note that a failed digest remains available and may be retried;
        # the test proves correct restoration for this run, not backoff policy.
        logs = fixture.daemon_log().lower()
        require("failed to re-attach" not in logs and
                "conflicting options" not in logs,
                "Scheduler logged namespace conflict/reattach failure")
        print("ALL PATCHED LIVE DOCKER TESTS PASSED", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--stage", choices=("original", "patched"), required=True)
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    require(os.environ.get("GITHUB_ACTIONS") == "true",
            "Test intentionally limited to disposable GitHub Actions runners")
    require(shutil.which("docker") and shutil.which("curl"),
            "Docker daemon and curl required")
    require(docker("info", check=False).returncode == 0, "Docker daemon unavailable")
    if args.stage == "original":
        original_stage(binary)
    else:
        patched_stage(binary)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
        sys.exit("FAIL: " + str(e))
