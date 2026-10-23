"""Exhaustive keyboard-menu walkthrough using a fake curses screen.

No real terminal, disk scanner, Docker, shell, cron, APT or external tool is run.
Every executable leaf is intercepted and verified by its action name.
"""
from __future__ import annotations

import collections
import curses
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "awtserver"))
import awtserver_tui as tui


class FakeScreen:
    def __init__(self, keys, *, width=40, height=14):
        self.keys = collections.deque(keys)
        self.width = width
        self.height = height
        self.frames = []
        self.lines = []
        self.calls = 0

    def getmaxyx(self):
        return self.height, self.width

    def keypad(self, on):
        self.keypad_on = on

    def erase(self):
        self.lines = []

    def clear(self):
        self.lines = []

    def addnstr(self, row, col, text, count, attribute):
        if not (0 <= row < self.height) or count < 0:
            raise AssertionError("TUI painted outside its terminal")
        self.lines.append((row, col, text[:count], attribute))

    def refresh(self):
        self.frames.append(list(self.lines))

    def getch(self):
        self.calls += 1
        if self.calls > 250:
            raise AssertionError("TUI navigation got stuck")
        if not self.keys:
            raise AssertionError("TUI requested unexpected keyboard input")
        return self.keys.popleft()


def leaves(section="root", indexes=()):
    for i, (_, action) in enumerate(tui.menu_for(section)):
        if action == "quit":
            continue
        if action.startswith("menu:"):
            yield from leaves(action.split(":", 1)[1], (*indexes, i))
        else:
            yield (*indexes, i), action


class FullNavigationTests(unittest.TestCase):
    @patch.object(tui.curses, "curs_set")
    def test_every_menu_item_can_be_opened_at_minimum_terminal_size(self, _):
        actions = list(leaves())
        self.assertGreaterEqual(len(actions), 25)
        visited = set()

        for index_path, action in actions:
            keys = []
            for index in index_path:
                keys.extend([curses.KEY_DOWN] * index)
                keys.append(10)  # Enter
            keys.extend([curses.KEY_DOWN, curses.KEY_NPAGE,
                         curses.KEY_PPAGE, ord("h"), ord("q")])
            screen = FakeScreen(keys)
            with self.subTest(action=action), \
                 patch.object(tui, "get_details",
                              side_effect=lambda name: "DETAIL " + name) as get, \
                 patch.object(tui, "launch_tool",
                              side_effect=lambda name, screen: "TOOL " + name) as launch:
                tui.run_ui(screen)
                self.assertFalse(screen.keys, f"Unconsumed keys for {action}")
                self.assertTrue(screen.keypad_on)
                rendered = "\n".join(text for frame in screen.frames
                                    for row, col, text, attr in frame)
                leaf_title = tui.menu_for(
                    # nested path menu name reconstructed below
                    self._parent(index_path)
                )[index_path[-1]][0]
                self.assertIn(leaf_title[:26], rendered)
                if action.startswith("launch:"):
                    launch.assert_called_once()
                    get.assert_not_called()
                else:
                    get.assert_called_once_with(action)
                    launch.assert_not_called()
                visited.add(action)

        self.assertEqual(visited, {a for _, a in actions})
        self.assertIn("doc:android-auto", visited)
        self.assertIn("schedule:review", visited)
        self.assertIn("snapraid:plan", visited)
        self.assertIn("launch:gdu", visited)
        self.assertIn("launch:ncdu", visited)

    @staticmethod
    def _parent(path):
        section = "root"
        for index in path[:-1]:
            action = tui.menu_for(section)[index][1]
            section = action.split(":", 1)[1]
        return section

    @patch.object(tui.curses, "curs_set")
    def test_resize_warning_stays_readable_and_exits(self, _):
        small = FakeScreen([ord("q")], height=9, width=25)
        tui.run_ui(small)
        self.assertTrue(any("Resize terminal" in text
                            for frame in small.frames for _, _, text, _ in frame))

    @patch.object(tui.curses, "curs_set")
    def test_menu_wrap_key_and_escape(self, _):
        s = FakeScreen([curses.KEY_UP, ord("h"), ord("q")], height=14)
        tui.run_ui(s)
        self.assertTrue(any("Quit" in text and attr == curses.A_REVERSE
                            for frame in s.frames for _, _, text, attr in frame))

    @patch.object(tui.curses, "curs_set")
    def test_backend_error_shown_without_crashing(self, _):
        s = FakeScreen([10, 10, ord("h"), ord("q")])
        with patch.object(tui, "get_details", side_effect=ValueError("test failure")):
            tui.run_ui(s)
        self.assertTrue(any("Unable to read: test failure" in text
                            for frame in s.frames for _, _, text, attr in frame))

    def test_external_tools_never_shell_out_in_test(self):
        for tool in ("gdu", "ncdu"):
            with self.subTest(tool=tool), \
                 patch.dict(tui.os.environ, {"AWTSERVER_TUI_TEST_MODE": "0"}), \
                 patch.object(tui.os, "geteuid", return_value=1000), \
                 patch.object(tui.shutil, "which", return_value="/usr/bin/"+tool), \
                 patch.object(tui.curses, "def_prog_mode"), \
                 patch.object(tui.curses, "endwin"), \
                 patch.object(tui.curses, "reset_prog_mode"), \
                 patch.object(tui.subprocess, "run",
                              return_value=MagicMock(returncode=0)) as run:
                s = FakeScreen([])
                self.assertIn("status 0", tui.launch_tool(tool, s))
                argv = run.call_args.args[0]
                self.assertEqual(argv[0], tool)
                self.assertFalse(run.call_args.kwargs["check"])
                self.assertNotIn("shell", run.call_args.kwargs)
                if tool == "gdu":
                    self.assertIn("--no-delete", argv)
                    self.assertIn("--no-spawn-shell", argv)
                else:
                    self.assertIn("-rr", argv)
        with patch.dict(tui.os.environ, {"AWTSERVER_TUI_TEST_MODE": "1"}), \
             patch.object(tui.subprocess, "run",
                          side_effect=AssertionError("test mode launched tool")):
            self.assertIn("disabled during safe TUI testing",
                          tui.launch_tool("gdu", FakeScreen([])))
            self.assertIn("disabled during safe TUI testing",
                          tui.launch_tool("ncdu", FakeScreen([])))
        with patch.dict(tui.os.environ, {"AWTSERVER_TUI_TEST_MODE": "0"}), \
             patch.object(tui.os, "geteuid", return_value=0), \
             patch.object(tui.subprocess, "run",
                          side_effect=AssertionError("root launched tool")):
            self.assertIn("blocked as root", tui.launch_tool("gdu", FakeScreen([])))
            self.assertIn("blocked as root", tui.launch_tool("ncdu", FakeScreen([])))
        with self.assertRaises(ValueError):
            tui.launch_tool("bash", FakeScreen([]))


if __name__ == "__main__":
    unittest.main()
