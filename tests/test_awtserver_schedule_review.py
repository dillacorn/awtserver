"""Tests for strictly read-only, sanitized schedule collision review."""
import contextlib
from datetime import date
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "awtserver"))
import awtserver_schedule_review as schedules


class ScheduleReviewTests(unittest.TestCase):
    def test_historical_inventory_is_not_a_deployment_plan(self):
        meta, items = schedules.load_inventory()
        self.assertEqual(meta["status"], "historical-audit")
        self.assertEqual(len(items), 9)
        report = schedules.review(items)
        self.assertEqual(report["enabled"], 5)
        self.assertEqual(len(report["disabled_job_ids"]), 4)
        self.assertEqual(report["emails_enabled"], 3)
        self.assertTrue(report["audit_only"])
        self.assertFalse(report["writes_or_schedule_imports"])
        self.assertEqual(report["weekly_macro_unresolved"], ["omv-custom-6"])

    def test_45_minute_daily_backup_to_snapraid_warning(self):
        _, items = schedules.load_inventory()
        report = schedules.review(items, gap_minutes=60)
        self.assertTrue(any(set(w["jobs"]) == {"omv-custom-5", "omv-custom-7"}
                            and w["gap_minutes"] == 45 for w in report["possible_gaps"]))

    def test_sunday_17th_monthly_rsync_potential_collision(self):
        _, items = schedules.load_inventory()
        report = schedules.review(items, gap_minutes=60, start=date(2026, 10, 22), days=400)
        self.assertTrue(any(set(w["jobs"]) == {"omv-rsync-1", "omv-rsync-2"}
                            and w["gap_minutes"] == 15 for w in report["possible_gaps"]))

    def test_omv_disabled_jobs_do_not_generate_warnings(self):
        _, items = schedules.load_inventory()
        report = schedules.review(items)
        names = {name for w in report["possible_gaps"] for name in w["jobs"]}
        self.assertFalse({"omv-custom-1", "omv-custom-2", "omv-custom-3",
                          "omv-custom-4"} & names)

    def test_forbid_raw_commands_and_private_fields(self):
        _, items = schedules.load_inventory()
        for field in ("command", "user", "password", "source", "destination", "host"):
            corrupted = dict(items[0], **{field: "private"})
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "unsafe"):
                schedules.validate_inventory({"source": "test", "status": "historical-audit", "jobs": [corrupted]})

    def test_prevent_arbitrary_cron_macro_and_invalid_type(self):
        _, items = schedules.load_inventory()
        for schedule in ("@reboot", "60 3 * * *", "0 3 * * *\necho bad", "0 3 * * 8"):
            with self.subTest(schedule=schedule), self.assertRaises(ValueError):
                schedules.validate_inventory({"source": "test", "status": "historical-audit", "jobs": [dict(items[0], schedule=schedule)]})
        with self.assertRaises(ValueError):
            schedules.validate_inventory({"source": "test", "status": "historical-audit", "jobs": [dict(items[0], enabled="false")]})

    def test_sunday_seven_and_weekly_unresolved(self):
        when = schedules.next_occurrences("45 5 * * 7", date(2027, 1, 15), 4)
        self.assertEqual([x.date().isoformat() for x in when], ["2027-01-17"])
        self.assertEqual(schedules.next_occurrences("@weekly", date(2027, 1, 15), 4), [])

    def test_external_input_cannot_import_execution_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "audit.json"
            inp.write_text(json.dumps({"source": "test", "status": "historical-audit",
                                       "jobs": [{"command": "/bin/evil"}]}))
            with self.assertRaisesRegex(ValueError, "unsafe"):
                schedules.load_inventory(inp)

    def test_cli_list_and_review_only(self):
        with contextlib.redirect_stdout(io.StringIO()) as capture:
            self.assertEqual(schedules.main(["list"]), 0)
        self.assertIn('"historical": true', capture.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as capture:
            self.assertEqual(schedules.main(["review", "--min-gap", "60"]), 0)
        self.assertIn('"possible_gaps"', capture.getvalue())


if __name__ == "__main__":
    unittest.main()
