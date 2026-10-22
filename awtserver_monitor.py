"""Read-only health summary and optionally email disk-capacity warnings.

No unsolicited emails. Sending is explicitly VM-gated and requires a private
operator-managed config plus a working local MTA. Config never prints secrets.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

import awtserver
import awtserver_storage as storage

DEFAULT_CONFIG = Path("/etc/awtserver/monitor.json")


def system_stats() -> dict:
    mem: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            match = re.fullmatch(r"(MemTotal|MemAvailable):\s+(\d+)\s+kB", line)
            if match:
                mem[match.group(1)] = int(match.group(2)) * 1024
    except OSError:
        pass
    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", 0)
    return {
        "load_1_5_15": [round(v, 2) for v in os.getloadavg()],
        "memory_total_bytes": total,
        "memory_available_bytes": available,
        "memory_used_percent": round((total - available) * 100 / total, 1)
        if total else None,
        "uptime_seconds": round(float(Path("/proc/uptime").read_text().split()[0])),
    }


def read_config(path: Path = DEFAULT_CONFIG) -> dict:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("Config must be an absolute regular file")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError("Config must be root-owned and mode 0600")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {"threshold", "mounts", "recipient"}:
        raise ValueError("Expected threshold, mounts, recipient only")
    if type(value["threshold"]) is not int or not 1 <= value["threshold"] <= 99:
        raise ValueError("Threshold must be integer in 1..99")
    if not isinstance(value["mounts"], list) or not value["mounts"]:
        raise ValueError("At least one mount must be configured")
    if len(value["mounts"]) != len(set(value["mounts"])):
        raise ValueError("Duplicate mounts")
    for mount in value["mounts"]:
        if not isinstance(mount, str) or not mount.startswith("/") or \
           "\n" in mount or ".." in Path(mount).parts:
            raise ValueError("Invalid mount")
    recipient = value["recipient"]
    if not isinstance(recipient, str) or not re.fullmatch(
        r"[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", recipient
    ):
        raise ValueError("Invalid email recipient")
    return value


def capacity_alert(config: dict, mounts: list[dict] | None = None) -> dict:
    report = storage.usage_report(config["threshold"], mounts)
    wanted = set(config["mounts"])
    seen = {m["mount"] for m in report["filesystems"]}
    result = [m for m in report["filesystems"] if m["mount"] in wanted]
    failures = [e for e in report["errors"] if e["mount"] in wanted]
    missing = sorted(wanted - seen - {e["mount"] for e in failures})
    return {"threshold": config["threshold"], "checked": result,
            "over_threshold": [x["mount"] for x in result if x["alert"]],
            "missing_mounts": missing, "failed_mounts": failures,
            "needs_attention": bool(missing or failures or any(x["alert"] for x in result))}


def send_alert(config: dict, result: dict) -> None:
    awtserver.apply_guard(True)
    if not result["needs_attention"]:
        return
    # Use the locally administered Postfix/sendmail-compatible MTA. Never
    # embed SMTP passwords or auth tokens in commands or repository files.
    sendmail = Path("/usr/sbin/sendmail")
    if sendmail.is_symlink() or not sendmail.is_file():
        raise ValueError("Local sendmail-compatible MTA unavailable")
    lines = [f"Disk alert threshold: {result['threshold']}%",
             "Over threshold: " + ", ".join(result["over_threshold"]),
             "Missing mounts: " + ", ".join(result["missing_mounts"]),
             "Unreadable mounts: " +
             ", ".join(x["mount"] for x in result["failed_mounts"])]
    for item in result["checked"]:
        lines.append(f"{item['mount']}: {item['used_percent']}% full")
    message = (f"To: {config['recipient']}\n"
               "Subject: [awtserver] Disk capacity / mount alert\n"
               "Content-Type: text/plain; charset=UTF-8\n\n"
               + "\n".join(lines) + "\n")
    subprocess.run([str(sendmail), "-t", "-oi"], input=message, text=True,
                   check=True, timeout=20)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="awtserver monitor",
                                     description="Host load and 80% disk capacity alerts")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("stats")
    p = sub.add_parser("usage")
    p.add_argument("--threshold", type=int, default=80)
    for action in ("check", "notify"):
        p = sub.add_parser(action)
        p.add_argument("--config", default=str(DEFAULT_CONFIG))
        if action == "notify":
            p.add_argument("--apply", action="store_true")
            p.add_argument("--confirm-vm", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "stats":
            output = system_stats()
            print(json.dumps(output, indent=2))
            return 0
        if args.action == "usage":
            output = storage.usage_report(args.threshold)
            print(storage.report_to_text(output))
            return 2 if output["alerts"] or output["errors"] else 0
        config = read_config(Path(args.config))
        result = capacity_alert(config)
        print(json.dumps(result, indent=2))
        if args.action == "notify" and args.apply:
            if not args.confirm_vm:
                raise ValueError("--confirm-vm required")
            send_alert(config, result)
            print("Alert submitted to local MTA." if result["needs_attention"]
                  else "No alert needed; email not sent.")
        elif args.action == "notify":
            print("Preview only. No email sent.")
        return 2 if result["needs_attention"] else 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
