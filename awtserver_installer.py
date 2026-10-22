#!/usr/bin/env python3
"""First-install-only VM installer for the awtserver terminal command.

Safeguard: refuses overwrite, updates, uninstall, real hosts and OMV.
The installer never touches Docker, networking, APT, storage or cron.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

import awtserver
import awtserver_docs

ROOT = Path(__file__).resolve().parent
TARGET = Path("/opt/awtserver")
LINK = Path("/usr/local/bin/awtserver")
FILES = (
    "awtserver",
    "awtserver.py",
    "awtserver_tui.py",
    "awtserver_cron.py",
    "awtserver_docs.py",
    "awtserver_installer.py",
    "awtserver_storage.py",
    "awtserver_snapraid.py",
    "awtserver_backup.py",
    "awtserver_monitor.py",
    "awtserver_schedule_review.py",
)
MARKER = ".awtserver-managed-v1"


def file_list() -> list[Path]:
    return [Path(p) for p in FILES] + [
        Path("docs/quick") / entry[3] for entry in awtserver_docs.entries()
    ] + [Path("docs/examples/omv-schedules-2026-10-22.json")]


def check_source(source: Path = ROOT) -> None:
    for relative in file_list():
        path = source / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing or unsafe installer source: {relative}")
        if not path.resolve().is_relative_to(source.resolve()):
            raise ValueError("Source escaped repository")
    if not (source / "awtserver").read_text(encoding="utf-8").startswith("#!/usr/bin/env python3"):
        raise ValueError("Unrecognized awtserver launcher")


def target_is_clear(dest: Path = TARGET, command: Path = LINK) -> None:
    if os.path.lexists(dest) or os.path.lexists(command):
        raise ValueError("Existing installation or command found; refusing to overwrite")
    if dest.parent.is_symlink() or command.parent.is_symlink():
        raise ValueError("Install parent is a symlink")
    if not dest.parent.is_dir() or not command.parent.is_dir():
        raise ValueError("Install parent directory missing")
    for parent in (dest.parent, command.parent):
        meta = parent.stat()
        if meta.st_uid != 0 or meta.st_mode & 0o022:
            raise ValueError("Unsafe installer destination parent")


def install(source: Path = ROOT, dest: Path = TARGET,
            command: Path = LINK) -> None:
    """No replace/update paths: a clean VM-only install, never a hidden upgrade."""
    awtserver.apply_guard(True)
    check_source(source)
    target_is_clear(dest, command)
    stage = Path(tempfile.mkdtemp(prefix=".awtserver-stage-", dir=dest.parent))
    placed = False
    try:
        for relative in file_list():
            target = stage / relative
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            shutil.copyfile(source / relative, target, follow_symlinks=False)
            target.chmod(0o755 if relative == Path("awtserver") else 0o644)
        (stage / MARKER).write_text("awtserver VM-only command installation\n",
                                    encoding="utf-8")
        (stage / MARKER).chmod(0o644)
        stage.chmod(0o755)
        target_is_clear(dest, command)
        stage.rename(dest)
        placed = True
        command.symlink_to(dest / "awtserver")
    except Exception:
        if placed and not os.path.lexists(command):
            # Roll back only the directory created by this one-shot installer.
            # Never delete an existing installation; preflight rejects one.
            shutil.rmtree(dest)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="awtserver installer",
        description="One-shot awtserver command install for disposable Debian 13 VMs")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-vm", action="store_true")
    args = parser.parse_args(argv)
    try:
        check_source()
        print("Files:", ", ".join(str(p) for p in file_list()))
        print(f"Target: {TARGET}; command: {LINK}")
        if not args.apply:
            print("Preview only. No files changed.")
        else:
            if not args.confirm_vm:
                raise ValueError("Explicit --confirm-vm required")
            install()
            print("Installed. Run: awtserver")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
