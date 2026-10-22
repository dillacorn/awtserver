#!/usr/bin/env python3
"""awtserver: VM-gated Debian package profiles and declarative job planning.

The CLI deliberately does not change disks, mounts, network settings, Docker
containers, systemd jobs, or cron. Job records are plans, not running schedules.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

STATE_DIR = Path("/var/lib/awtserver")
JOBS_FILE = STATE_DIR / "jobs.json"
JOB_SCRIPTS = Path("/usr/local/libexec/awtserver-jobs")

# Debian Stable package names. Packages may start daemons via Debian maintainer
# scripts even though awtserver itself never enables or edits service units.
PROFILES = {
    "base": ("ca-certificates", "curl", "git", "jq"),
    "access": ("openssh-server", "fail2ban"),
    "storage": ("snapraid", "mergerfs", "smartmontools"),
    "ftp": ("proftpd-core",),
    "ups": ("apcupsd",),
    "docker": ("docker.io", "docker-compose"),
    "scheduler": ("cron",),
    "sharing": ("samba",),
    "backup": ("rsync",),
}
DEFAULT_PROFILES = ("base", "access", "storage", "backup")
NAME_RE = re.compile(r"[a-z][a-z0-9_-]{0,47}\Z")
USER_RE = re.compile(r"[a-z_][a-z0-9_-]{0,31}\Z")


def packages_for(profiles: list[str]) -> list[str]:
    invalid = sorted(set(profiles) - PROFILES.keys())
    if invalid:
        raise ValueError("Unknown profile(s): " + ", ".join(invalid))
    return sorted({pkg for profile in profiles for pkg in PROFILES[profile]})


def parse_os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    info = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        info[key] = value.strip().strip('"').strip("'")
    return info


def virtual_machine() -> bool:
    try:
        return subprocess.run(
            ["systemd-detect-virt", "--vm", "--quiet"],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
    except FileNotFoundError:
        return False


def apply_guard(confirmed: bool) -> None:
    """Never permit package/state writes to the existing OMV NAS or a real host."""
    if not confirmed:
        raise ValueError("Write blocked: add --confirm-vm to acknowledge a disposable VM")
    if os.geteuid() != 0:
        raise ValueError("Write blocked: requires root")
    os_info = parse_os_release()
    if os_info.get("ID") != "debian" or os_info.get("VERSION_ID") != "13":
        raise ValueError("Write blocked: Debian 13 is the only evaluated target")
    if Path("/etc/openmediavault").exists():
        raise ValueError("Write blocked: OpenMediaVault installation detected")
    if not virtual_machine():
        raise ValueError("Write blocked: disposable virtual machine not detected")


def profile_plan(profiles: list[str]) -> dict:
    return {"profiles": profiles, "packages": packages_for(profiles),
            "effects": ["APT index refresh", "APT package installation",
                        "Debian packages may start services"],
            "excluded": ["disk formatting", "mount changes", "network/firewall changes",
                         "Docker stack deployment", "OMV removal", "UPS configuration",
                         "cron/systemd job activation"]}


def valid_cron(schedule: str) -> bool:
    """Conservative numeric five-field cron syntax; no command or env expansion."""
    bounds = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
    fields = schedule.split()
    if len(fields) != 5:
        return False
    for field, (low, high) in zip(fields, bounds):
        for part in field.split(","):
            match = re.fullmatch(r"(\*|[0-9]{1,2})(?:-([0-9]{1,2}))?(?:/([0-9]{1,2}))?", part)
            if not match:
                return False
            start, end, step = match.groups()
            if start != "*" and not low <= int(start) <= high:
                return False
            if end is not None:
                if start == "*" or not low <= int(end) <= high or int(end) < int(start):
                    return False
            if step is not None and (int(step) == 0 or (start != "*" and end is None)):
                return False
    return True


def validate_job(name: str, schedule: str, user: str, script: str) -> dict:
    if not NAME_RE.fullmatch(name):
        raise ValueError("Job name must be lowercase ASCII letters, digits, _ or -")
    if not valid_cron(schedule):
        raise ValueError("Unsupported cron expression (use five numeric fields)")
    if not USER_RE.fullmatch(user) or user == "root":
        raise ValueError("Job user must be a named, non-root account")
    path = Path(script)
    if not path.is_absolute() or path.parent != JOB_SCRIPTS:
        raise ValueError("Script must be directly under " + str(JOB_SCRIPTS))
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", path.name):
        raise ValueError("Unsafe script filename")
    return {"name": name, "schedule": " ".join(schedule.split()),
            "user": user, "script": str(path), "enabled": False}


def load_jobs(path: Path | None = None) -> list[dict]:
    path = path if path is not None else JOBS_FILE
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise ValueError("Unsafe jobs state path")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Jobs state must be an array")
    names = set()
    for job in data:
        if not isinstance(job, dict):
            raise ValueError("Invalid job record")
        expected = validate_job(job["name"], job["schedule"], job["user"], job["script"])
        if type(job.get("enabled")) is not bool or job["name"] in names:
            raise ValueError("Invalid/duplicate job state")
        if set(job) != set(expected):
            raise ValueError("Unknown fields in job state")
        names.add(job["name"])
    return data


def save_jobs(jobs: list[dict], path: Path | None = None) -> None:
    """Atomic private state write; intentionally does not install cron jobs."""
    path = path if path is not None else JOBS_FILE
    parent = path.parent
    if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
        raise ValueError("Unsafe state directory")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("Unsafe jobs state path")
    payload = json.dumps(jobs, indent=2, sort_keys=True) + "\n"
    fd, temp = tempfile.mkstemp(prefix=".jobs-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            os.fchmod(out.fileno(), 0o600)
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def jobs_command(args: argparse.Namespace) -> None:
    jobs = load_jobs()
    if args.job_action == "list":
        print(json.dumps({"jobs": jobs, "active_cron_jobs": 0,
                          "note": "Declarative plans only: no cron entries installed"},
                         indent=2))
        return
    if args.job_action == "add":
        job = validate_job(args.name, args.schedule, args.user, args.script)
        if any(old["name"] == job["name"] for old in jobs):
            raise ValueError("Job already exists; no implicit overwrite")
        jobs.append(job)
    else:
        matches = [job for job in jobs if job["name"] == args.name]
        if not matches:
            raise ValueError("Job does not exist")
        if args.job_action == "enable":
            matches[0]["enabled"] = True
        elif args.job_action == "disable":
            matches[0]["enabled"] = False
        elif args.job_action == "remove":
            jobs = [job for job in jobs if job["name"] != args.name]
    print(json.dumps({"action": args.job_action, "result": jobs,
                      "note": "Enabled is desired state only; cron is not activated"}, indent=2))
    if args.apply:
        apply_guard(args.confirm_vm)
        save_jobs(jobs)
        print("Saved declarative jobs state (no cron/systemd changes).")
    else:
        print("Preview only. No files changed; --apply --confirm-vm is VM-only.")


def doctor() -> None:
    info = parse_os_release()
    names = ("ssh", "docker", "fail2ban", "smartmontools", "apcupsd", "cron")
    output = {"os": info.get("PRETTY_NAME", "unknown"),
              "supported_apply_target": info.get("ID") == "debian"
                 and info.get("VERSION_ID") == "13"
                 and not Path("/etc/openmediavault").exists()
                 and virtual_machine(),
              "virtual_machine": virtual_machine(),
              "omv_present": Path("/etc/openmediavault").exists(),
              "services": {}}
    for name in names:
        try:
            cmd = subprocess.run(["systemctl", "is-active", name], capture_output=True,
                                 text=True, check=False, timeout=3)
            output["services"][name] = cmd.stdout.strip() or "unknown"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            output["services"][name] = "unknown"
    print(json.dumps(output, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="awtserver Debian 13 VM prototype")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Read-only host diagnostics")
    sub.add_parser("profiles", help="List available package profiles")
    for action in ("plan", "install"):
        cmd = sub.add_parser(action, help="Plan or VM-only install Debian packages")
        cmd.add_argument("--profiles", nargs="+", choices=sorted(PROFILES),
                         default=list(DEFAULT_PROFILES))
        if action == "install":
            cmd.add_argument("--apply", action="store_true")
            cmd.add_argument("--confirm-vm", action="store_true")
    js = sub.add_parser("jobs", help="Manage declarative job plans; never runs cron")
    jsub = js.add_subparsers(dest="job_action", required=True)
    jsub.add_parser("list")
    for action in ("add", "enable", "disable", "remove"):
        cmd = jsub.add_parser(action)
        cmd.add_argument("--name", required=True)
        if action == "add":
            cmd.add_argument("--schedule", required=True, help='Example: "15 2 * * *"')
            cmd.add_argument("--user", required=True)
            cmd.add_argument("--script", required=True)
        cmd.add_argument("--apply", action="store_true")
        cmd.add_argument("--confirm-vm", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            doctor()
        elif args.command == "profiles":
            print(json.dumps(PROFILES, indent=2))
        elif args.command in ("plan", "install"):
            plan = profile_plan(args.profiles)
            print(json.dumps(plan, indent=2))
            if args.command == "install":
                if not args.apply:
                    print("Preview only; --apply --confirm-vm required on a disposable Debian 13 VM.")
                else:
                    apply_guard(args.confirm_vm)
                    # Resolve package candidates without touching APT configuration.
                    subprocess.run(["apt-get", "update"], check=True)
                    subprocess.run(["apt-get", "--simulate", "--no-remove", "install",
                                    *plan["packages"]], check=True)
                    subprocess.run(["apt-get", "install", "-y", "--no-remove", *plan["packages"]], check=True)
        elif args.command == "jobs":
            jobs_command(args)
    except (ValueError, OSError, subprocess.CalledProcessError, KeyError, json.JSONDecodeError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
