#!/usr/bin/env python3
"""GitHub-hosted only: real Gluetun fail-closed update with disposable VPN clients.

Uses a deliberately unreachable TEST-NET WireGuard endpoint and generated test
keys. No production Docker hosts, VPN accounts, tokens or SMTP settings.
A successful result is proof only of no-tunnel isolation in this CI scenario,
NOT proof of absence of transient leaks with a live authenticated VPN.
"""
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import uuid

WATCHTOWER = "nickfedor/watchtower:1.23.1"
GLUETUN_OLD = "qmcgaw/gluetun:v3.40.4"
GLUETUN_NEW = "qmcgaw/gluetun:v3.41.3"
CLIENT = "alpine:3.20.0"
EGRESS = "1.1.1.1"


def run(*args, timeout=150, check=True):
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, timeout=timeout)
    if check and proc.returncode:
        raise RuntimeError(f"{args[:3]} failed: {proc.stdout[-2200:]}")
    return proc


def docker(*args, **kwargs):
    return run("docker", *args, **kwargs)


def ensure(value, message):
    if not value:
        raise RuntimeError(message)


def inspect(name):
    result = docker("inspect", "--type", "container", name, check=False)
    return json.loads(result.stdout)[0] if result.returncode == 0 else None


def isolated(name):
    probe = docker("exec", name, "sh", "-c",
                   f"nc -z -w 3 {EGRESS} 443", timeout=15, check=False)
    ensure(probe.returncode != 0,
           f"VPN EGRESS LEAK: {name} reached {EGRESS}:443 without a VPN tunnel")


def main():
    ensure(os.environ.get("GITHUB_ACTIONS") == "true",
           "This test is only permitted on disposable GitHub Actions runners")
    ensure(Path("/dev/net/tun").exists(),
           "GitHub runner lacks /dev/net/tun; cannot validate actual Gluetun")
    docker("pull", WATCHTOWER, timeout=300)
    docker("pull", GLUETUN_OLD, timeout=300)
    docker("pull", GLUETUN_NEW, timeout=300)
    docker("pull", CLIENT, timeout=300)
    new_image = docker("image", "inspect", GLUETUN_NEW, "--format",
                       "{{.Id}}").stdout.strip()
    old_image = docker("image", "inspect", GLUETUN_OLD, "--format",
                       "{{.Id}}").stdout.strip()
    ensure(new_image != old_image, "Old and new Gluetun images are identical")
    # Control: demonstrate internet access is possible outside the VPN.
    control = docker("run", "--rm", CLIENT, "sh", "-c",
                     f"nc -z -w 5 {EGRESS} 443", timeout=30, check=False)
    ensure(control.returncode == 0,
           "Runner network baseline unreachable; isolation proof inconclusive")
    with tempfile.TemporaryDirectory(prefix="wt-gluetun-ci-") as temporary:
        token = "wtvpn" + uuid.uuid4().hex[:9]
        parent = token + "-gluetun"
        clients = [token + "-transmission", token + "-browser"]
        config = Path(temporary) / "compose.yml"
        # No real VPN connection can be established: RFC 5737 TEST-NET-3 endpoint.
        private_key = base64.b64encode(secrets.token_bytes(32)).decode()
        peer_key = base64.b64encode(secrets.token_bytes(32)).decode()
        config.write_text(f"""services:
  gluetun:
    image: {GLUETUN_NEW}
    container_name: {parent}
    cap_add: [NET_ADMIN]
    devices: ["/dev/net/tun:/dev/net/tun"]
    restart: "no"
    environment:
      VPN_SERVICE_PROVIDER: custom
      VPN_TYPE: wireguard
      VPN_ENDPOINT_IP: 203.0.113.99
      VPN_ENDPOINT_PORT: "51820"
      WIREGUARD_PRIVATE_KEY: "{private_key}"
      WIREGUARD_PUBLIC_KEY: "{peer_key}"
      WIREGUARD_ADDRESSES: "10.64.222.21/32"
  transmission:
    image: {CLIENT}
    container_name: {clients[0]}
    command: ["sleep", "3600"]
    network_mode: service:gluetun
    depends_on: [gluetun]
    restart: "no"
  browser:
    image: {CLIENT}
    container_name: {clients[1]}
    command: ["sleep", "3600"]
    network_mode: service:gluetun
    depends_on: [gluetun]
    restart: "no"
""")
        cp = ["docker", "compose", "-p", token, "-f", str(config)]
        docker("tag", GLUETUN_OLD, GLUETUN_NEW)
        try:
            run(*cp, "up", "-d", "--no-build", "--pull", "never", timeout=150)
            time.sleep(5)
            old_parent = inspect(parent)
            ensure(old_parent and old_parent["State"]["Running"],
                   "Fake VPN parent failed to stay running")
            old_ids = {name: inspect(name)["Id"] for name in clients}
            for name in clients:
                ensure(inspect(name) and inspect(name)["State"]["Running"],
                       f"{name} was not running before update")
                isolated(name)
            ensure((old_parent["State"].get("Health") or {}).get("Status") !=
                   "healthy", "Impossible VPN unexpectedly reported healthy")
            print("PASS: disconnected Gluetun blocks both dependent clients",
                  flush=True)
            wt = docker("run", "--rm", "--name", token + "-watchtower",
                        "-v", "/var/run/docker.sock:/var/run/docker.sock",
                        WATCHTOWER, "--run-once", "--no-startup-message",
                        "--stop-timeout", "3s", parent, *clients,
                        timeout=260, check=False)
            print("===== Watchtower fake VPN update log =====", flush=True)
            # Avoid logging Gluetun container environment or generated keys.
            print(wt.stdout[-5500:], flush=True)
            ensure(wt.returncode == 0, "Watchtower fake VPN update failed")
            newer = inspect(parent)
            ensure(newer and newer["State"]["Running"] and
                   newer["Image"] == new_image and
                   newer["Id"] != old_parent["Id"],
                   "Real Gluetun parent was not updated")
            for name in clients:
                current = inspect(name)
                ensure(current and current["State"]["Running"] and
                       current["Id"] != old_ids[name],
                       f"{name}: dependent not restarted")
                ensure(current["HostConfig"]["NetworkMode"] ==
                       "container:" + newer["Id"],
                       f"{name}: stale network namespace after VPN parent update")
                for attempt in range(4):
                    isolated(name)
                    time.sleep(1)
            ensure((newer["State"].get("Health") or {}).get("Status") !=
                   "healthy", "Invalid VPN became unexpectedly healthy")
            print("PASS: new Gluetun and both dependents reattached; "
                  "no outbound TCP through failed VPN", flush=True)
        finally:
            run(*cp, "down", "--remove-orphans", "--timeout", "8",
                timeout=100, check=False)
            # Only restore the disposable runner's mutable image tag.
            docker("pull", GLUETUN_NEW, timeout=300, check=False)
            print("Disposed fake VPN stack", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError) as e:
        sys.exit(f"FAIL: {e}")
