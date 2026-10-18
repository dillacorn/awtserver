#!/usr/bin/env python3
"""Guarded WUD -> Freshdock daemon switch on openmediavault.

--check is read-only. --apply stages private SMTP configuration and replaces only
the WUD daemon. All production app containers, volumes, networks, and Compose
files are untouched. Applications remain UNENROLLED until a separate approval/
validated label migration. Do not mistake daemon installation for full cutover.
"""
import argparse
from datetime import datetime
import json
import os
import re
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path("/docker/freshdock")
WUD_DIR = Path("/docker/wud")
IMAGE = "ghcr.io/turbootzz/freshdock:1.7.1"
EXPECTED_CRON = "45 2 * * *"
REQUIRED = {
    "host": "WUD_TRIGGER_SMTP_LEGACY_HOST",
    "port": "WUD_TRIGGER_SMTP_LEGACY_PORT",
    "username": "WUD_TRIGGER_SMTP_LEGACY_USER",
    "password": "WUD_TRIGGER_SMTP_LEGACY_PASS",
    "from": "WUD_TRIGGER_SMTP_LEGACY_FROM_ADDRESS",
    "to": "WUD_TRIGGER_SMTP_LEGACY_TO",
}

class Refused(RuntimeError):
    pass

def need(ok, reason):
    if not ok:
        raise Refused(reason)

def call(args, *, seconds=45, check=True):
    try:
        p = subprocess.run(args, text=True, capture_output=True, timeout=seconds)
    except (subprocess.TimeoutExpired, OSError) as e:
        raise Refused(f"{args[0]} unavailable or timed out ({type(e).__name__})") from None
    if check and p.returncode:
        raise Refused(f"{args[0]} failed (code {p.returncode}); no sensitive output printed")
    return p

def docker(*args, seconds=45, check=True):
    return call(["docker", *args], seconds=seconds, check=check)

def find(name):
    p = docker("inspect", "--type", "container", name, check=False)
    if p.returncode:
        return None
    data = json.loads(p.stdout)
    need(len(data) == 1 and data[0]["Name"] == "/" + name,
         f"{name}: container identity mismatch")
    return data[0]

def envdict(container):
    return dict(x.split("=", 1) for x in container["Config"]["Env"] if "=" in x)

def assert_live_state():
    need(os.geteuid() == 0, "Must run as root")
    need(socket.gethostname() == "openmediavault", "Wrong host")
    need(shutil.which("docker") is not None, "Docker missing")
    need(docker("compose", "version", check=False).returncode == 0, "Docker Compose missing")
    now = datetime.now().strftime("%H%M")
    need(not ("0215" <= now <= "0445"), "Scheduled update window; stop")
    wud = find("wud")
    need(wud is not None, "WUD missing; inspect existing migration state")
    need(find("freshdock") is None, "Freshdock already exists; do not overwrite")
    labels = wud["Config"].get("Labels") or {}
    need(labels.get("com.docker.compose.project") == "wud" and
         labels.get("com.docker.compose.service") == "wud" and
         labels.get("com.docker.compose.project.working_dir") == "/docker/wud",
         "Unexpected WUD Compose identity")
    need(wud["Config"]["Image"] == "getwud/wud:9.4.1" and
         wud["State"]["Status"] == "running", "WUD image/state mismatch")
    env = envdict(wud)
    need(env.get("WUD_WATCHER_LOCAL_CRON") == EXPECTED_CRON and
         env.get("WUD_TRIGGER_DOCKER_UPDATES_AUTO") == "true" and
         env.get("WUD_WATCHER_LOCAL_WATCHBYDEFAULT") == "false",
         "WUD scheduled updater settings changed")
    need(env.get("WUD_TRIGGER_SMTP_LEGACY_AUTO") == "true" and
         env.get("WUD_TRIGGER_SMTP_LEGACY_TLS_VERIFY") == "true",
         "WUD SMTP config changed")
    need(all(env.get(k) for k in REQUIRED.values()), "WUD SMTP incomplete")
    need(env[REQUIRED["port"]] in ("465", "587"),
         "SMTP port requires explicit TLS-mode review")
    include = env.get("WUD_WATCHER_LOCAL_INCLUDE", "")
    need(include.startswith("^(?:") and include.endswith(")$"),
         "WUD name allowlist is not exact/anchored")
    try:
        pat = re.compile(include)
    except re.error:
        raise Refused("Invalid WUD watcher name allowlist") from None
    ids = docker("ps", "-aq").stdout.split()
    allc = json.loads(docker("inspect", *ids).stdout) if ids else []
    selected = sorted(c["Name"].lstrip("/") for c in allc
                      if pat.fullmatch(c["Name"].lstrip("/")) and
                      str((c["Config"].get("Labels") or {}).get("wud.watch", "")).lower() != "false")
    need(len(selected) == 26, "Selected container count changed; review actual live scope")
    need(set(("gluetun", "transmission", "mullvad-browser", "vaultwarden",
              "nginx-vaultwarden")) <= set(selected),
         "Expected protected containers missing from allowlist")
    need(WUD_DIR.joinpath("compose.yml").is_file(), "WUD Compose source missing")
    need(WUD_DIR.joinpath(".env").is_file(), "WUD private .env missing")
    for name in ("pihole", "dnsproxy-quad9", "nginx-pihole"):
        c = find(name)
        need(c is not None and c["State"]["Status"] == "running",
             f"Critical DNS container {name} is not running")
    for name in ("gluetun", "transmission", "mullvad-browser"):
        need(find(name) is not None, f"Privacy container {name} missing")
    g = find("gluetun")
    need(g["State"]["Status"] == "running" and
         (g["State"].get("Health") or {}).get("Status") == "healthy",
         "Gluetun unhealthy")
    t, b = find("transmission"), find("mullvad-browser")
    need(t["State"]["Status"] == "paused" and
         t["HostConfig"]["NetworkMode"] != "container:" + g["Id"],
         "Transmission state unexpectedly changed; review before cutover")
    need(b["State"]["Status"] == "running" and
         b["HostConfig"]["NetworkMode"] == "container:" + g["Id"],
         "Mullvad Browser not attached to current Gluetun")
    need(not ROOT.exists() or (ROOT.is_dir() and not any(ROOT.iterdir())),
         "Existing Freshdock directory content; refusing overwrite")
    return env, selected

def toml_string(val):
    need("\x00" not in val and "\n" not in val and "\r" not in val,
         "Multiline/invalid SMTP field")
    return json.dumps(val, ensure_ascii=False)

def smtp_toml(env):
    # Old WUD TLS_ENABLED=false on port 587 means implicit TLS off; Freshdock
    # uses explicit starttls to avoid silently downgrading mail transport.
    tls = "implicit" if env[REQUIRED["port"]] == "465" else "starttls"
    recipients = [x.strip() for x in env[REQUIRED["to"]].split(",") if x.strip()]
    need(bool(recipients), "Missing SMTP recipients")
    return "\n".join([
        "[settings]", 'default_mode = "watch"', "watch_all = false",
        "compose_aware = true", "cleanup = false", "prune_dangling = false",
        "", "[notifications.email]", 'type = "smtp"',
        "host = " + toml_string(env[REQUIRED["host"]]),
        "port = " + env[REQUIRED["port"]],
        "username = " + toml_string(env[REQUIRED["username"]]),
        "password = " + toml_string(env[REQUIRED["password"]]),
        "from = " + toml_string(env[REQUIRED["from"]]),
        "to = [" + ", ".join(toml_string(r) for r in recipients) + "]",
        "tls = " + toml_string(tls),
        'triggers = ["succeeded", "failed"]',
        "",
    ])

def apply(env, selected, source):
    staged = False
    wud_stopped = False
    installed = False
    try:
        need(source.is_file(), "Pinned Freshdock Compose source missing")
        ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        ROOT.chmod(0o700)
        dst = ROOT / "compose.yml"
        dst.write_bytes(source.read_bytes())
        dst.chmod(0o600)
        selection = ROOT / "selected.json"
        selection.write_text(json.dumps({"source": "live-wud-9.4.1",
                                         "cron": EXPECTED_CRON,
                                         "container_names": selected}, indent=2) + "\n")
        selection.chmod(0o600)
        private = ROOT / "freshdock.toml"
        private.write_text(smtp_toml(env))
        private.chmod(0o600)
        staged = True
        compose = ["docker", "compose", "-p", "freshdock",
                   "--project-directory", str(ROOT), "-f", str(dst)]
        call(compose + ["config", "--quiet"])
        docker("pull", IMAGE, seconds=250)
        print("PASS: Freshdock configuration validated and image pulled", flush=True)
        # Freeze WUD only AFTER all available checks and image pull succeed.
        docker("update", "--restart=no", "wud")
        docker("stop", "--time", "30", "wud", seconds=65)
        wud_stopped = True
        print("WUD stopped. Production applications remain untouched.", flush=True)
        call(compose + ["up", "-d", "--no-deps", "--no-build", "--pull", "never",
                        "freshdock"], seconds=90)
        for _ in range(12):
            time.sleep(3)
            instance = find("freshdock")
            need(instance is not None, "Freshdock unexpectedly missing")
            need(instance["State"]["Status"] == "running" and
                 instance["RestartCount"] == 0, "Freshdock crashed or restarted")
            log = docker("logs", "--tail", "100", "freshdock",
                         check=False)
            text = (log.stdout + log.stderr).lower()
            if ("scheduler started" in text and
                    "notification targets configured" in text and
                    "no notification targets configured" not in text and
                    "email(smtp)" in text):
                break
        else:
            raise Refused("Freshdock scheduler/notification startup not verified")
        # Fleet stays unlabelled. Only report-only scheduler is running.
        need(find("wud")["State"]["Status"] == "exited",
             "WUD unexpectedly restarted")
        docker("rm", "wud")
        installed = True
        print("PASS: WUD container removed and Freshdock v1.7.1 started.", flush=True)
        print("Safe state: no application is auto-enrolled by this first stage.", flush=True)
        print("SMTP target configured (delivery still needs a live event test).",
              flush=True)
    finally:
        if not wud_stopped:
            # No production change occurred before this stage except image pull.
            if staged:
                for path in (ROOT / "freshdock.toml", ROOT / "selected.json", ROOT / "compose.yml"):
                    path.unlink(missing_ok=True)
                try:
                    ROOT.rmdir()
                except OSError:
                    pass
        elif not installed:
            print("CRITICAL: Partial cutover. WUD intentionally remains disabled.",
                  file=sys.stderr)
            print("Do not restart it until the failure and VPN safety are reviewed.",
                  file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="replace WUD daemon after strict preflight")
    parser.add_argument("--compose", default="/tmp/freshdock-compose-verified.yml",
                        help="local trusted Compose source (not downloaded by script)")
    args = parser.parse_args()
    try:
        env, selected = assert_live_state()
        print("Existing WUD-selected containers:", len(selected), "(source stored privately on apply)")
        print("PASS: Host, WUD, critical DNS, Gluetun, and private SMTP preflight")
        print("SMTP present; TLS mode:", "STARTTLS" if env[REQUIRED["port"]] == "587"
              else "implicit")
        print("Current 02:45 WUD update schedule noted; Freshdock will not have "
              "any auto-enrolled applications until stage two.")
        if args.apply:
            apply(env, selected, Path(args.compose))
        else:
            print("READ ONLY: Add --apply --compose <file> for daemon replacement.")
        return 0
    except (Refused, OSError, ValueError, KeyError) as e:
        print("STOP:", e, file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
