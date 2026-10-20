#!/usr/bin/env python3
"""Guarded Freshdock -> Nicholas Fedor Watchtower migration on openmediavault.

Default: read-only --check. --apply starts ONLY a new updater daemon; it does
NOT recreate, update, stop, or restart any application, VPN, Tailscale sidecar,
database, or source Compose stack. Existing Freshdock must be STOPPED with
restart disabled. No global scan: explicit exact 24-container positional list.

This installer never removes /docker/freshdock or old Watchtower files.
A successful install is not proof of successful future unattended upgrades.
"""
import argparse
from datetime import datetime
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
import tomllib
from urllib.parse import quote, urlencode

HOST = "openmediavault"
ROOT = Path("/docker/watchtower-fork")
OLD_ROOT = Path("/docker/freshdock")
VERSION = "nickfedor/watchtower:1.23.1"
SCHEDULE = "0 45 2 * * *"
MODE_CRON = "45 2 * * *"
VPN = ("gluetun", "transmission", "mullvad-browser")
NIGHTLY_COUNT = 21
TOTAL_COUNT = NIGHTLY_COUNT + len(VPN)
SELECTOR = "__NO_PRODUCTION_TARGETS_WITHOUT_GUARDED_ENROLLMENT__"
VERIFY_TIMER = "watchtower-fork-verify.timer"
VERIFY_SERVICE = "watchtower-fork-verify.service"
UNITS = Path("/etc/systemd/system")


class Stop(RuntimeError):
    pass


def need(ok, reason):
    if not ok:
        raise Stop(reason)


def command(*args, timeout=50, check=True):
    try:
        p = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise Stop(f"{args[0]} unavailable or timed out") from None
    if check and p.returncode:
        raise Stop(f"{args[0]} {args[1]} failed (exit {p.returncode}; output suppressed)")
    return p


def docker(*args, **kwargs):
    return command("docker", *args, **kwargs)


def containers():
    ids = docker("ps", "-aq").stdout.split()
    return {
        c["Name"].lstrip("/"): c
        for c in json.loads(docker("inspect", *ids, timeout=75).stdout)
    } if ids else {}


def state(c):
    return c["State"]["Status"]


def label(c, key):
    return (c.get("Config", {}).get("Labels") or {}).get(key, "")


def compose_source_preflight(c, name):
    """Require actual existing Compose sources before allowing updates.

    Watchtower can remove the original container during a failed recreate.
    Without its original Compose file, recovery would be unnecessarily risky.
    """
    need(label(c, "com.docker.compose.project") and
         label(c, "com.docker.compose.service"),
         f"{name}: missing Compose project/service identity")
    paths = label(c, "com.docker.compose.project.config_files")
    need(paths, f"{name}: original Compose source paths unavailable")
    for raw in paths.split(","):
        source = Path(raw.strip())
        need(source.is_absolute() and source.is_file(),
             f"{name}: original Compose configuration file missing")
    working = label(c, "com.docker.compose.project.working_dir")
    need(working and Path(working).is_dir(),
         f"{name}: original Compose working directory missing")


def valid_parent(c, fleet):
    mode = c["HostConfig"].get("NetworkMode") or ""
    if not mode.startswith("container:"):
        return True
    expected = mode.split(":", 1)[1]
    return any(
        parent["Id"] == expected and state(parent) == "running"
        for parent in fleet.values()
    )


def vpn_firewall_preflight(fleet):
    """Fail closed on known ways clients could bypass Gluetun's firewall.

    This is a static runtime configuration audit, NOT a real VPN egress test.
    """
    gluetun = fleet["gluetun"]
    host = gluetun["HostConfig"]
    caps = {str(cap).upper().removeprefix("CAP_")
            for cap in (host.get("CapAdd") or [])}
    need("NET_ADMIN" in caps,
         "Gluetun lacks explicit NET_ADMIN needed for its kill switch")
    need(host.get("NetworkMode") != "host",
         "Gluetun must not operate in host network mode")
    env = dict(item.split("=", 1) for item in
               (gluetun["Config"].get("Env") or []) if "=" in item)
    outbound = env.get("FIREWALL_OUTBOUND_SUBNETS", "").strip()
    # Gluetun explicitly exempts these subnets from VPN routing/firewall.
    # Don't authorize routable public exceptions or a global bypass.
    local_ranges = [
        ipaddress.ip_network(value)
        for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                      "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
                      "fc00::/7", "fe80::/10", "::1/128")
    ]
    for item in filter(None, (x.strip() for x in outbound.split(","))):
        try:
            network = ipaddress.ip_network(item, strict=False)
        except ValueError:
            raise Stop("Invalid Gluetun outbound firewall subnet") from None
        need(any(network.subnet_of(allowed) for allowed in local_ranges
                 if network.version == allowed.version),
             "Gluetun firewall has an unapproved nonlocal outbound bypass")
    for name in ("transmission", "mullvad-browser"):
        host = fleet[name]["HostConfig"]
        caps = {str(cap).upper().removeprefix("CAP_")
                for cap in (host.get("CapAdd") or [])}
        need("NET_ADMIN" not in caps and not host.get("Privileged", False),
             f"{name}: VPN client can override the shared firewall")


def selection(fleet):
    enabled = sorted(
        n for n, c in fleet.items()
        if state(c) == "running" and
        label(c, "freshdock.enable").lower() == "true"
    )
    need(len(enabled) == NIGHTLY_COUNT,
         f"Freshdock selected live count changed: {len(enabled)} (expected 21)")
    for n in enabled:
        c = fleet[n]
        need(label(c, "freshdock.mode") == "nightly" and
             label(c, "freshdock.schedule") == MODE_CRON,
             f"{n}: unexpected Freshdock schedule/mode")
        compose_source_preflight(c, n)
        need(valid_parent(c, fleet),
             f"{n}: stale network parent")
    need(not set(VPN) & set(enabled),
         "VPN trio already in Freshdock selected set, unexpected prior migration")
    for n in VPN:
        need(n in fleet and state(fleet[n]) == "running",
             f"VPN container {n} missing/not running")
        compose_source_preflight(fleet[n], n)
    parent = fleet["gluetun"]
    need((parent["State"].get("Health") or {}).get("Status") == "healthy",
         "Gluetun VPN parent not healthy")
    for n in ("transmission", "mullvad-browser"):
        need(fleet[n]["HostConfig"]["NetworkMode"] == "container:" + parent["Id"],
             f"{n} does not share the CURRENT Gluetun network namespace")
    vpn_firewall_preflight(fleet)
    # A stopped dependent may be started later, still referencing the old
    # parent ID after replacement. Block unknown clients regardless of state.
    for n, c in fleet.items():
        if c["HostConfig"]["NetworkMode"] == "container:" + parent["Id"]:
            need(n in ("transmission", "mullvad-browser"),
                 f"Unreviewed additional Gluetun network client: {n}")
    targets = tuple(sorted(set(enabled) | set(VPN)))
    need(not {"vaultwarden", "nginx-vaultwarden"} & set(targets),
         "Legacy Vaultwarden services must remain explicitly excluded")
    need(len(targets) == TOTAL_COUNT, "Allowlist must contain exactly 24 targets")
    watched = set(targets)
    for n in targets:
        need(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", n) is not None,
             f"Unsafe name in target list: {n!r}")
        need(label(fleet[n], "com.centurylinklabs.watchtower.enable").lower()
             != "false", f"{n}: explicit legacy Watchtower opt-out")
        need(label(fleet[n], "com.centurylinklabs.watchtower.monitor-only").lower()
             != "true", f"{n}: legacy Watchtower monitor-only label")
    # 1.23.1 live Docker canary reproduced stale network dependents when
    # only the parent was targeted. The parent and EVERY running dependent
    # must appear on the same exact Watchtower update allowlist.
    for name in targets:
        parent = fleet[name]
        for child_name, child in fleet.items():
            if child["HostConfig"].get("NetworkMode") != "container:" + parent["Id"]:
                continue
            need(child_name in watched,
                 f"Unsafe partial network group: {name} selected but "
                 f"dependent {child_name} excluded (state={state(child)})")
            # In v1.23.1, an explicit Watchtower dependency label or
            # Compose depends_on label OVERRIDES HostConfig.NetworkMode
            # dependency detection. Require a reference to the actual
            # parent, or the fork may restart the child in the wrong order.
            explicit = label(child, "com.centurylinklabs.watchtower.depends-on")
            compose_dep = label(child, "com.docker.compose.depends_on")
            if explicit:
                refs = {x.strip().lstrip("/") for x in explicit.split(",")}
                need(name in refs,
                     f"{child_name}: Watchtower depends-on omits network parent {name}")
            elif compose_dep:
                refs = {x.split(":", 1)[0].strip()
                        for x in compose_dep.split(",")}
                need(label(parent, "com.docker.compose.project") ==
                     label(child, "com.docker.compose.project") and
                     label(parent, "com.docker.compose.service") in refs,
                     f"{child_name}: Compose depends_on omits network parent {name}")
    return targets


def smtp_data(path):
    need(path.is_file(), "Freshdock private SMTP TOML is missing")
    need(path.stat().st_mode & 0o077 == 0,
         "Freshdock SMTP TOML permissions too open")
    with path.open("rb") as file:
        data = tomllib.load(file)
    v = data.get("notifications", {}).get("email", {})
    need(v.get("type") == "smtp" and
         v.get("tls") in ("starttls", "implicit") and
         str(v.get("port")) in ("587", "465"),
         "SMTP config transport is not one of the audited TLS modes")
    need((v["tls"], int(v["port"])) in (("starttls", 587), ("implicit", 465)),
         "SMTP port and TLS mode inconsistent")
    for key in ("host", "username", "password", "from", "to"):
        need(v.get(key), f"Missing SMTP {key} field")
    need(isinstance(v["to"], list) and
         all(isinstance(x, str) and x for x in v["to"]),
         "SMTP recipients not configured")
    host = v["host"]
    need(re.fullmatch(r"[A-Za-z0-9.-]+", host) is not None,
         "Unexpected SMTP hostname syntax")
    need(all("\n" not in str(x) for x in (v["username"], v["password"], v["from"])),
         "Unexpected multiline SMTP field")
    return v


def smtp_url(cfg):
    mode = "ExplicitTLS" if cfg["tls"] == "starttls" else "ImplicitTLS"
    start = "yes" if cfg["tls"] == "starttls" else "no"
    params = urlencode({
        "fromaddress": cfg["from"],
        "toaddresses": ",".join(cfg["to"]),
        "encryption": mode,
        "usestarttls": start,
        # Shoutrrr otherwise permits a plaintext fallback when STARTTLS is
        # unavailable. Never downgrade the private SMTP credentials.
        "requirestarttls": start,
        "timeout": "30s",
    })
    return (
        "smtp://"
        + quote(cfg["username"], safe="") + ":"
        + quote(cfg["password"], safe="") + "@"
        + cfg["host"] + ":" + str(cfg["port"]) + "/?" + params
    )


def compose(targets):
    # JSON syntax is YAML-compatible and understood by Docker Compose.
    # The command is an exact positional allowlist. No global discovery.
    return {
        "services": {
            "watchtower": {
                "image": VERSION,
                "container_name": "watchtower",
                "restart": "unless-stopped",
                "command": [
                    "--schedule", SCHEDULE,
                    "--no-startup-message", *targets,
                ],
                "environment": {
                    "TZ": "America/New_York",
                    "WATCHTOWER_CLEANUP": "false",
                    "WATCHTOWER_NOTIFICATION_URL": "/run/secrets/notification_url",
                },
                "volumes": [
                    "/var/run/docker.sock:/var/run/docker.sock",
                    "./notification_url:/run/secrets/notification_url:ro",
                ],
                "labels": {
                    "com.centurylinklabs.watchtower.enable": "false",
                },
            }
        }
    }


def preflight():
    need(os.geteuid() == 0 and socket.gethostname() == HOST,
         "Must run as root on the expected openmediavault host")
    now = datetime.now().strftime("%H%M")
    need(not ("0215" <= now <= "0445"),
         "Do not change updater during nightly SnapRAID/update windows")
    need(docker("compose", "version", check=False).returncode == 0,
         "Docker Compose plugin missing")
    need(docker("info", check=False).returncode == 0,
         "Docker daemon unavailable")
    need(command("pgrep", "-x", "snapraid", check=False).returncode != 0,
         "SnapRAID currently running; leave disks alone")
    fleet = containers()
    need("watchtower" not in fleet, "Existing Watchtower container already present")
    old = fleet.get("freshdock")
    need(old is not None and
         old["Config"]["Image"] == "ghcr.io/turbootzz/freshdock:1.7.1" and
         state(old) != "running" and
         old["HostConfig"]["RestartPolicy"]["Name"] == "no",
         "Original Freshdock must remain stopped with restart=no")
    need(not ROOT.exists(),
         "Existing /docker/watchtower-fork path; refuse overwriting")
    need(command("systemctl", "--version", check=False).returncode == 0,
         "systemd required for unattended post-update verification")
    need(command("systemd-analyze", "calendar",
                 "*-*-* 05:00:00 America/New_York",
                 check=False).returncode == 0,
         "Installed systemd does not understand the verifier timer")
    need(not any((UNITS / name).exists() or (UNITS / name).is_symlink()
                 for name in (VERIFY_TIMER, VERIFY_SERVICE)),
         "Existing verifier systemd unit; refuse overwriting")
    need(all(not n.endswith("-old") and "-old-" not in n
             for n in fleet if state(fleet[n]) == "running"),
         "A running stale archived container requires review")
    targets = selection(fleet)
    mail = smtp_data(OLD_ROOT / "freshdock.toml")
    source = OLD_ROOT / "selected.json"
    need(source.is_file(), "Freshdock selected.json provenance missing")
    saved = json.loads(source.read_text())
    need(isinstance(saved.get("container_names"), list),
         "Previous enrolled allowlist provenance invalid")
    # This file is the original 26-target WUD snapshot, not necessarily the
    # active Freshdock selected set. We require current enrollment to be a
    # subset of the pre-migration selection.
    provenance = set(saved["container_names"])
    need(set(targets) <= provenance,
         "Newly selected targets are outside the original authorized allowlist")
    return fleet, targets, mail


def smtp_send(cfg, subject, body):
    """Send only with verified TLS, never reporting credentials on failure."""
    message = EmailMessage()
    message["From"] = cfg["from"]
    message["To"] = ", ".join(cfg["to"])
    message["Subject"] = subject
    message.set_content(body)
    try:
        context = ssl.create_default_context()
        if cfg["tls"] == "implicit":
            client = smtplib.SMTP_SSL(cfg["host"], int(cfg["port"]),
                                      timeout=30, context=context)
        else:
            client = smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=30)
        with client:
            if cfg["tls"] == "starttls":
                client.ehlo()
                need(client.has_extn("starttls"),
                     "SMTP refuses STARTTLS; email not sent")
                client.starttls(context=context)
                client.ehlo()
            client.login(cfg["username"], cfg["password"])
            client.send_message(message)
    except (OSError, smtplib.SMTPException, ValueError):
        raise Stop("Encrypted SMTP delivery failed (details suppressed)") from None


def verify_runtime(fleet, manifest):
    """Read-only validation after unattended updates, independent of status logs."""
    names = manifest.get("container_names")
    need(isinstance(names, list) and len(names) == TOTAL_COUNT and
         len(set(names)) == TOTAL_COUNT and set(VPN) <= set(names),
         "Private installed Watchtower allowlist invalid")
    selected = selection(fleet)
    need(set(selected) == set(names), "Current enrollment differs from installed allowlist")
    updater = fleet.get("watchtower")
    need(updater and state(updater) == "running",
         "Watchtower updater not running")
    cmd = updater["Config"].get("Cmd") or []
    need(cmd[:2] == ["--schedule", SCHEDULE] and
         cmd[-len(names):] == names,
         "Updater schedule or target list drifted")
    for name in names:
        c = fleet[name]
        need(state(c) == "running", f"{name}: not running after nightly update")
        health = (c["State"].get("Health") or {}).get("Status")
        need(health not in ("unhealthy",),
             f"{name}: unhealthy after nightly update")
    need("freshdock" in fleet and state(fleet["freshdock"]) != "running" and
         fleet["freshdock"]["HostConfig"]["RestartPolicy"]["Name"] == "no",
         "Defective Freshdock is unexpectedly enabled")
    return names


def verify_and_alert(notify):
    try:
        need(ROOT.is_dir(), "No installed Watchtower directory")
        source = ROOT / "targets.json"
        need(source.is_file(), "Installed target list unavailable")
        manifest = json.loads(source.read_text())
        names = verify_runtime(containers(), manifest)
        print(f"PASS: {len(names)} target containers healthy/running; "
              "network dependencies and updater verified")
    except (Stop, OSError, KeyError, ValueError, TypeError) as exc:
        # Errors below contain only container names/configuration descriptors,
        # never SMTP passwords or Docker inspect environments.
        reason = str(exc)
        print(f"FAIL: Watchtower unattended verification: {reason}",
              file=sys.stderr)
        if notify:
            mail = smtp_data(OLD_ROOT / "freshdock.toml")
            smtp_send(mail, "OMV Watchtower: unattended update needs attention",
                      "Host: openmediavault\n"
                      "The nightly Docker updater left an unsafe state:\n"
                      f"{reason}\n"
                      "Do not restart the defective Freshdock image. "
                      "Inspect Docker state before retrying updates.\n")
            print("PASS: encrypted failure alert delivered", flush=True)
        raise Stop("Unattended Watchtower verification failed") from None


def verifier_units():
    # The timer does not update containers, only audits and emails on failure.
    service = """[Unit]
Description=Check OMV Watchtower containers after nightly updates
Wants=docker.service
After=docker.service

[Service]
Type=oneshot
User=root
UMask=0077
ExecStart=/usr/bin/python3 /docker/watchtower-fork/replace_freshdock.py --verify --notify-on-failure
"""
    timer = """[Unit]
Description=Audit Docker updater following nightly maintenance

[Timer]
OnCalendar=*-*-* 05:00:00 America/New_York
Persistent=true
Unit=watchtower-fork-verify.service

[Install]
WantedBy=timers.target
"""
    return service, timer


def safe_write(path, text, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w") as out:
        out.write(text)
        out.flush()
        os.fsync(out.fileno())
    path.chmod(mode)


def apply(before, targets, mail):
    need(not ROOT.exists(), "Destination already exists; no overwrite")
    # Stage all secret-bearing paths root-only before pulling image.
    ROOT.mkdir(parents=False, mode=0o700)
    ROOT.chmod(0o700)
    safe_write(ROOT / "notification_url", smtp_url(mail) + "\n")
    safe_write(ROOT / "compose.yml", json.dumps(compose(targets), indent=2) + "\n")
    safe_write(ROOT / "targets.json", json.dumps({
        "source": "Freshdock live enabled Compose labels; WUD selection audited",
        "schedule": SCHEDULE,
        "container_names": targets
    }, indent=2) + "\n")
    safe_write(ROOT / "replace_freshdock.py",
               Path(__file__).read_text(), mode=0o700)
    service, timer = verifier_units()
    safe_write(UNITS / VERIFY_SERVICE, service, mode=0o644)
    safe_write(UNITS / VERIFY_TIMER, timer, mode=0o644)
    command("systemd-analyze", "verify", str(UNITS / VERIFY_SERVICE),
            str(UNITS / VERIFY_TIMER))
    # Verify real SMTP delivery before enabling unattended updates.
    smtp_send(mail, "OMV Watchtower: verified encrypted notifications",
              "Encrypted SMTP has been verified for the Watchtower replacement.\n"
              "Freshdock remains stopped. This is not an application update.\n")
    target_path = ROOT / "compose.yml"
    cp = ["docker", "compose", "-p", "watchtower-fork",
          "--project-directory", str(ROOT), "-f", str(target_path)]
    command(*cp, "config", "--quiet")
    docker("pull", VERSION, timeout=300)
    print("PASS: Watchtower image pulled; private config checked", flush=True)
    # Refuse any container-name or state change between inventory and creation.
    live = containers()
    for name, original in before.items():
        need(name in live and live[name]["Id"] == original["Id"] and
             state(live[name]) == state(original) and
             live[name]["State"]["Paused"] == original["State"]["Paused"],
             f"Fleet changed during preparation: {name}")
    need("watchtower" not in live, "Watchtower name acquired by another process")
    try:
        command(*cp, "up", "-d", "--no-deps", "--no-build",
                "--pull", "never", "watchtower", timeout=110)
        live = containers()
        updater = live.get("watchtower")
        need(updater and state(updater) == "running" and
             updater["Config"]["Image"] == VERSION,
             "Watchtower daemon not running as expected")
        need(updater["Config"]["Cmd"][-len(targets):] == list(targets),
             "Runtime updater target allowlist differs")
        need(updater["Config"]["Cmd"][:2] == ["--schedule", SCHEDULE],
             "Runtime updater schedule mismatch")
        for name, original in before.items():
            now = live.get(name)
            need(now and now["Id"] == original["Id"] and
                 state(now) == state(original) and
                 now["State"]["Paused"] == original["State"]["Paused"],
                 f"Application unexpectedly changed during install: {name}")
        print("PASS: Watchtower running; 24 exact targets, 02:45 ET cron", flush=True)
        print("PASS: All existing containers unchanged", flush=True)
        command("systemctl", "daemon-reload")
        command("systemctl", "enable", "--now", VERIFY_TIMER)
        need(command("systemctl", "is-enabled", VERIFY_TIMER,
                     check=False).returncode == 0,
             "Unattended safety verification timer was not enabled")
        print("PASS: encrypted mail verified; next-day health alert enabled", flush=True)
        print("NOTE: No application update triggered; live nightly behavior still needs observation")
    except Exception:
        # Prevent an unsuccessful daemon install from ever running unattended.
        docker("update", "--restart=no", "watchtower", check=False)
        docker("stop", "--time", "20", "watchtower", check=False, timeout=35)
        command("systemctl", "disable", "--now", VERIFY_TIMER, check=False)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="install and start new updater after strict preflight")
    parser.add_argument("--verify", action="store_true",
                        help="read-only check of an installed updater and its targets")
    parser.add_argument("--notify-on-failure", action="store_true",
                        help="send encrypted SMTP alert for a failed --verify")
    args = parser.parse_args()
    try:
        need(not args.notify_on_failure or args.verify,
             "--notify-on-failure requires --verify")
        if args.verify:
            need(os.geteuid() == 0 and socket.gethostname() == HOST,
                 "Verifier must run as root on openmediavault")
            verify_and_alert(args.notify_on_failure)
            return 0
        before, targets, mail = preflight()
        print(f"PASS: {HOST}; original Freshdock stopped and restart disabled")
        print(f"PASS: {len(targets)} selected services; Gluetun and clients verified")
        print("PASS: private SMTP STARTTLS/implicit TLS fields available")
        print("PASS: cron 02:45 America/New_York; no application recreation")
        print("Selected: " + ", ".join(targets))
        if args.apply:
            apply(before, targets, mail)
        else:
            print("READ-ONLY PASS. No changes; --apply requires CI approval.")
        return 0
    except (Stop, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
