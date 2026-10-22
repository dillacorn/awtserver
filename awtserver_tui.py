#!/usr/bin/env python3
"""Compact, read-only awtserver TUI, backed by the same CLI/docs functions."""
from __future__ import annotations

import curses
import json
import re
import shutil
import subprocess
import sys
import textwrap

import awtserver
import awtserver_cron
import awtserver_docs
import awtserver_storage
import awtserver_snapraid
import awtserver_monitor
import awtserver_schedule_review

# Stable category-first navigation. Only render/read actions exist.
ROOT_ITEMS = (
    ("Status", "menu:status"),
    ("Storage", "menu:storage"),
    ("SnapRAID", "menu:snapraid"),
    ("Maintenance", "menu:maintenance"),
    ("Packages", "menu:packages"),
    ("Guides", "menu:guides"),
    ("Quit", "quit"),
)
SUBMENU = {
    "status": (("Host health", "doctor"), ("CPU and memory", "stats"),
               ("Disk alerts at 80%", "storage:usage")),
    "storage": (("Disk space", "storage:usage"),
                ("Drive list", "storage:disks"),
                ("mergerfs pools", "storage:pools"),
                ("Available tools", "storage:tools"),
                ("gdu (no deletion)", "launch:gdu"),
                ("ncdu (read only)", "launch:ncdu")),
    "snapraid": (("AIO status and prerequisites", "snapraid:status"),
                 ("Schedule preview", "snapraid:plan"),
                 ("Setup instructions", "doc:snapraid")),
    "maintenance": (("Scheduled jobs", "menu:schedules"),
                    ("USB backup and recovery", "doc:recovery-usb"),
                    ("Capacity emails", "doc:alerts"),
                    ("UPS and SMART", "doc:smart-ups")),
    "packages": (("Package profiles", "profiles"), ("Install plan", "plan")),
    "schedules": (("Saved jobs", "jobs"), ("Cron changes", "cron")),
}
ITEMS = ROOT_ITEMS  # backwards-compatible menu metadata for existing callers


def menu_for(section: str) -> tuple[tuple[str, str], ...]:
    if section == "root":
        return ROOT_ITEMS
    if section in SUBMENU:
        return SUBMENU[section]
    if section == "guides":
        return tuple((category, "menu:guide:" + category)
                     for category, _ in awtserver_docs.groups())
    if section.startswith("guide:"):
        cat = section.split(":", 1)[1]
        for category, topics in awtserver_docs.groups():
            if category == cat:
                return tuple((title, "doc:" + slug) for slug, title in topics)
    raise ValueError("Unknown menu section")


def next_selection(index: int, key: int, count: int) -> int:
    if key in (curses.KEY_DOWN, ord("j")):
        return (index + 1) % count
    if key in (curses.KEY_UP, ord("k")):
        return (index - 1) % count
    return index


def get_details(action: str) -> str:
    """Model for read-only views; no commands that change the host."""
    if action == "stats":
        return json.dumps(awtserver_monitor.system_stats(), indent=2)
    if action == "doctor":
        return json.dumps(awtserver.doctor_snapshot(), indent=2)
    if action == "profiles":
        return json.dumps(awtserver.PROFILES, indent=2)
    if action == "plan":
        return json.dumps(awtserver.profile_plan(list(awtserver.DEFAULT_PROFILES)),
                          indent=2)
    if action == "jobs":
        return json.dumps({"desired_jobs": awtserver.load_jobs(),
                           "note": "Enabled is desired state, not activation"},
                          indent=2)
    if action == "cron":
        return awtserver_cron.preview_cron(awtserver.load_jobs())
    if action == "storage:usage":
        return awtserver_storage.report_to_text(awtserver_storage.usage_report(80))
    if action == "storage:disks":
        return json.dumps(awtserver_storage.block_devices(), indent=2)
    if action == "storage:pools":
        return json.dumps(awtserver_storage.pool_report(), indent=2)
    if action == "storage:tools":
        return json.dumps(awtserver_storage.tool_catalog(), indent=2)
    if action == "snapraid:status":
        return json.dumps({"schedule": awtserver_snapraid.schedule_from_file(),
                           "warnings": awtserver_snapraid.prerequisites()}, indent=2)
    if action == "snapraid:plan":
        return awtserver_snapraid.render_cron(awtserver_snapraid.schedule_from_file())
    if action.startswith("doc:"):
        return awtserver_docs.read_topic(action.split(":", 1)[1])
    raise ValueError("Unknown TUI action")


def detail_lines(detail: str, columns: int, *, markdown: bool = False) -> list[str]:
    """Wrap long guides rather than silently hiding right-hand text on SSH."""
    result = []
    width = max(14, columns - 6)
    for line in detail.splitlines():
        if markdown:
            # Links remain accessible through the complete CLI guide. A narrow
            # TUI should show readable instructions, not opaque long URLs.
            line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
            line = line.replace("**", "").replace(chr(96), "")
            line = line.lstrip("#").lstrip() if line.startswith("#") else line
        if not line.strip():
            result.append("")
            continue
        match = re.match(r"^(\s*(?:\d+\.\s+|[-*]\s+))", line)
        initial = match.group(0) if match else ""
        rest = line[len(initial):]
        lines = textwrap.wrap(rest, width=max(10, width - len(initial)),
                              break_long_words=True, break_on_hyphens=False)
        if not lines:
            result.append(initial)
        else:
            result.append(initial + lines[0])
            result.extend(" " * len(initial) + part for part in lines[1:])
    return result or ["(empty)"]


def launch_tool(action: str, screen) -> str:
    """Explicit terminal-only tool switch, never a command string or shell."""
    allowed = {
        "gdu": ["gdu", "--no-delete", "--no-spawn-shell",
                "--no-view-file", "--no-cross", "/"],
        "ncdu": ["ncdu", "-rr", "-x", "/"],
    }
    if action not in allowed:
        raise ValueError("Unknown external tool")
    argv = allowed[action]
    if not shutil.which(argv[0]):
        return f"{argv[0]} is not installed. Select the optional tooling package profile."
    curses.def_prog_mode()
    curses.endwin()
    try:
        result = subprocess.run(argv, check=False)
        return f"{argv[0]} finished with status {result.returncode}"
    finally:
        curses.reset_prog_mode()
        screen.clear()
        screen.refresh()


def safe_line(screen, row: int, col: int, text: str, width: int,
              attribute: int = 0) -> None:
    height, columns = screen.getmaxyx()
    if row < 0 or row >= height or col >= columns or width < 1:
        return
    try:
        screen.addnstr(row, col, text, max(0, min(width, columns - col - 1)),
                       attribute)
    except curses.error:
        pass


def run_ui(screen) -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass  # Some real SSH terminals do not support cursor visibility.
    screen.keypad(True)
    stack: list[tuple[str, int]] = [("root", 0)]
    detail_title = ""
    detail = ""
    markdown_detail = False
    scroll = 0

    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 14 or width < 30:
            safe_line(screen, 0, 0, "Resize terminal: 30x14 minimum", width)
            screen.refresh()
            key = screen.getch()
            if key in (ord("q"), 27):
                return
            continue

        safe_line(screen, 0, 2, "awtserver | Debian Stable", width - 4,
                  curses.A_BOLD)
        safe_line(screen, 1, 2, "CLI-first | read-only navigation", width - 4)

        if detail_title:
            lines = detail_lines(detail, width, markdown=markdown_detail)
            safe_line(screen, 3, 2, detail_title, width - 4, curses.A_BOLD)
            count = max(1, height - 7)
            scroll = max(0, min(scroll, max(0, len(lines) - count)))
            for line_index, line in enumerate(lines[scroll:scroll + count]):
                safe_line(screen, 5 + line_index, 2, line, width - 4)
            help_line = "Up/Down scroll | Esc/h back | q quit"
        else:
            section, selected = stack[-1]
            items = menu_for(section)
            safe_line(screen, 3, 2, section.replace("guide:", ""), width - 4,
                      curses.A_BOLD)
            for index, (label, _) in enumerate(items):
                prefix = "> " if index == selected else "  "
                safe_line(screen, 5 + index, 2, prefix + label, width - 4,
                          curses.A_REVERSE if index == selected else 0)
            help_line = "Up/Down select | Enter open | Esc back | q quit"
        safe_line(screen, height - 2, 2, help_line, width - 4)
        screen.refresh()

        key = screen.getch()
        if key == ord("q"):
            return
        if detail_title:
            if key in (27, ord("h"), curses.KEY_BACKSPACE):
                detail_title, detail, scroll, markdown_detail = "", "", 0, False
            elif key in (curses.KEY_DOWN, ord("j")):
                scroll += 1
            elif key in (curses.KEY_UP, ord("k")):
                scroll = max(0, scroll - 1)
            elif key == curses.KEY_NPAGE:
                scroll += max(1, height - 7)
            elif key == curses.KEY_PPAGE:
                scroll = max(0, scroll - max(1, height - 7))
            continue

        section, selected = stack[-1]
        items = menu_for(section)
        if key in (27, ord("h"), curses.KEY_BACKSPACE):
            if len(stack) > 1:
                stack.pop()
            continue
        next_index = next_selection(selected, key, len(items))
        if next_index != selected:
            stack[-1] = (section, next_index)
        if key in (10, 13, curses.KEY_ENTER, ord("l")):
            label, action = items[stack[-1][1]]
            if action == "quit":
                return
            if action.startswith("menu:"):
                stack.append((action.split(":", 1)[1], 0))
                continue
            detail_title = label
            markdown_detail = action.startswith("doc:")
            scroll = 0
            try:
                if action.startswith("launch:"):
                    detail = launch_tool(action.split(":", 1)[1], screen)
                else:
                    detail = get_details(action)
            except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
                detail = f"Unable to read: {error}"


def main() -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("awtserver TUI requires an interactive terminal (SSH/TTY).",
              file=sys.stderr)
        return 2
    try:
        curses.wrapper(run_ui)
    except (curses.error, KeyboardInterrupt) as error:
        if isinstance(error, curses.error):
            print(f"Terminal UI unavailable: {error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
