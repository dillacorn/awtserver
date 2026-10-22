#!/usr/bin/env python3
"""Conservative, VM-only materialization of awtserver declarative jobs.

No program in this module modifies a live system without the caller's VM gate.
Only /etc/cron.d/awtserver is ever written. No unrelated crontab is read/written.
"""
from __future__ import annotations

import difflib
import os
from pathlib import Path
import pwd
import stat
import tempfile
import subprocess

from awtserver import validate_job, valid_cron

CRON_FILE = Path("/etc/cron.d/awtserver")
SCRIPT_DIR = Path("/usr/local/libexec/awtserver-jobs")
MARKER = "# awtserver-managed-cron-v1\n"
HEADER = (
    MARKER
    + "# Generated from /var/lib/awtserver/jobs.json; do not edit here.\n"
    + "SHELL=/bin/sh\n"
    + "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
)


def render_cron(jobs: list[dict]) -> str:
    names: set[str] = set()
    lines = [HEADER]
    for job in sorted(jobs, key=lambda entry: entry["name"]):
        if set(job) != {"name", "schedule", "user", "script", "enabled"}:
            raise ValueError("Unexpected job fields")
        expected = validate_job(job["name"], job["schedule"],
                                job["user"], job["script"])
        if type(job["enabled"]) is not bool:
            raise ValueError("Job enabled must be a boolean")
        if job["name"] in names:
            raise ValueError("Duplicate job name")
        names.add(job["name"])
        if job["enabled"]:
            lines.append(f"# {job['name']}\n"
                         f"{expected['schedule']} {expected['user']} {expected['script']}\n")
        else:
            lines.append(f"# disabled: {job['name']}\n")
    return "".join(lines)


def _checked_root_path(path: Path, *, directory: bool) -> None:
    info = path.lstat()  # refuses symlinks, including dangling ones
    if directory and not stat.S_ISDIR(info.st_mode):
        raise ValueError("Not a directory: " + str(path))
    if not directory and not stat.S_ISREG(info.st_mode):
        raise ValueError("Not a regular file: " + str(path))
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("Unsafe ownership or permissions: " + str(path))


def validate_active_jobs(jobs: list[dict]) -> None:
    """Validate actual execution identities/scripts only when activating."""
    active = [job for job in jobs if job["enabled"]]
    if not active:
        return
    _checked_root_path(SCRIPT_DIR, directory=True)
    for job in active:
        user = pwd.getpwnam(job["user"])
        if user.pw_uid == 0:
            raise ValueError("Root execution is unsupported in this prototype")
        script = Path(job["script"])
        if script.parent != SCRIPT_DIR:
            raise ValueError("Script outside approved directory")
        _checked_root_path(script, directory=False)
        mode = script.stat().st_mode
        if not mode & stat.S_IXOTH:
            raise ValueError("Job script must be executable by non-root user")
        if not mode & stat.S_IROTH:
            raise ValueError("Job script must be readable by non-root user")


def existing_content(path: Path = CRON_FILE) -> str:
    if path.is_symlink():
        raise ValueError("Refusing symlinked cron file")
    if not path.exists():
        return ""
    _checked_root_path(path, directory=False)
    body = path.read_text(encoding="utf-8")
    if not body.startswith(MARKER):
        raise ValueError("Refusing to replace an unmanaged cron file")
    return body


def preview_cron(jobs: list[dict], path: Path = CRON_FILE) -> str:
    desired = render_cron(jobs)
    old = existing_content(path)
    if old == desired:
        return "No cron changes required.\n"
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True),
        desired.splitlines(keepends=True),
        fromfile=str(path) + " (current)",
        tofile=str(path) + " (proposed)",
    ))


def sync_cron(jobs: list[dict], path: Path = CRON_FILE) -> bool:
    """Deploy only an owned, managed cron file, after caller performed VM gate."""
    if path.parent.is_symlink():
        raise ValueError("Refusing symlinked /etc/cron.d")
    _checked_root_path(path.parent, directory=True)
    desired = render_cron(jobs)
    old = existing_content(path)
    if old == desired:
        return False
    if not subprocess.run(["systemctl", "is-active", "--quiet", "cron"],
                          check=False).returncode == 0:
        raise ValueError("cron service is not active; schedule deployment blocked")
    validate_active_jobs(jobs)
    # Recheck ownership/content immediately before rename. The root-only
    # cron.d directory protects against replacement by non-root writers.
    if existing_content(path) != old:
        raise ValueError("Cron file changed during review")
    fd, temp = tempfile.mkstemp(prefix=".awtserver-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(desired)
            stream.flush()
            os.fsync(stream.fileno())
        if existing_content(path) != old:
            raise ValueError("Cron file changed before replacement")
        os.replace(temp, path)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)
    return True
