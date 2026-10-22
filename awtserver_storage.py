"""Read-only filesystem, mergerfs and host health inspection for awtserver.

No recursive disk scans, mount operations or drive writes. Results are local
host snapshots, not assertions about a repo's example Docker mounts.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

SKIP_TYPES = frozenset({"proc", "sysfs", "tmpfs", "devtmpfs", "devpts",
                        "cgroup", "cgroup2", "overlay", "squashfs", "nsfs",
                        "tracefs", "debugfs", "securityfs", "pstore",
                        "configfs", "fusectl", "mqueue", "ramfs", "autofs"})
# Do not include filesystem paths from docker /proc mounts in public reports.


def run_json(args: list[str]) -> object:
    if not shutil.which(args[0]):
        raise ValueError(f"Missing tool: {args[0]}")
    p = subprocess.run(args, check=False, text=True, capture_output=True, timeout=15)
    if p.returncode:
        raise ValueError(f"{args[0]} exited with code {p.returncode}")
    return json.loads(p.stdout)


def mount_table() -> list[dict]:
    data = run_json(["findmnt", "--json", "-o", "TARGET,SOURCE,FSTYPE"])
    roots = data.get("filesystems", []) if isinstance(data, dict) else []
    result = []
    def walk(entries: list[dict]) -> None:
        for entry in entries:
            result.append({k: str(entry.get(k) or "") for k in
                           ("target", "source", "fstype")})
            walk(entry.get("children") or [])
    walk(roots)
    return result


def relevant_mounts(mounts: list[dict]) -> list[dict]:
    # Avoid docker pseudo-filesystems and duplicate mountpoints.
    seen: set[str] = set()
    result = []
    for m in mounts:
        target, fstype = m.get("target", ""), m.get("fstype", "")
        if not target.startswith("/") or fstype in SKIP_TYPES:
            continue
        if target.startswith(("/proc/", "/sys/", "/dev/", "/run/")):
            continue
        if target in seen:
            continue
        seen.add(target)
        result.append(m)
    return result


def disk_usage(path: str) -> dict:
    v = os.statvfs(path)
    total = v.f_blocks * v.f_frsize
    # bavail is space available to ordinary users, accounting for reserved blocks.
    available = v.f_bavail * v.f_frsize
    used = (v.f_blocks - v.f_bfree) * v.f_frsize
    percent = round((total - available) * 100 / total, 1) if total else 0.0
    return {"mount": path, "size_bytes": total, "used_bytes": used,
            "available_bytes": available, "used_percent": percent}


def usage_report(threshold: int = 80, mounts: list[dict] | None = None) -> dict:
    if not 1 <= threshold <= 99:
        raise ValueError("Threshold must be 1..99 percent")
    mounts = relevant_mounts(mount_table() if mounts is None else mounts)
    results = []
    failures = []
    for m in mounts:
        path = m["target"]
        try:
            data = disk_usage(path)
        except OSError as exc:
            failures.append({"mount": path, "error": type(exc).__name__})
            continue
        data["fstype"] = m["fstype"]
        data["source"] = m["source"]
        data["alert"] = data["used_percent"] >= threshold
        results.append(data)
    return {"threshold_percent": threshold, "filesystems": results,
            "alerts": [r["mount"] for r in results if r["alert"]],
            "errors": failures, "note": "mergerfs pool and branch usage may overlap"}


def block_devices() -> dict:
    data = run_json(["lsblk", "--json", "-o",
                     "NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,RO,MODEL,TRAN"])
    if not isinstance(data, dict) or not isinstance(data.get("blockdevices"), list):
        raise ValueError("Unexpected lsblk data")
    return data


def pool_report(mounts: list[dict] | None = None) -> dict:
    mounts = mount_table() if mounts is None else mounts
    pools = [m for m in mounts if "mergerfs" in m.get("fstype", "").lower()]
    output = []
    for pool in pools:
        source = pool.get("source", "")
        # Display the fuse source; do not guess which branch paths are active.
        output.append({"mount": pool["target"], "source": source,
                       "fstype": pool["fstype"]})
    return {"pools": output, "note": "Read-only pool discovery; review findmnt and real fstab before any edits"}


def tool_catalog() -> list[dict]:
    tools = (
        ("gdu", "Interactive disk usage (can delete files: use cautiously)"),
        ("ncdu", "Directory size browser (can delete files: use cautiously)"),
        ("duf", "Compact filesystem space table"),
        ("btop", "CPU, RAM, processes and disk I/O"),
        ("smartctl", "SMART inspection (some subcommands start tests)"),
        ("mergerfs.ctl", "Inspect or alter mergerfs branches; inspect only"),
        ("mergerfs.balance", "Moves files among mergerfs branches; not auto-run"),
    )
    return [{"tool": name, "installed": shutil.which(name) is not None,
             "purpose": description} for name, description in tools]


def report_to_text(data: dict) -> str:
    rows = [f"Disk threshold: {data['threshold_percent']}%",
            "Mount                        Used     Available   State"]
    for item in data["filesystems"]:
        used = f"{item['used_percent']:>5.1f}%"
        left = f"{item['available_bytes'] / 1024 ** 3:.1f} GiB"
        state = "ALERT" if item["alert"] else "OK"
        rows.append(f"{item['mount'][:28]:<28} {used:>6} {left:>12}   {state}")
    for item in data["errors"]:
        rows.append(f"{item['mount']}: unable to inspect ({item['error']})")
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="awtserver storage",
                                description="Read-only storage and capacity diagnostics")
    sub = p.add_subparsers(dest="action", required=True)
    use = sub.add_parser("usage")
    use.add_argument("--threshold", type=int, default=80)
    use.add_argument("--json", action="store_true")
    for action in ("disks", "pools", "tools"):
        sub.add_parser(action)
    args = p.parse_args(argv)
    try:
        if args.action == "usage":
            report = usage_report(args.threshold)
            print(json.dumps(report, indent=2) if args.json else report_to_text(report))
            # Exit 2 for threshold breached / incomplete inspection; safe for timers.
            return 2 if report["alerts"] or report["errors"] else 0
        if args.action == "disks":
            out = block_devices()
        elif args.action == "pools":
            out = pool_report()
        else:
            out = tool_catalog()
        print(json.dumps(out, indent=2))
    except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
