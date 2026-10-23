"""Read-only menu model tests, no actual terminal required."""
from pathlib import Path
from unittest.mock import patch
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "awtserver"))
import awtserver_tui as tui


class TuiTests(unittest.TestCase):
    def test_key_navigation_wraps(self):
        import curses
        self.assertEqual(tui.next_selection(0, curses.KEY_UP, 6), 5)
        self.assertEqual(tui.next_selection(5, curses.KEY_DOWN, 6), 0)
        self.assertEqual(tui.next_selection(3, ord("j"), 6), 4)
        self.assertEqual(tui.next_selection(3, ord("k"), 6), 2)
        self.assertEqual(tui.next_selection(2, ord("x"), 6), 2)

    def test_details_use_same_backend(self):
        with patch.object(tui.awtserver, "doctor_snapshot",
                          return_value={"os": "Debian 13"}), \
             patch.object(tui.awtserver, "profile_plan",
                          return_value={"profiles": ["base"]}) as plan, \
             patch.object(tui.awtserver, "load_jobs",
                          return_value=[{"name": "test"}]), \
             patch.object(tui.awtserver_cron, "preview_cron",
                          return_value="No changes.\n") as preview:
            self.assertEqual(json.loads(tui.get_details("doctor"))["os"], "Debian 13")
            self.assertIn("storage", json.loads(tui.get_details("profiles")))
            self.assertEqual(json.loads(tui.get_details("plan"))["profiles"], ["base"])
            self.assertEqual(json.loads(tui.get_details("jobs"))["desired_jobs"][0]["name"], "test")
            self.assertEqual(tui.get_details("cron"), "No changes.\n")
            plan.assert_called_once_with(list(tui.awtserver.DEFAULT_PROFILES))
            preview.assert_called_once_with([{"name": "test"}])

    def test_unknown_action_refused(self):
        with self.assertRaisesRegex(ValueError, "Unknown"):
            tui.get_details("activate")

    def test_noninteractive_terminal_refused(self):
        with patch.object(tui.sys.stdin, "isatty", return_value=False), \
             patch.object(tui.sys.stdout, "isatty", return_value=False), \
             patch.object(tui.curses, "wrapper",
                          side_effect=AssertionError("TUI unexpectedly started")):
            self.assertEqual(tui.main(), 2)


if __name__ == "__main__":
    unittest.main()
