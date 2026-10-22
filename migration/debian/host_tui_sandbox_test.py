#!/usr/bin/env python3
"""Unprivileged OMV TUI/action integration validation, NEVER a deployment tool.

Invoke only as an unprivileged user with AWTSERVER_SANDBOX_TEST=1.
This runner does not accept --apply, writable target paths, or commands.
It runs isolated unit tests (some mock VM write guards *only* for temporary
files), then invokes every safe read-only TUI leaf on this actual host.
It deliberately does NOT launch gdu/ncdu, cron, SnapRAID, mail or restic.
"""
from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import sys
import unittest


def walk(menu, section="root"):
    for label, action in menu.menu_for(section):
        if action == "quit":
            continue
        if action.startswith("menu:"):
            yield from walk(menu, action.split(":", 1)[1])
        else:
            yield label, action


def main() -> int:
    if os.geteuid() == 0:
        print("REFUSED: host test cannot run as root", file=sys.stderr)
        return 2
    if os.environ.get("AWTSERVER_SANDBOX_TEST") != "1":
        print("REFUSED: AWTSERVER_SANDBOX_TEST=1 required", file=sys.stderr)
        return 2

    root = Path(__file__).resolve().parents[2]
    if not root.is_dir() or not (root / "awtserver_tui.py").is_file():
        print("REFUSED: source tree not found", file=sys.stderr)
        return 2
    sys.path.insert(0, str(root))
    import awtserver_tui as tui
    import awtserver as cli

    print("===== HOST READ-ONLY / TEMP-WRITE VALIDATION =====")
    if not Path("/etc/openmediavault").exists():
        print("REFUSED: test is designed for the existing OMV host", file=sys.stderr)
        return 2
    try:
        cli.apply_guard(True)
    except ValueError:
        print("PASS: real host write gate denies authorization")
    else:
        print("FAIL: production write gate unexpectedly accepted")
        return 1

    capture = io.StringIO()
    with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
        suite = unittest.defaultTestLoader.discover(
            start_dir=str(root / "tests"), pattern="test_awtserver*.py",
            top_level_dir=str(root),
        )
        result = unittest.TextTestRunner(stream=capture, verbosity=1).run(suite)
    print(f"Unit / sandbox tests: {result.testsRun} run; "
          f"{len(result.failures)} failures; {len(result.errors)} errors; "
          f"{len(result.skipped)} skipped")
    if not result.wasSuccessful() or result.skipped or result.testsRun < 90:
        print("FAIL: test suite incomplete")
        print(capture.getvalue()[-6000:])
        return 1
    print("PASS: isolated write/rollback tests and simulated keyboard coverage")

    failures = []
    checked = 0
    skipped = []
    for label, action in walk(tui):
        if action.startswith("launch:"):
            skipped.append(action)
            continue
        checked += 1
        try:
            value = tui.get_details(action)
            if not isinstance(value, str) or not value.strip():
                raise AssertionError("Empty TUI result")
        except (ValueError, OSError, KeyError, AssertionError,
                RuntimeError) as exc:
            failures.append((action, type(exc).__name__))
        except Exception as exc:
            failures.append((action, type(exc).__name__))
    print(f"Actual read-only TUI action backends: {checked} checked; "
          f"{len(failures)} failures")
    print("External disk browsers intentionally not launched: " + ", ".join(skipped))
    for action, error in failures:
        print(f"FAIL: {action}: {error}")
    if failures:
        return 1

    print("PASS: all read-only TUI backends returned results")
    print("PASS: no production install, cron, disk, Docker or email actions executed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
