#!/usr/bin/env python3
"""Compact, read-only awtserver TUI, backed by the same CLI/docs functions."""
from __future__ import annotations

import curses
import json
import sys

import awtserver
import awtserver_cron
import awtserver_docs

# Stable category-first navigation. Only render/read actions exist.
ROOT_ITEMS = (
    ("Status", "doctor"),
    ("Packages", "menu:packages"),
    ("Schedules", "menu:schedules"),
    ("Guides", "menu:guides"),
    ("Quit", "quit"),
)
SUBMENU = {
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
    if action.startswith("doc:"):
        return awtserver_docs.read_topic(action.split(":", 1)[1])
    raise ValueError("Unknown TUI action")


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
    scroll = 0

    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 12 or width < 30:
            safe_line(screen, 0, 0, "Resize terminal: 30x12 minimum", width)
            screen.refresh()
            key = screen.getch()
            if key in (ord("q"), 27):
                return
            continue

        safe_line(screen, 0, 2, "awtserver | Debian Stable", width - 4,
                  curses.A_BOLD)
        safe_line(screen, 1, 2, "CLI-first | read-only navigation", width - 4)

        if detail_title:
            lines = detail.splitlines() or ["(empty)"]
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
                detail_title, detail, scroll = "", "", 0
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
            scroll = 0
            try:
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
