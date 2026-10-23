"""Bundled short setup guides, shared by the awtserver CLI and TUI.

No subprocesses, downloads, host writes, or mutable config state.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

_CODE_DIR = Path(__file__).resolve().parent
ROOT = _CODE_DIR if (_CODE_DIR / "docs" / "quick").is_dir() else _CODE_DIR.parent
CATALOG = (
    ("Remote access", "remote-tailscale", "Tailscale overview", "remote-tailscale.md"),
    ("Remote access", "remote-apps", "Docker application checklist", "remote-apps.md"),
    ("Remote access", "android-auto", "Android Auto Rules", "android-auto.md"),
    ("Networking", "dns", "Pi-hole and Tailscale DNS", "dns.md"),
    ("Applications", "docker", "Docker safety checklist", "docker.md"),
    ("Storage", "storage", "Disk and SnapRAID safety", "storage.md"),
    ("Storage", "mergerfs", "mergerfs pool tools", "mergerfs.md"),
    ("Storage", "snapraid", "SnapRAID AIO setup", "snapraid.md"),
    ("Maintenance", "jobs", "Scheduled jobs", "jobs.md"),
    ("Maintenance", "recovery-usb", "USB OS recovery", "recovery-usb.md"),
    ("Maintenance", "alerts", "Disk and email alerts", "alerts.md"),
    ("Maintenance", "smart-ups", "SMART and APC UPS", "smart-ups.md"),
)


def entries() -> tuple[tuple[str, str, str, str], ...]:
    return CATALOG


def groups() -> list[tuple[str, list[tuple[str, str]]]]:
    result = []
    for category, key, title, _ in CATALOG:
        if not result or result[-1][0] != category:
            result.append((category, []))
        result[-1][1].append((key, title))
    return result


def index_text() -> str:
    lines = ["awtserver | Quick guides", ""]
    for category, topics in groups():
        lines.append(category)
        lines.extend(f"  {slug:<20} {title}" for slug, title in topics)
        lines.append("")
    lines.append("Open: awtserver docs <topic>")
    return "\n".join(lines) + "\n"


def read_topic(slug: str, root: Path = ROOT) -> str:
    files = {item[1]: item[3] for item in CATALOG}
    if slug not in files:
        raise ValueError(f"Unknown guide '{slug}'. Run: awtserver docs")
    # File selected only from built-in catalog, never a user-provided path.
    path = root / "docs" / "quick" / files[slug]
    if not path.is_file() or path.is_symlink():
        raise ValueError("Guide is unavailable: " + slug)
    return path.read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="awtserver docs", description="Browse compact local server guides")
    parser.add_argument("topic", nargs="?", help="Guide topic shown in the index")
    args = parser.parse_args(argv)
    try:
        text = read_topic(args.topic) if args.topic else index_text()
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(text, end="" if text.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
