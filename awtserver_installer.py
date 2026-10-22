#!/usr/bin/env python3
"""Lifecycle for awtserver *program files only* on Debian 12/13.

Installing the CLI does not permit service writes: awtserver.apply_guard is a
separate VM-only gate that is never changed by this installer.
Only /opt/awtserver and /usr/local/bin/awtserver are managed.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request

import awtserver
import awtserver_docs

ROOT = Path(__file__).resolve().parent
TARGET = Path("/opt/awtserver")
LINK = Path("/usr/local/bin/awtserver")
FILES = (
    "awtserver", "awtserver.py", "awtserver_tui.py",
    "awtserver_cron.py", "awtserver_docs.py", "awtserver_installer.py",
    "awtserver_storage.py", "awtserver_snapraid.py", "awtserver_backup.py",
    "awtserver_monitor.py", "awtserver_schedule_review.py",
)
MARKER = ".awtserver-managed.json"
FORMAT = 2
API = "https://api.github.com/repos/dillacorn/awtserver/commits/main"
ARCHIVE = "https://codeload.github.com/dillacorn/awtserver/tar.gz/"
MAX_DOWNLOAD = 20 * 1024 * 1024


def file_list() -> list[Path]:
    return [Path(p) for p in FILES] + [
        Path("docs/quick") / row[3] for row in awtserver_docs.entries()
    ] + [Path("docs/examples/omv-schedules-2026-10-22.json")]


def check_source(source: Path = ROOT) -> None:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Missing or unsafe installer source directory")
    for relative in file_list():
        path = source / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing or unsafe installer source: {relative}")
        if not path.resolve().is_relative_to(source.resolve()):
            raise ValueError("Source escaped repository")
    launcher = (source / "awtserver").read_text(encoding="utf-8")
    if not launcher.startswith("#!/usr/bin/env python3"):
        raise ValueError("Unrecognized awtserver launcher")


def command_install_guard() -> None:
    """Permits installing ONLY these program files on Debian Stable / OMV."""
    if os.geteuid() != 0:
        raise ValueError("Command installation requires root")
    info = awtserver.parse_os_release()
    if info.get("ID") != "debian" or info.get("VERSION_ID") not in ("12", "13"):
        raise ValueError("Command installation requires Debian 12 or 13")
    # Crucial: this does not invoke, patch or disable apply_guard().
    # Mutating service commands remain disposable-Debian-13-VM-only.


def checked_parent(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Unsafe installer parent directory")
    st = path.stat()
    if st.st_uid != 0 or st.st_mode & 0o022:
        raise ValueError("Installer parent must be root-owned and not group-writable")


def target_is_clear(dest: Path = TARGET, command: Path = LINK) -> None:
    if os.path.lexists(dest) or os.path.lexists(command):
        raise ValueError("Existing installation or command found; refusing overwrite")
    checked_parent(dest.parent)
    checked_parent(command.parent)


def manifest_for(source: Path, revision: str = "local") -> dict:
    return {
        "format": FORMAT,
        "revision": revision,
        "files": {
            str(p): hashlib.sha256((source / p).read_bytes()).hexdigest()
            for p in file_list()
        },
    }


def checked_install(dest: Path = TARGET, command: Path = LINK) -> dict:
    """Reject foreign files, modifications, symlinks and redirected commands."""
    checked_parent(dest.parent)
    checked_parent(command.parent)
    if dest.is_symlink() or not dest.is_dir():
        raise ValueError("No verified awtserver installation")
    if not command.is_symlink() or os.readlink(command) != str(dest / "awtserver"):
        raise ValueError("Command does not point to the managed installation")
    marker = dest / MARKER
    if marker.is_symlink() or not marker.is_file() or marker.stat().st_uid != 0:
        raise ValueError("Missing or unsafe managed installation marker")
    data = json.loads(marker.read_text(encoding="utf-8"))
    expected = {str(p) for p in file_list()}
    if (not isinstance(data, dict) or set(data) != {"format", "revision", "files"}
            or data["format"] != FORMAT or not isinstance(data["revision"], str)
            or not isinstance(data["files"], dict)
            or set(data["files"]) != expected):
        raise ValueError("Unsupported or modified installation manifest")
    # Do not delete or replace directories containing user-added files.
    actual_files = set()
    for path in dest.rglob("*"):
        if path.is_symlink():
            raise ValueError("Symlink in managed installation; refusing changes")
        rel = str(path.relative_to(dest))
        if path.is_file():
            actual_files.add(rel)
            if path.stat().st_uid != 0:
                raise ValueError("Non-root file in managed installation")
        elif not path.is_dir():
            raise ValueError("Unexpected installation entry")
    if actual_files != expected | {MARKER}:
        raise ValueError("Modified or foreign installation files; refusing changes")
    for rel, digest in data["files"].items():
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid managed file hash")
        if hashlib.sha256((dest / rel).read_bytes()).hexdigest() != digest:
            raise ValueError("Installed program file changed; refusing overwrite")
    return data


def write_stage(source: Path, parent: Path, revision: str = "local") -> Path:
    check_source(source)
    stage = Path(tempfile.mkdtemp(prefix=".awtserver-stage-", dir=parent))
    try:
        for rel in file_list():
            path = stage / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / rel, path, follow_symlinks=False)
            path.chmod(0o755 if str(rel) == "awtserver" else 0o644)
        marker = stage / MARKER
        marker.write_text(json.dumps(manifest_for(stage, revision), sort_keys=True) + "\n",
                          encoding="utf-8")
        marker.chmod(0o644)
        stage.chmod(0o755)
        return stage
    except Exception:
        shutil.rmtree(stage)
        raise


def remove_verified_tree(dest: Path, data: dict) -> None:
    """Unlink only files explicitly recorded in a validated manifest."""
    for rel in data["files"]:
        (dest / rel).unlink()
    (dest / MARKER).unlink()
    directories = sorted((p for p in dest.rglob("*") if p.is_dir()),
                         key=lambda p: len(p.parts), reverse=True)
    for path in directories:
        path.rmdir()  # fail rather than remove any unexpected content
    dest.rmdir()


def install(source: Path = ROOT, dest: Path = TARGET,
            command: Path = LINK, revision: str = "local") -> None:
    command_install_guard()
    check_source(source)
    target_is_clear(dest, command)
    stage = write_stage(source, dest.parent, revision)
    placed = False
    try:
        target_is_clear(dest, command)
        stage.rename(dest)
        placed = True
        try:
            command.symlink_to(dest / "awtserver")
        except Exception:
            # No pre-existing installation: safe to roll back only known files.
            # Do not delete an unexpected foreign entry if one raced in.
            if not os.path.lexists(command):
                data = json.loads((dest / MARKER).read_text())
                remove_verified_tree(dest, data)
            raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def update(source: Path, dest: Path = TARGET, command: Path = LINK,
           revision: str = "local") -> bool:
    command_install_guard()
    old = checked_install(dest, command)
    check_source(source)
    new = manifest_for(source, revision)
    if old["files"] == new["files"]:
        return False
    stage = write_stage(source, dest.parent, revision)
    rollback = Path(tempfile.mkdtemp(prefix=".awtserver-previous-", dir=dest.parent))
    rollback.rmdir()  # reserve unique name without overwriting any other path
    moved = False
    try:
        # Only a verified owned tree may be renamed.
        checked_install(dest, command)
        dest.rename(rollback)
        moved = True
        try:
            stage.rename(dest)
        except Exception:
            rollback.rename(dest)
            moved = False
            raise
        # New version is live; previous files are strictly verified managed
        # files. Preserve them if deletion fails rather than deleting foreign data.
        remove_verified_tree(rollback, old)
        moved = False
        return True
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if moved and rollback.exists():
            # Preserve rollback for manual recovery rather than deleting data.
            print(f"Previous verified program files retained: {rollback}", file=sys.stderr)


def uninstall(dest: Path = TARGET, command: Path = LINK) -> None:
    command_install_guard()
    data = checked_install(dest, command)
    # Only code recorded in the exact manifest, never /etc, /var/lib or
    # app data. Delete command last.
    remove_verified_tree(dest, data)
    if command.is_symlink() and os.readlink(command) == str(dest / "awtserver"):
        command.unlink()


def _download(url: str, max_bytes: int = MAX_DOWNLOAD) -> bytes:
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "awtserver-cli"}),
        timeout=25,
    ) as response:
        length = response.read(max_bytes + 1)
    if len(length) > max_bytes:
        raise ValueError("Remote source exceeds download limit")
    return length


def fetch_main(source_root: Path) -> tuple[Path, str]:
    """Resolve main to a SHA, fetch a SHA-pinned archive, extract allowlist."""
    commit = json.loads(_download(API, max_bytes=500_000).decode("utf-8"))["sha"]
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Invalid GitHub source revision")
    payload = _download(ARCHIVE + commit)
    source = source_root / "checkout"
    source.mkdir()
    required = {str(p) for p in file_list()}
    found = set()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for entry in archive:
            parts = Path(entry.name).parts
            if len(parts) < 2:
                continue
            relative = Path(*parts[1:])
            if str(relative) not in required:
                continue
            if not entry.isfile() or entry.issym() or entry.islnk():
                raise ValueError("Unsafe downloaded source file")
            if entry.size > 1_000_000:
                raise ValueError("Oversized downloaded source file")
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(entry) as stream, target.open("xb") as output:
                shutil.copyfileobj(stream, output)
            found.add(str(relative))
    if found != required:
        raise ValueError("Downloaded source is incomplete")
    check_source(source)
    return source, commit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="awtserver installer",
        description="Manage only awtserver CLI files (no server service changes)")
    parser.add_argument("operation", choices=("install", "update", "uninstall", "status"),
                        nargs="?", default="install")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-vm", action="store_true",
                        help="Legacy option; service writes remain VM-only")
    args = parser.parse_args(argv)
    try:
        if args.operation == "status":
            data = checked_install()
            print(f"Installed revision: {data['revision']}")
            return 0
        print(f"Action: {args.operation}; managed files only: {TARGET}, {LINK}")
        if not args.apply:
            if args.operation == "install":
                check_source()
            print("Preview only. No files changed.")
            return 0
        if args.operation == "install":
            install()
            print("Installed awtserver command.")
        elif args.operation == "uninstall":
            uninstall()
            print("Removed awtserver program only. Server data and configuration remain.")
        else:
            with tempfile.TemporaryDirectory(prefix="awtserver-fetch-") as temp:
                source, revision = fetch_main(Path(temp))
                changed = update(source, revision=revision)
                print("Updated awtserver command." if changed else "Already up to date.")
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError,
            tarfile.TarError, urllib.error.URLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
