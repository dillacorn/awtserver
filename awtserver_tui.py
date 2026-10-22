#!/usr/bin/env python3
"""Read-only awtserver terminal navigator.

No sudo, no external dependencies beyond Python's curses module, no writes.
All actions call the same pure/read-only backend functions as the CLI.
"""
from __future__ import annotations

import curses
import json
import sys

import awtserver
import awtserver_cron


ITEMS = (
    ("System diagnostics", "doctor"),
    ("Package profiles", "profiles"),
    ("Default installation plan", "plan"),
    ("Saved scheduled jobs", "jobs"),
    ("Managed cron preview", "cron"),
    ("Quit", "quit"),
)


def next_selection(index: int, key: int, count: int) -> int:
    if key in (curses.KEY_DOWN, ord("j")):
        return (index + 1) % count
    if key in (curses.KEY_UP, ord("k")):
        return (index - 1) % count
    return index


def get_details(action: str) -> str:
    """Read-only operations, reusable and unit testable without curses."""
    if action == "doctor":
        return json.dumps(awtserver.doctor_snapshot(), indent=2)
    if action == "profiles":
        return json.dumps(awtserver.PROFILES, indent=2)
    if action == "plan":
        return json.dumps(awtserver.profile_plan(list(awtserver.DEFAULT_PROFILES)), indent=2)
    if action == "jobs":
        return json.dumps({"desired_jobs": awtserver.load_jobs(),
                           "note": "Enabled here does not imply scheduled or running"}, indent=2)
    if action == "cron":
        return awtserver_cron.preview_cron(awtserver.load_jobs())
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
    curses.curs_set(0)
    screen.keypad(True)
    selection = 0
    action = ""
    scroll = 0
    detail = ""
    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 12 or width < 30:
            safe_line(screen, 0, 0, "Enlarge terminal (30x12 minimum)", width)
            screen.refresh()
            key = screen.getch()
            if key in (ord("q"), 27):
                return
            continue
        safe_line(screen, 0, 2, "awtserver | Debian Stable", width - 4,
                  curses.A_BOLD)
        safe_line(screen, 1, 2, "SSH-first management | READ ONLY", width - 4)
        if not action:
            for index, (label, _) in enumerate(ITEMS):
                prefix = "> " if index == selection else "  "
                safe_line(screen, 3 + index, 2, prefix + label, width - 4,
                          curses.A_REVERSE if index == selection else 0)
            safe_line(screen, height - 2, 2,
                      "Arrows/j/k select | Enter open | q quit", width - 4)
        else:
            lines = detail.splitlines() or ["(empty)"]
            safe_line(screen, 3, 2, action, width - 4, curses.A_BOLD)
            count = max(1, height - 7)
            scroll = max(0, min(scroll, max(0, len(lines) - count)))
            for line_index, item in enumerate(lines[scroll:scroll + count]):
                safe_line(screen, line_index + 5, 2, item, width - 4)
            safe_line(screen, height - 2, 2,
                      "Arrows/j/k scroll | Esc/h back | q quit", width - 4)
        screen.refresh()
        key = screen.getch()
        if key == ord("q"):
            return
        if not action:
            selection = next_selection(selection, key, len(ITEMS))
            if key in (10, 13, curses.KEY_ENTER, ord("l")):
                label, selected_action = ITEMS[selection]
                if selected_action == "quit":
                    return
                action = label
                scroll = 0
                try:
                    detail = get_details(selected_action)
                except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
                    detail = f"Unable to read data: {error}"
        elif key in (27, ord("h"), curses.KEY_BACKSPACE):
            action = ""
        elif key in (curses.KEY_DOWN, ord("j")):
            scroll += 1
        elif key in (curses.KEY_UP, ord("k")):
            scroll = max(0, scroll - 1)
        elif key == curses.KEY_NPAGE:
            scroll += max(1, height - 7)
        elif key == curses.KEY_PPAGE:
            scroll = max(0, scroll - max(1, height - 7))


def main() -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("awtserver TUI requires an interactive terminal (SSH or TTY).",
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
