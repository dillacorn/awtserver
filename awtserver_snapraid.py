"""SnapRAID AIO v3.4 package and root-cron management for disposable Debian VM.

Schedule state can be planned, enabled/disabled and synchronized without
executing SnapRAID. Production host, disks, OMV and forced sync are excluded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

from awtserver import apply_guard, valid_cron

SCRIPT_DIR = Path("/usr/local/libexec/awtserver-snapraid")
SCRIPT = SCRIPT_DIR / "snapraid-aio-script.sh"
CONFIG = SCRIPT_DIR / "script-config.conf"
SCHEDULE = Path("/var/lib/awtserver/snapraid-schedule.json")
CRON = Path("/etc/cron.d/awtserver-snapraid")
MARKER = "# awtserver-managed-snapraid-v1\n"
DEFAULT = {"enabled": False, "schedule": "30 1 * * *"}


def require_safe_file(path: Path, *, mode: int | None = None) -> None:
    meta = path.lstat()
    if not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022:
        raise ValueError("Unsafe file ownership/permissions: " + str(path))
    if mode is not None and meta.st_mode & 0o777 != mode:
        raise ValueError("Unexpected file permissions: " + str(path))


def schedule_from_file(path: Path = SCHEDULE) -> dict:
    if path.is_symlink():
        raise ValueError("Refusing symlink state file")
    if not path.exists():
        return DEFAULT.copy()
    require_safe_file(path)
    settings = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(settings, dict) or set(settings) != {"enabled", "schedule"}:
        raise ValueError("Unrecognized schedule state")
    if type(settings["enabled"]) is not bool or not valid_cron(settings["schedule"]):
        raise ValueError("Invalid schedule state")
    return settings


def render_cron(settings: dict) -> str:
    if not isinstance(settings, dict) or set(settings) != {"enabled", "schedule"}:
        raise ValueError("Invalid schedule")
    if type(settings["enabled"]) is not bool or not valid_cron(settings["schedule"]):
        raise ValueError("Invalid schedule")
    # Explicit non-overlap lock. Never use --force-sync.
    return (MARKER +
            "# Installed only after VM preflight and review of AIO configuration\n"
            "SHELL=/bin/bash\n"
            "PATH=/usr/sbin:/usr/bin:/sbin:/bin\n" +
            (f"{settings['schedule']} root /usr/bin/flock -n /run/lock/awtserver-snapraid.lock "
             f"{SCRIPT}\n" if settings["enabled"] else "# disabled\n"))


def safe_existing(path: Path, marker: str) -> str:
    if path.is_symlink():
        raise ValueError("Refusing symlinked destination")
    if not path.exists():
        return ""
    require_safe_file(path)
    value = path.read_text(encoding="utf-8")
    if not value.startswith(marker):
        raise ValueError("Refusing to replace unmanaged file")
    return value


def atomic_create_or_replace(path: Path, text: str, *, mode: int,
                             marker: str | None = None) -> bool:
    parent = path.parent
    meta = parent.lstat()
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022:
        raise ValueError("Unsafe destination directory")
    old = safe_existing(path, marker) if marker is not None else (
        path.read_text(encoding="utf-8") if path.is_file() and not path.is_symlink() else "")
    if old == text:
        return False
    if marker is None and (path.exists() or path.is_symlink()):
        raise ValueError("Existing state file; use managed overwrite flow")
    fd, temp = tempfile.mkstemp(prefix=".awtserver-snapraid-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), mode)
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if marker is not None and safe_existing(path, marker) != old:
            raise ValueError("Destination changed during update")
        os.replace(temp, path)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)
    return True


def save_settings(settings: dict, path: Path = SCHEDULE) -> None:
    # State is separate from cron activation and cannot activate by itself.
    apply_guard(True)
    render_cron(settings)
    parent = path.parent
    if parent.is_symlink():
        raise ValueError("Unsafe state parent")
    parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    meta = parent.stat()
    if meta.st_uid != 0 or meta.st_mode & 0o077:
        raise ValueError("State directory must be root-owned mode 0700")
    old = schedule_from_file(path)
    if path.exists() and set(old) != {"enabled", "schedule"}:
        raise ValueError("Unexpected state")
    # Replacements only allowed for the exact regular, root-owned state file.
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    desired = json.dumps(settings, sort_keys=True, indent=2) + "\n"
    if desired == current:
        return
    if path.exists():
        require_safe_file(path, mode=0o600)
        if path.read_text(encoding="utf-8") != current:
            raise ValueError("State changed during update")
        # Replacement is restricted to validated JSON root-owned file.
        fd, temp = tempfile.mkstemp(prefix=".snapraid-", dir=parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                os.fchmod(f.fileno(), 0o600)
                f.write(desired)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, path)
        finally:
            if os.path.lexists(temp):
                os.unlink(temp)
    else:
        atomic_create_or_replace(path, desired, mode=0o600)


def prerequisites(script: Path = SCRIPT, config: Path = CONFIG) -> list[str]:
    issues = []
    for p in (script, config):
        try:
            require_safe_file(p)
        except (OSError, ValueError) as exc:
            issues.append(f"{p}: {type(exc).__name__}")
    if not issues:
        if "SNAPSCRIPTVERSION=\"3.4\"" not in script.read_text(encoding="utf-8"):
            issues.append("Script version not verified as AIO v3.4")
        if not re.search(r'^CONFIG_VERSION=["\x27]?3\.4', config.read_text(encoding="utf-8"),
                         flags=re.MULTILINE):
            issues.append("Script configuration needs review/upgrade to 3.4")
    for exe in ("flock", "snapraid"):
        if not shutil.which(exe):
            issues.append("Missing binary: " + exe)
    return issues


def sync(settings: dict, path: Path = CRON, script: Path = SCRIPT,
         config: Path = CONFIG) -> bool:
    apply_guard(True)
    desired = render_cron(settings)
    if path.parent.is_symlink():
        raise ValueError("Cron directory is a symlink")
    if settings["enabled"]:
        problems = prerequisites(script, config)
        if problems:
            raise ValueError("Cannot enable SnapRAID: " + "; ".join(problems))
        if not Path("/usr/bin/flock").is_file():
            raise ValueError("Missing /usr/bin/flock")
        if subprocess.run(["systemctl", "is-active", "--quiet", "cron"],
                          check=False).returncode:
            raise ValueError("cron service not active")
    return atomic_create_or_replace(path, desired, mode=0o644, marker=MARKER)


def prepare_script(source: Path, digest: str, target: Path = SCRIPT) -> None:
    """Stage reviewed upstream script from a LOCAL file only; no network exec."""
    apply_guard(True)
    if not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        raise ValueError("A trusted SHA256 checksum is required")
    if source.is_symlink() or not source.is_file():
        raise ValueError("Source must be a local regular file")
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest.lower():
        raise ValueError("SHA256 mismatch")
    if b'SNAPSCRIPTVERSION="3.4"' not in content:
        raise ValueError("Only reviewed v3.4 AIO source supported")
    subprocess.run(["bash", "-n", str(source)], check=True)
    if target.parent.is_symlink() or target.parent.exists():
        raise ValueError("Destination already exists; no overwrite")
    # Create a new, private directory containing only the reviewed executable.
    target.parent.mkdir(mode=0o700, parents=True)
    try:
        if target.exists() or target.is_symlink():
            raise ValueError("Script already installed")
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        if not list(target.parent.iterdir()):
            target.parent.rmdir()
        raise
    # Config is deliberately NOT generated, copied or executed. It needs
    # explicit review for file paths, parity, Docker pause lists and secrets.


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="awtserver snapraid",
                                     description="VM-only SnapRAID AIO v3.4 scheduling")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("plan")
    for cmd in ("enable", "disable", "sync"):
        p = sub.add_parser(cmd)
        p.add_argument("--apply", action="store_true")
        p.add_argument("--confirm-vm", action="store_true")
        if cmd == "enable":
            p.add_argument("--schedule", default=DEFAULT["schedule"])
    p = sub.add_parser("prepare")
    p.add_argument("--source", required=True)
    p.add_argument("--sha256", required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--confirm-vm", action="store_true")
    args = parser.parse_args(argv)
    try:
        settings = schedule_from_file()
        if args.command == "status":
            print(json.dumps({"desired_schedule": settings,
                              "installed_cron": safe_existing(CRON, MARKER),
                              "prerequisite_warnings": prerequisites()}, indent=2))
            return 0
        if args.command == "plan":
            print(render_cron(settings), end="")
            return 0
        if args.command == "prepare":
            print(f"Stage verified local v3.4 script from {args.source} to {SCRIPT}.")
            print("No config installed or executed; user must review it separately.")
            if args.apply:
                if not args.confirm_vm:
                    raise ValueError("--confirm-vm required")
                prepare_script(Path(args.source), args.sha256)
            return 0
        if args.command == "enable":
            settings = {"enabled": True, "schedule": args.schedule}
        elif args.command == "disable":
            settings = {"enabled": False, "schedule": settings["schedule"]}
        print(render_cron(settings), end="")
        if not args.apply:
            print("Preview only. No state/cron changed.")
        else:
            if not args.confirm_vm:
                raise ValueError("--confirm-vm required")
            if args.command == "sync":
                changed = sync(settings)
                print("Cron synchronized" if changed else "Cron unchanged")
            else:
                save_settings(settings)
                print("Desired state saved. Run snapraid sync separately to activate.")
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError,
            json.JSONDecodeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
