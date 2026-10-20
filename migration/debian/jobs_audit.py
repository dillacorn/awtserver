#!/usr/bin/env python3
"""Read-only migration audit of OMV jobs and rsync backup schedules.

Reads OMV confdb entries and cron scheduling metadata, never prints command
bodies, user-provided comments, destination paths, credentials, addresses,
passwords, SSH keys, or UUIDs. Only outputs schedules, predefined keyword
categories, and rsync safety flags. Does not modify files or services.
"""
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys

HOST = "openmediavault"
CRON_FILES = (
    "/etc/cron.d/openmediavault-userdefined",
    "/etc/cron.d/openmediavault-rsync",
    "/etc/cron.d/omv-compose-backup",
)
CRON_TYPES = (
    "snapraid", "rsync", "docker", "borg", "timeshift", "smart",
    "backup", "scrub", "clamav", "certbot", "curl",
    "python", "bash", "systemctl", "other",
)
SCHEDULE_KEYS = ("minute", "hour", "dayofmonth", "month", "dayofweek")
FLAGS = ("enable", "sendemail", "everynminute", "everynhour",
         "everyndayofmonth", "optiondelete", "optiondryrun",
         "optionarchive", "optionrecursive", "optionacls", "optionxattrs")


def read_command(*argv, timeout=25):
    if shutil.which(argv[0]) is None:
        return None
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout, errors="replace", check=False)
        return p.stdout if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def safe_flag(value):
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int) and value in (0, 1):
        return "yes" if value else "no"
    if isinstance(value, str):
        text = value.lower().strip()
        if text in ("yes", "true", "1"):
            return "yes"
        if text in ("no", "false", "0"):
            return "no"
    return "unknown"


def safe_field(value):
    # Cron numeric, wildcard, lists and step expressions only.
    s = str(value)
    if re.fullmatch(r"[0-9*/,\-]{1,30}", s):
        return s
    return "[unrecognized]"


def schedule(job):
    execution = job.get("execution", "exactly")
    if execution != "exactly":
        allowed = {"hourly", "daily", "weekly", "monthly", "yearly",
                   "reboot", "everyminute"}
        if isinstance(execution, str) and execution in allowed:
            return "execution=" + execution
        return "execution=[unrecognized]"
    fields = []
    for field in SCHEDULE_KEYS:
        raw = safe_field(job.get(field, "?"))
        every = safe_flag(job.get({"minute": "everynminute",
                                  "hour": "everynhour",
                                  "dayofmonth": "everyndayofmonth"}.get(field)))
        if every == "yes" and raw not in ("*", "[unrecognized]"):
            raw = "*/" + raw
        fields.append(raw)
    return " ".join(fields)


def categories(command_text):
    if not isinstance(command_text, str):
        return ["unknown"]
    found = []
    for kind in CRON_TYPES:
        if kind == "other":
            continue
        if re.search(r"(?i)(?<![a-z0-9])" + re.escape(kind) +
                     r"(?![a-z0-9])", command_text):
            found.append(kind)
    return found or ["other"]


def confdb(name):
    raw = read_command("omv-confdbadm", "read", name)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def omv_jobs():
    print("\n===== OMV SCHEDULED JOBS (COMMANDS REDACTED) =====")
    jobs = confdb("conf.system.cron.job")
    if jobs is None:
        print("Unavailable")
    else:
        print("Configured:", len(jobs))
        for index, job in enumerate(jobs, 1):
            if not isinstance(job, dict):
                print(f"Job {index}: malformed")
                continue
            status = safe_flag(job.get("enable"))
            kinds = categories(job.get("command"))
            print(f"Job {index}: enabled={status} schedule={schedule(job)} "
                  f"category={','.join(kinds)} sendemail="
                  f"{safe_flag(job.get('sendemail'))} "
                  "command=[REDACTED]")
    print("\n===== OMV RSYNC JOBS (SOURCE/DESTINATIONS REDACTED) =====")
    jobs = confdb("conf.service.rsync.job")
    if jobs is None:
        print("Unavailable")
    else:
        print("Configured:", len(jobs))
        for index, job in enumerate(jobs, 1):
            if not isinstance(job, dict):
                print(f"Job {index}: malformed")
                continue
            typ = job.get("type")
            mode = job.get("mode")
            typ = typ if typ in ("local", "remote") else "unknown"
            mode = mode if mode in ("push", "pull") else "unknown"
            opts = " ".join(
                f"{key.removeprefix('option')}={safe_flag(job.get(key))}"
                for key in ("optiondelete", "optiondryrun",
                            "optionarchive", "optionrecursive",
                            "optionacls", "optionxattrs"))
            print(f"Rsync {index}: enabled={safe_flag(job.get('enable'))} "
                  f"schedule={schedule(job)} type={typ} mode={mode} "
                  f"{opts} sendemail={safe_flag(job.get('sendemail'))} "
                  "src=[REDACTED] dest=[REDACTED]")
    print("\n===== SYSTEM CRON FILES (ONLY TIMINGS / JOB COUNTS) =====")
    for filename in CRON_FILES:
        path = Path(filename)
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            print(path.name + ": absent/unreadable")
            continue
        schedules = []
        for line in raw.splitlines():
            tokens = line.strip().split()
            if not tokens or line.lstrip().startswith("#") or "=" in tokens[0]:
                continue
            if tokens[0].startswith("@") and len(tokens) >= 3:
                if tokens[0] in ("@reboot", "@daily", "@weekly", "@monthly",
                                 "@hourly", "@annually", "@yearly"):
                    schedules.append(tokens[0])
            elif len(tokens) >= 7:
                fields = [safe_field(x) for x in tokens[:5]]
                if "[unrecognized]" not in fields:
                    schedules.append(" ".join(fields))
        print(f"{path.name}: {len(schedules)} scheduled entries" +
              (" [" + "; ".join(schedules[:20]) + "]" if schedules else ""))


def main():
    if os.geteuid() != 0 or socket.gethostname() != HOST:
        print("STOP: Run as root on openmediavault", file=sys.stderr)
        return 1
    print("READ-ONLY OMV JOBS AND BACKUP SCHEDULE AUDIT")
    omv_jobs()
    print("\nPASS: OMV scheduled-job audit completed without changes")
    print("All command bodies, job comments, credentials, and paths were omitted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
