#!/usr/bin/env python3
"""Sanitized read-only OMV capability probe.

Never prints disk serials/UUIDs, mounts, IPs, usernames, container names,
job command bodies, auth secrets or email addresses. Makes no changes.
"""
import json
from pathlib import Path
import subprocess

PKGS = ("openmediavault", "openmediavault-snapraid", "mergerfs",
        "snapraid", "apcupsd", "smartmontools", "postfix", "samba",
        "rsync", "restic", "borgbackup", "timeshift", "gdu", "ncdu",
        "duf", "btop", "docker-ce", "docker.io", "clamav-daemon",
        "fail2ban", "cron", "proftpd-core", "unattended-upgrades")
SERVICES = ("ssh", "docker", "cron", "smartd", "smartmontools",
            "apcupsd", "tailscaled", "fail2ban", "postfix",
            "smbd", "proftpd", "pihm-web")
TOKENS = ("snapraid", "backup", "rsync", "watchtower", "cert",
          "smart", "cron", "apt", "pihole", "pihm", "docker",
          "restic", "borg", "compose")


def run(*argv, timeout=12):
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           check=False, timeout=timeout)
        return p.stdout if p.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def omv_jobs():
    # OMV command bodies stay solely in memory and are NEVER printed.
    raw = run("omv-confdbadm", "read", "conf.system.cron.job")
    try:
        jobs = json.loads(raw)
        if isinstance(jobs, dict):
            jobs = [jobs]
        if isinstance(jobs, list):
            enabled = sum(str(x.get("enable", x.get("enabled", ""))).lower()
                          in ("1", "true", "yes") for x in jobs
                          if isinstance(x, dict))
            return {"total": len(jobs), "enabled": enabled}
    except (ValueError, TypeError):
        pass
    return {"total": None, "enabled": None}


def usb_summary():
    raw = run("lsblk", "-J", "-o", "TYPE,TRAN,RM,MOUNTPOINTS")
    result = {"usb_disks": 0, "usb_unmounted": 0}
    try:
        disks = json.loads(raw)["blockdevices"]
    except (ValueError, KeyError, TypeError):
        return result
    for disk in disks:
        if disk.get("type") != "disk" or not (
                disk.get("tran") == "usb" or disk.get("rm") is True):
            continue
        result["usb_disks"] += 1
        nodes = [disk] + (disk.get("children") or [])
        if not any(any(n.get("mountpoints") or []) for n in nodes):
            result["usb_unmounted"] += 1
    return result


def main():
    package_output = run("dpkg-query", "-W", "-f=" + "$" + "{binary:Package}\n")
    found = set(package_output.splitlines())
    units = run("systemctl", "list-timers", "--all", "--no-pager", "--no-legend")
    timers = sorted({part for line in units.splitlines()
                     for part in line.split()
                     if part.endswith(".timer") and
                     any(t in part.lower() for t in TOKENS)})
    cron = {}
    for name in ("cron.d", "cron.daily", "cron.weekly", "cron.monthly"):
        path = Path("/etc") / name
        try:
            cron[name] = sum(p.is_file() for p in path.iterdir()
                             if not p.name.startswith("."))
        except OSError:
            cron[name] = None
    version = {}
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith(("ID=", "VERSION_ID=")):
                key, value = line.split("=", 1)
                version[key] = value.strip('"')
    except OSError:
        pass
    output = {
        "report": "awtserver feature inventory (read-only)",
        "os": version,
        "omv_present": Path("/etc/openmediavault").is_dir(),
        "packages": {x: x in found for x in PKGS},
        "services_active": {x: run("systemctl", "is-active", x).strip()
                            == "active" for x in SERVICES},
        "omv_job_counts": omv_jobs(),
        "cron_file_counts": cron,
        "relevant_timers": timers,
        "removable_disks": usb_summary(),
        "snapraid_aio_script_common_path_present": any(
            x.is_file() for x in (
                Path("/usr/sbin/snapraid/snapraid-aio-script.sh"),
                Path("/usr/local/sbin/snapraid-aio-script.sh"),
                Path("/opt/snapraid/snapraid-aio-script.sh"))),
        "note": "Counts/status only. No secrets, paths, job commands, or identifiers."}
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
