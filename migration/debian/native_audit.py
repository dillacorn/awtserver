#!/usr/bin/env python3
"""Focused read-only audit of host-native features for a future Debian rebuild.

No configuration content, credentials, secrets, private keys, Docker inspect
values, firewall rules, SSH policy values, Tailscale IPs or disk UUIDs are
printed. Information is written only to stdout; no services are changed.
"""
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys

HOST = "openmediavault"
SERVICES = (
    "ssh", "fail2ban", "proftpd", "apcupsd", "nut-monitor",
    "smartmontools", "smartd", "smartctl-hdparm", "smbd",
    "wsdd-server", "nfs-server", "rpcbind", "avahi-daemon",
    "clamav-daemon", "clamav-freshclam", "collectd", "chrony",
    "postfix", "nginx", "php8.2-fpm", "netbird", "podman",
    "podman-restart", "podman-auto-update", "systemd-networkd",
    "systemd-resolved", "networking", "netfilter-persistent",
    "nftables", "docker", "containerd", "tailscaled", "pihm-web",
    "unattended-upgrades", "openmediavault-engined",
    "omv-docker-upgrade-recovery", "omv-pihole-tailscale-dns-guard",
    "watchtower-fork-verify",
)
TIMERS = (
    "omv-docker-upgrade-recovery", "omv-pihole-tailscale-dns-guard",
    "watchtower-fork-verify", "podman-auto-update",
    "apt-daily", "apt-daily-upgrade", "certbot", "fstrim",
)
CONFDB_IDS = (
    "conf.system.cron.job", "conf.service.rsync.job",
    "conf.service.smb", "conf.service.ftp",
    "conf.service.smartmontools", "conf.service.ssh",
)


def out(*cmd, timeout=18):
    if not shutil.which(cmd[0]):
        return None
    try:
        p = subprocess.run(cmd, text=True, capture_output=True,
                           timeout=timeout, errors="replace", check=False)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def heading(label):
    print("\n===== " + label + " =====", flush=True)


def unit_status(unit):
    active = out("systemctl", "is-active", unit)
    enabled = out("systemctl", "is-enabled", unit)
    # Exit status is nonzero for inactive/disabled. Follow up with
    # read-only systemctl show to distinguish loaded vs nonexistent.
    shown = out("systemctl", "show", unit,
                "-p", "LoadState", "-p", "ActiveState", "-p", "UnitFileState")
    values = {}
    for line in (shown or "").splitlines():
        name, sep, value = line.partition("=")
        if sep:
            values[name] = value
    return {
        "loaded": values.get("LoadState", "unknown"),
        "active": values.get("ActiveState", active or "unknown"),
        "enabled": values.get("UnitFileState", enabled or "unknown"),
    }


def service_rows():
    heading("HOST SERVICE STATES (NOT DOCKER)")
    for name in SERVICES:
        status = unit_status(name + ".service")
        if status["loaded"] == "not-found":
            continue
        print("{:<34} {:<11} {:<18} {}".format(
            name, status["active"], status["enabled"], status["loaded"]))
    heading("NATIVE TIMER STATES")
    for name in TIMERS:
        status = unit_status(name + ".timer")
        print("{:<34} {:<11} {:<18} {}".format(
            name, status["active"], status["enabled"], status["loaded"]))


def mounts():
    heading("MERGERFS MOUNT ACTUAL STATUS")
    path = "/srv/mergerfs/data/root"
    result = out("findmnt", "-n", "-T", path, "-o", "TARGET,FSTYPE")
    print("Actual filesystem for Samba share target:",
          result.replace("\n", "; ") if result else "NOT RESOLVED")
    result = out("findmnt", "-n", "-T", "/srv/mergerfs/data", "-o", "TARGET,FSTYPE")
    print("Actual filesystem for mergerfs parent:",
          result.replace("\n", "; ") if result else "NOT RESOLVED")
    status = unit_status("srv-mergerfs-data.mount")
    print("Mergerfs systemd mount unit:", status)
    raw = out("lsblk", "-J", "-b", "-o", "NAME,TYPE,SIZE,TRAN,MOUNTPOINTS")
    if not raw:
        print("Unmounted-device inventory unavailable")
        return
    try:
        devices = json.loads(raw).get("blockdevices", [])
    except (TypeError, ValueError):
        print("Unmounted-device inventory unavailable")
        return

    def has_mount(node):
        if any(p for p in node.get("mountpoints") or []):
            return True
        return any(has_mount(child) for child in node.get("children") or [])

    for disk in devices:
        if disk.get("type") == "disk" and not has_mount(disk):
            size = disk.get("size")
            gib = f"{size/1024**3:.1f} GiB" if isinstance(size, (float, int)) else "unknown"
            print("Entirely unmounted disk:", disk.get("name"), gib,
                  "transport=" + str(disk.get("tran") or "unknown"))


def omv_config_counts():
    heading("OMV FEATURES / JOB COUNTS (NO COMMANDS OR SECRETS)")
    if not shutil.which("omv-confdbadm"):
        print("OMV config database command unavailable")
        return
    for key in CONFDB_IDS:
        raw = out("omv-confdbadm", "read", key, timeout=18)
        if raw is None:
            print(key + ": unavailable")
            continue
        try:
            parsed = json.loads(raw)
        except ValueError:
            print(key + ": not parseable; content suppressed")
            continue
        if isinstance(parsed, list):
            total = len(parsed)
            enabled = sum(str(x.get("enable", "")).lower() in ("true", "1", "yes")
                          for x in parsed if isinstance(x, dict))
            print(f"{key}: {total} entries, {enabled} explicitly enabled")
        elif isinstance(parsed, dict):
            print(key + ": configuration object present (values suppressed)")
        else:
            print(key + ": present, nonobject (value suppressed)")


def backup_and_managers():
    heading("BACKUP / AUXILIARY TOOL INDICATORS")
    packages = out("dpkg-query", "-W", "-f=" + "\u0024{binary:Package}\\n",
                   timeout=22) or ""
    for name in ("borgbackup", "restic", "rsync", "timeshift", "proftpd",
                 "podman", "netbird", "clamav", "apcupsd", "nut",
                 "smartmontools", "postfix"):
        installed = any(p == name or p.startswith(name + "-")
                        for p in packages.splitlines())
        print(f"{name}: package-present={installed}")
    for p in ("/etc/cron.d", "/etc/cron.daily", "/etc/cron.weekly",
              "/etc/systemd/system"):
        try:
            names = sorted(f.name for f in Path(p).iterdir()
                           if re.search("backup|sync|scrub|timeshift|borg|usb|snapraid|cert|smart",
                                        f.name, flags=re.IGNORECASE))
        except OSError:
            names = []
        print(p + " relevant filenames: " +
              (", ".join(names[:50]) if names else "none found"))
    if shutil.which("podman"):
        raw = out("podman", "ps", "--all", "--format", "{{.Names}}", timeout=25)
        if raw is None:
            print("Podman container inventory: unavailable")
        else:
            names = [x for x in raw.splitlines() if x.strip()]
            print("Podman container count:", len(names))
            # Names may disclose applications; preserve private conversational scope.
            print("Podman container names:", ", ".join(names[:60]) or "none")
    print("SMART daemon process present:",
          out("pgrep", "-x", "smartd") is not None)


def main():
    if os.geteuid() != 0 or socket.gethostname() != HOST:
        print("STOP: Run as root on openmediavault", file=sys.stderr)
        return 1
    print("READ-ONLY NATIVE HOST DEPENDENCY AUDIT")
    print("Host:", HOST)
    service_rows()
    mounts()
    omv_config_counts()
    backup_and_managers()
    print("\nPASS: Read-only audit complete; no server settings changed.")
    print("Output contains private service names and paths: keep out of public Git.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
