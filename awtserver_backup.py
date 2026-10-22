"""Encrypted OS-config backup to verified mounted removable storage in disposable VM.

Production backups and restores need separate, tested authorization. This
module does not format, mount, delete, prune, or overwrite host files.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import os
import shutil
import stat
import subprocess
import sys

from awtserver import apply_guard

DEFAULT_PATHS = ("/etc", "/usr/local", "/opt/awtserver")
REPO_FOLDER = "awtserver-restic"


def exec_capture(args: list[str], timeout: int = 15) -> str:
    p = subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)
    if p.returncode:
        raise ValueError(f"{args[0]} returned {p.returncode}")
    return p.stdout.strip()


def backup_target(mount: str, expected_uuid: str) -> dict:
    p = Path(mount)
    if not p.is_absolute() or not p.is_dir() or p.is_symlink() or ".." in p.parts:
        raise ValueError("Backup destination must be an existing absolute mountpoint")
    if not expected_uuid or not all(ch.isalnum() or ch in "-_" for ch in expected_uuid):
        raise ValueError("Provide the target filesystem UUID explicitly")
    try:
        actual = exec_capture(["findmnt", "-n", "-o", "TARGET", "--target", str(p)])
        # A child path within a mount is not an acceptable USB backup destination.
        if actual != str(p):
            raise ValueError("Target is not a dedicated mountpoint")
        source = exec_capture(["findmnt", "-n", "-o", "SOURCE", "--target", str(p)])
        uuid = exec_capture(["findmnt", "-n", "-o", "UUID", "--target", str(p)])
        fstype = exec_capture(["findmnt", "-n", "-o", "FSTYPE", "--target", str(p)])
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise ValueError("Cannot verify target mount") from exc
    if uuid != expected_uuid:
        raise ValueError("Target UUID mismatch; abort backup")
    if not source.startswith("/dev/") or fstype in ("fuse.mergerfs", "overlay", "tmpfs"):
        raise ValueError("Target must be a separate block-backed filesystem")
    return {"mount": str(p), "filesystem_uuid_matches": True,
            "filesystem": fstype, "repository": str(p / REPO_FOLDER)}


def secrets_file(path: Path) -> None:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("Password file must be an absolute regular path")
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o077:
        raise ValueError("Password file must be root-owned and private")
    if st.st_size < 1:
        raise ValueError("Password file must not be empty")


def backup_plan(mount: str, uuid: str) -> dict:
    target = backup_target(mount, uuid)
    target["included"] = list(DEFAULT_PATHS)
    target["excluded"] = ["Docker/application data (back up separately)",
                          "SnapRAID parity and data disks", "running databases"]
    target["requirements"] = [
        "Dedicated USB disk manually mounted with exact matching UUID",
        "restic repository initialized separately, with verified private password",
        "Snapshot and recovery verification on isolated Debian VM",
        "Off-host copy and separately protected recovery key; no USB formatting"]
    return target


def snapshot(mount: str, uuid: str, password_path: Path) -> None:
    apply_guard(True)
    if not shutil.which("restic"):
        raise ValueError("Install reviewed Debian restic package first")
    target = backup_target(mount, uuid)
    secrets_file(password_path)
    repo = Path(target["repository"])
    if repo.is_symlink() or not repo.is_dir() or not (repo / "config").is_file():
        raise ValueError("Restic repository must already be initialized on verified USB")
    if (repo / "config").is_symlink():
        raise ValueError("Unsafe restic repository configuration")
    # No automatic init, forget, prune, delete or restore.
    env = os.environ.copy()
    # Restic uses local private password file. Do not put passwords in argv/env.
    args = ["restic", "-r", str(repo), "--password-file", str(password_path),
            "backup", "--one-file-system", *DEFAULT_PATHS]
    subprocess.run(args, check=True, env=env)
    subprocess.run(["restic", "-r", str(repo), "--password-file", str(password_path),
                    "snapshots", "--json"], check=True, stdout=subprocess.DEVNULL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="awtserver backup",
                                     description="VM-only guarded encrypted OS backup")
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("plan", "snapshot", "restore-plan"):
        p = sub.add_parser(action)
        p.add_argument("--mount", required=True)
        p.add_argument("--uuid", required=True)
        if action == "snapshot":
            p.add_argument("--password-file", required=True)
            p.add_argument("--apply", action="store_true")
            p.add_argument("--confirm-vm", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = backup_plan(args.mount, args.uuid)
        print(json.dumps(plan, indent=2))
        if args.action == "restore-plan":
            print("Recover only into a separate empty VM/staging root using restic restore")
            print("with --target <new-root>. Inspect files; never restore to / live.")
        elif args.action == "snapshot":
            if args.apply:
                if not args.confirm_vm:
                    raise ValueError("--confirm-vm required")
                snapshot(args.mount, args.uuid, Path(args.password_file))
                print("Snapshot command completed. Restore verification remains required.")
            else:
                print("Preview only. No backup performed.")
    except (ValueError, OSError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
