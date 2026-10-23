"""Read-only review of sanitized scheduled-job inventories.

This is *not* an importer. It never reads OMV command bodies, never runs jobs,
never writes cron files, and never treats audit examples as deployment state.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
import sys

CATEGORIES = frozenset(("backup", "snapraid", "docker-maintenance", "rsync"))
KINDS = frozenset(("omv-custom", "omv-rsync"))
TIMING_RE = re.compile(r"^(?:[0-9]{1,2}|\*)(?:[,-][0-9]{1,2})*(?:/[0-9]{1,2})?$")
_CODE_DIR = Path(__file__).resolve().parent
_SOURCE_ROOT = _CODE_DIR if (_CODE_DIR / "docs" / "examples").is_dir() else _CODE_DIR.parent
DEFAULT_AUDIT = _SOURCE_ROOT / "docs" / "examples" / "omv-schedules-2026-10-22.json"


def validate_inventory(data: object) -> list[dict]:
    if not isinstance(data, dict) or set(data) != {"source", "status", "jobs"}:
        raise ValueError("Expected sanitized source/status/jobs inventory")
    if data["status"] != "historical-audit" or not isinstance(data["source"], str):
        raise ValueError("Only explicitly marked historical audit input supported")
    jobs = data["jobs"]
    if not isinstance(jobs, list) or len(jobs) > 80:
        raise ValueError("Invalid job inventory length")
    result = []
    ids = set()
    for item in jobs:
        if not isinstance(item, dict) or set(item) != {
            "id", "kind", "category", "enabled", "schedule", "email"
        }:
            raise ValueError("Unknown/unsafe inventory fields (commands are forbidden)")
        ident = item["id"]
        if not isinstance(ident, str) or not re.fullmatch(r"[a-z0-9_-]{1,40}", ident):
            raise ValueError("Invalid job ID")
        if ident in ids:
            raise ValueError("Duplicate job ID")
        ids.add(ident)
        if item["kind"] not in KINDS or item["category"] not in CATEGORIES:
            raise ValueError("Unrecognized job kind/category")
        if type(item["enabled"]) is not bool or type(item["email"]) is not bool:
            raise ValueError("Expected explicit enabled/email booleans")
        schedule = item["schedule"]
        if schedule != "@weekly":
            if not isinstance(schedule, str) or len(schedule.split()) != 5:
                raise ValueError("Expected five-field cron schedule or @weekly")
            ranges = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
            for field, (low, high) in zip(schedule.split(), ranges):
                if not TIMING_RE.fullmatch(field):
                    raise ValueError("Invalid schedule field")
                # Use strict numeric syntax for inventory: *, N, N-M, N,N.
                if not re.fullmatch(r"\*|[0-9]{1,2}|[0-9]{1,2}-[0-9]{1,2}", field):
                    raise ValueError("Unsupported schedule field")
                nums = [int(n) for n in re.findall(r"[0-9]+", field)]
                if any(n < low or n > high for n in nums) or (
                    len(nums) == 2 and nums[1] < nums[0]
                ):
                    raise ValueError("Out-of-range schedule")
        result.append(item)
    return result


def load_inventory(path: Path = DEFAULT_AUDIT) -> tuple[dict, list[dict]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Inventory must be an existing regular, non-symlink file")
    if path.stat().st_size > 100_000:
        raise ValueError("Inventory exceeds maximum supported size")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data, validate_inventory(data)


def next_occurrences(schedule: str, start: date, days: int) -> list[datetime]:
    """Only precise five-field schedules; no assumptions about @weekly."""
    if schedule == "@weekly":
        return []
    minute, hour, dom, month, dow = schedule.split()
    def matches(field: str, value: int) -> bool:
        if field == "*":
            return True
        if "-" in field:
            a, b = (int(x) for x in field.split("-"))
            return a <= value <= b
        return int(field) == value
    points = []
    for offset in range(days):
        d = start + timedelta(days=offset)
        # Python Monday=0, POSIX Sunday=0/7.
        weekday = (d.weekday() + 1) % 7
        days_match = matches(dom, d.day)
        dow_match = matches(dow, weekday) or (weekday == 0 and dow == "7")
        # Cron OR semantics when both day-of-month and weekday restricted.
        either_restricted = dom != "*" and dow != "*"
        if not (matches(month, d.month) and
                ((days_match or dow_match) if either_restricted else
                 (days_match and dow_match))):
            continue
        points.append(datetime(d.year, d.month, d.day, int(hour), int(minute)))
    return points


def review(jobs: list[dict], *, gap_minutes: int = 60,
           start: date = date(2026, 10, 22), days: int = 400) -> dict:
    if not 1 <= gap_minutes <= 1440:
        raise ValueError("Gap must be 1..1440 minutes")
    if not 1 <= days <= 730:
        raise ValueError("Review period must be 1..730 days")
    enabled = [j for j in jobs if j["enabled"]]
    dormant = [j["id"] for j in jobs if not j["enabled"]]
    occurrences = []
    unresolved = []
    for job in enabled:
        if job["schedule"] == "@weekly":
            unresolved.append(job["id"])
            continue
        for when in next_occurrences(job["schedule"], start, days):
            occurrences.append((when, job["id"]))
    occurrences.sort()
    warnings = {}
    for i, (when, ident) in enumerate(occurrences):
        # Nearby different jobs are *possible* overlaps, not confirmed overlaps.
        j = i + 1
        while j < len(occurrences):
            later, other = occurrences[j]
            minutes = int((later - when).total_seconds() / 60)
            if minutes >= gap_minutes:
                break
            if other != ident:
                ids = tuple(sorted((ident, other)))
                key = (ids, minutes)
                if key not in warnings:
                    warnings[key] = {"jobs": list(ids),
                                     "gap_minutes": minutes,
                                     "example": when.strftime("%Y-%m-%d %H:%M")}
            j += 1
    return {
        "audit_only": True, "writes_or_schedule_imports": False,
        "jobs_total": len(jobs), "enabled": len(enabled),
        "disabled_job_ids": dormant, "emails_enabled": sum(j["email"] for j in enabled),
        "weekly_macro_unresolved": unresolved,
        "schedule_gap_threshold_minutes": gap_minutes,
        "possible_gaps": sorted(warnings.values(),
                               key=lambda x: (x["gap_minutes"], x["jobs"])),
        "warnings": [
            "Schedules do not prove successful execution or backup integrity",
            "Gap detection cannot prove a conflict without job runtime/locking evidence",
            "Weekly @weekly expansion must be verified against the deployed cron implementation",
            "No commands, users, paths, secrets, or job configurations are imported",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="awtserver schedules",
                                     description="Read-only historical OMV schedule review")
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("list", "review"):
        p = sub.add_parser(action)
        p.add_argument("--input", type=Path, default=DEFAULT_AUDIT)
        if action == "review":
            p.add_argument("--min-gap", type=int, default=60)
    args = parser.parse_args(argv)
    try:
        info, jobs = load_inventory(args.input)
        if args.action == "list":
            output = {"source": info["source"], "historical": True,
                      "jobs": jobs, "note": "Not active cron state or a deployment plan"}
        else:
            output = review(jobs, gap_minutes=args.min_gap)
            output["source"] = info["source"]
        print(json.dumps(output, indent=2))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
