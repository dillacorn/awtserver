#!/usr/bin/env python3
"""Read-only OMV Watchtower health verification, independent of retired updaters.

The unattended 05:00 ET systemd timer invokes --verify --notify-on-failure.
Secrets exist only in /docker/watchtower-fork/alert_smtp.json (root 0600).
No container is ever created, stopped, restarted, or removed by this script.
"""
import argparse
from email.message import EmailMessage
import ipaddress
import json
import os
from pathlib import Path
import re
import smtplib
import socket
import ssl
import subprocess
import sys

HOST = "openmediavault"
ROOT = Path("/docker/watchtower-fork")
SCHEDULE = "0 45 2 * * *"
VPN = frozenset({"gluetun", "transmission", "qbittorrent", "mullvad-browser"})
EXPECTED = frozenset({
    "app-dockge", "app-flame", "app-ntfy", "audiobookshelf", "brave",
    "freshrss", "gluetun", "hbbr", "hbbs", "jellyfin", "jellyseerr",
    "mariadb_jellyseerr", "mullvad-browser", "navidrome",
    "tailscale-audiobookshelf", "tailscale-brave", "tailscale-dockge",
    "tailscale-flame", "tailscale-freshrss", "tailscale-jellyfin",
    "tailscale-jellyseerr", "tailscale-navidrome", "tailscale-ntfy",
    "transmission",
})

# All-or-nothing original 24 and current 28 target policies.
# Only deployed applications are eligible; no second Transmission by default.
ADDITIONAL = frozenset({"amutorrent", "prowlarr", "trawl", "tailscale-amutorrent"})
EXPANDED = EXPECTED | ADDITIONAL
# A separate qBittorrent Tailscale identity remains alongside the old
# Transmission machine during a reversible migration. The old Tailscale
# machine is retired only after independent checks and user approval.
QBIT_TRANSITION = (EXPANDED - {"transmission"}) | {
    "qbittorrent", "tailscale-qbittorrent",
}
QBIT_FINAL = QBIT_TRANSITION - {"tailscale-transmission"}
APPROVED = frozenset({EXPECTED, EXPANDED, frozenset(QBIT_TRANSITION),
                      frozenset(QBIT_FINAL)})
GLUETUN_CLIENTS = frozenset({
    "transmission", "qbittorrent", "mullvad-browser", "amutorrent",
    "prowlarr", "trawl",
})


class Stop(RuntimeError):
    pass


def need(ok, reason):
    if not ok:
        raise Stop(reason)


def docker_inventory():
    try:
        ids = subprocess.run(
            ["docker", "ps", "-aq"], check=True, text=True,
            capture_output=True, timeout=25).stdout.split()
        if not ids:
            raise Stop("Docker container inventory is empty")
        inspected = subprocess.run(
            ["docker", "inspect", *ids], check=True, text=True,
            capture_output=True, timeout=75)
        return {c["Name"].lstrip("/"): c for c in json.loads(inspected.stdout)}
    except (subprocess.SubprocessError, OSError, ValueError):
        raise Stop("Docker inventory unavailable") from None


def labels(c):
    return c.get("Config", {}).get("Labels") or {}


def state(c):
    return c["State"]["Status"]


def read_targets(root=ROOT):
    path = root / "targets.json"
    need(path.is_file() and not path.is_symlink(), "Private Watchtower target manifest missing")
    need(path.stat().st_mode & 0o077 == 0, "Target manifest permissions too open")
    manifest = json.loads(path.read_text())
    names = manifest.get("container_names")
    need(isinstance(names, list) and len(names) in (24, 28, 29) and
         all(isinstance(n, str) and
             re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", n) for n in names) and
         frozenset(names) in APPROVED and
         manifest.get("schedule") == SCHEDULE,
         "Watchtower manifest does not match an approved exact target policy")
    return names


def read_smtp(root=ROOT):
    path = root / "alert_smtp.json"
    need(path.is_file() and not path.is_symlink(), "Private Watchtower SMTP alert config missing")
    need(path.stat().st_mode & 0o077 == 0, "SMTP alert config permissions too open")
    cfg = json.loads(path.read_text())
    need(isinstance(cfg, dict) and
         (cfg.get("tls"), cfg.get("port")) in
         (("starttls", 587), ("implicit", 465)),
         "Invalid SMTP TLS policy")
    for field in ("host", "username", "password", "from", "to"):
        need(cfg.get(field), f"SMTP {field} missing")
    need(isinstance(cfg["to"], list) and
         all(isinstance(x, str) and x for x in cfg["to"]),
         "SMTP recipient list invalid")
    need(re.fullmatch(r"[A-Za-z0-9.-]+", cfg["host"]),
         "SMTP hostname invalid")
    return cfg


def send_tls(cfg, subject, body):
    email = EmailMessage()
    email["From"] = cfg["from"]
    email["To"] = ", ".join(cfg["to"])
    email["Subject"] = subject
    email.set_content(body)
    try:
        context = ssl.create_default_context()
        if cfg["tls"] == "implicit":
            client = smtplib.SMTP_SSL(cfg["host"], cfg["port"],
                                      timeout=30, context=context)
        else:
            client = smtplib.SMTP(cfg["host"], cfg["port"], timeout=30)
        with client:
            if cfg["tls"] == "starttls":
                client.ehlo()
                need(client.has_extn("starttls"),
                     "SMTP does not support required STARTTLS")
                client.starttls(context=context)
                client.ehlo()
            client.login(cfg["username"], cfg["password"])
            client.send_message(email)
    except (OSError, smtplib.SMTPException, ValueError):
        raise Stop("Encrypted SMTP notification could not be sent") from None


def check_compose(c, name):
    meta = labels(c)
    need(meta.get("com.docker.compose.project") and
         meta.get("com.docker.compose.service"),
         f"{name}: missing Compose project/service identity")
    paths = meta.get("com.docker.compose.project.config_files", "")
    need(paths, f"{name}: original Compose files unspecified")
    for value in paths.split(","):
        source = Path(value.strip())
        need(source.is_absolute() and source.is_file(),
             f"{name}: original Compose file unavailable")
    workdir = meta.get("com.docker.compose.project.working_dir", "")
    need(workdir and Path(workdir).is_dir(),
         f"{name}: original Compose working directory missing")


def check_vpn(fleet):
    parent = fleet["gluetun"]
    need((parent["State"].get("Health") or {}).get("Status") == "healthy",
         "Gluetun VPN parent not healthy")
    host = parent["HostConfig"]
    caps = {str(x).upper().removeprefix("CAP_") for x in host.get("CapAdd") or []}
    need("NET_ADMIN" in caps and host.get("NetworkMode") != "host",
         "Gluetun cannot enforce an isolated network firewall")
    env = dict(x.split("=", 1) for x in
               (parent["Config"].get("Env") or []) if "=" in x)
    local = [ipaddress.ip_network(s) for s in (
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
        "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
        "fc00::/7", "fe80::/10", "::1/128"
    )]
    for item in filter(None, (x.strip() for x in
                              env.get("FIREWALL_OUTBOUND_SUBNETS", "").split(","))):
        try:
            network = ipaddress.ip_network(item, strict=False)
        except ValueError:
            raise Stop("Invalid Gluetun firewall outbound subnet") from None
        need(any(network.subnet_of(allowed) for allowed in local
                 if network.version == allowed.version),
             "Gluetun permits an unapproved public firewall bypass")
    for name in sorted(GLUETUN_CLIENTS & fleet.keys()):
        child = fleet[name]
        need(child["HostConfig"].get("NetworkMode") == "container:" + parent["Id"],
             f"{name}: not attached to the current Gluetun namespace")
        config = child["HostConfig"]
        child_caps = {str(x).upper().removeprefix("CAP_")
                      for x in config.get("CapAdd") or []}
        need("NET_ADMIN" not in child_caps and not config.get("Privileged", False),
             f"{name}: can modify the shared VPN firewall")
    for name, item in fleet.items():
        if item["HostConfig"].get("NetworkMode") == "container:" + parent["Id"]:
            need(name in GLUETUN_CLIENTS,
                 f"Unapproved additional Gluetun namespace user: {name}")


def check_dependencies(fleet, names):
    included = set(names)
    for parent_name in names:
        parent = fleet[parent_name]
        for name, child in fleet.items():
            if child["HostConfig"].get("NetworkMode") != "container:" + parent["Id"]:
                continue
            if name not in included:
                # A stopped Transmission container may be retained briefly for
                # rollback during the qBittorrent transition. It cannot be
                # running, monitored, or automatically updated in that state.
                # Gluetun still must be the same parent for this exact child.
                retiring = (
                    parent_name == "gluetun" and
                    name == "transmission" and
                    state(child) == "exited" and
                    "qbittorrent" in included and
                    child["HostConfig"].get("NetworkMode") ==
                    "container:" + parent["Id"]
                )
                need(retiring,
                     f"{parent_name}: excluded dependent {name} ({state(child)})")
                continue
            meta = labels(child)
            explicit = meta.get("com.centurylinklabs.watchtower.depends-on", "")
            compose_dep = meta.get("com.docker.compose.depends_on", "")
            if explicit:
                refs = {x.strip().lstrip("/") for x in explicit.split(",")}
                need(parent_name in refs,
                     f"{name}: dependency label hides network parent")
            elif compose_dep:
                refs = {x.split(":", 1)[0].strip()
                        for x in compose_dep.split(",")}
                need(labels(parent).get("com.docker.compose.project") ==
                     labels(child).get("com.docker.compose.project") and
                     labels(parent).get("com.docker.compose.service") in refs,
                     f"{name}: Compose dependency hides network parent")


def verify_runtime(fleet, names):
    need(len(names) == len(set(names)) and frozenset(names) in APPROVED,
         "Expected approved Watchtower services are not enrolled")
    updater = fleet.get("watchtower")
    need(updater and state(updater) == "running", "Watchtower daemon not running")
    cmd = updater.get("Config", {}).get("Cmd") or []
    need(cmd == ["--schedule", SCHEDULE, "--no-startup-message", *names],
         "Watchtower schedule/positional allowlist changed")
    need(updater["Config"]["Image"] == "nickfedor/watchtower:1.23.1",
         "Unexpected Watchtower image")
    for name in names:
        c = fleet.get(name)
        need(c is not None, f"{name}: application container missing")
        need(state(c) == "running", f"{name}: application not running")
        health = (c["State"].get("Health") or {}).get("Status")
        need(health not in ("unhealthy",), f"{name}: unhealthy")
        check_compose(c, name)
        network = c["HostConfig"].get("NetworkMode") or ""
        if network.startswith("container:"):
            need(any(other["Id"] == network.split(":", 1)[1] and
                     state(other) == "running" for other in fleet.values()),
                 f"{name}: stale/unavailable network parent")
        meta = labels(c)
        need(meta.get("com.centurylinklabs.watchtower.enable", "").lower() != "false",
             f"{name}: Watchtower opted out")
        need(meta.get("com.centurylinklabs.watchtower.monitor-only", "").lower() != "true",
             f"{name}: Watchtower monitor-only label")
    need("freshdock" not in fleet or state(fleet["freshdock"]) != "running",
         "Retired updater unexpectedly running")
    check_vpn(fleet)
    check_dependencies(fleet, names)
    return names


def verify_and_alert(notify):
    try:
        names = read_targets(ROOT)
        # Without an SMTP config, a failing alert cannot be delivered.
        read_smtp(ROOT)
        verify_runtime(docker_inventory(), names)
        print(f"PASS: independent Watchtower verifier; {len(names)} healthy targets")
    except (Stop, OSError, KeyError, ValueError, TypeError) as err:
        reason = str(err)
        print(f"FAIL: Watchtower verification: {reason}", file=sys.stderr)
        if notify:
            try:
                cfg = read_smtp(ROOT)
                send_tls(cfg, "OMV Watchtower: unattended update needs attention",
                         "Host: openmediavault\n"
                         "The Docker updater has an unsafe or unavailable state:\n"
                         + reason + "\nInspect the running services and Compose sources.\n")
                print("PASS: encrypted failure alert submitted")
            except (Stop, OSError, ValueError) as notify_error:
                print(f"FAIL: alert delivery: {notify_error}", file=sys.stderr)
        raise Stop("Watchtower verification failed") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--notify-on-failure", action="store_true")
    args = parser.parse_args()
    try:
        need(args.verify and
             (not args.notify_on_failure or args.verify),
             "Only --verify [--notify-on-failure] is supported")
        need(os.geteuid() == 0 and socket.gethostname() == HOST,
             "Verifier must run as root on openmediavault")
        verify_and_alert(args.notify_on_failure)
        return 0
    except (Stop, OSError, ValueError, KeyError, TypeError) as err:
        print(f"STOP: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
