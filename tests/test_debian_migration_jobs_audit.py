"""Tests for read-only OMV scheduled-job and rsync migration audit."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "migration" / "debian"))
import jobs_audit


class JobsAuditTests(unittest.TestCase):
    def test_safe_schedule(self):
        self.assertEqual(
            jobs_audit.schedule({
                "execution": "exactly", "minute": "15", "everynminute": False,
                "hour": "2", "everynhour": False, "dayofmonth": "*",
                "month": "*", "dayofweek": "1",
            }),
            "15 2 * * 1",
        )
        self.assertEqual(jobs_audit.safe_field("password=abc"), "[unrecognized]")
        self.assertEqual(jobs_audit.schedule({"execution": "daily"}), "execution=daily")

    def test_flags_strict(self):
        self.assertEqual(jobs_audit.safe_flag(True), "yes")
        self.assertEqual(jobs_audit.safe_flag("0"), "no")
        self.assertEqual(jobs_audit.safe_flag("secret"), "unknown")

    def test_omv_commands_and_credentials_not_printed(self):
        entries = {
            "conf.system.cron.job": [{
                "enable": True, "command": "rsync -a --password=TOPSECRET /source /dest",
                "comment": "private-token-1234", "hour": "3", "minute": "55",
                "dayofmonth": "*", "month": "*", "dayofweek": "*",
                "execution": "exactly", "sendemail": True,
            }],
            "conf.service.rsync.job": [{
                "enable": True, "type": "remote", "mode": "push",
                "password": "secret5678",
                "src": {"uri": "PRIVATE_SOURCE"},
                "dest": {"uri": "ssh://private.destination.example"},
                "minute": "5", "hour": "4", "dayofmonth": "*",
                "month": "*", "dayofweek": "*", "optiondelete": True,
                "optionarchive": True, "optiondryrun": False,
            }],
        }
        def fake_command(*args, **kwargs):
            if args[:2] == ("omv-confdbadm", "read"):
                return json.dumps(entries[args[2]])
            return ""
        buf = io.StringIO()
        with patch.object(jobs_audit, "read_command", side_effect=fake_command), \
             patch.object(jobs_audit.Path, "read_text", side_effect=OSError()), \
             contextlib.redirect_stdout(buf):
            jobs_audit.omv_jobs()
        output = buf.getvalue()
        self.assertIn("Job 1: enabled=yes schedule=55 3 * * *", output)
        self.assertIn("category=rsync", output)
        self.assertIn("Rsync 1: enabled=yes schedule=5 4 * * *", output)
        self.assertIn("delete=yes", output)
        self.assertNotIn("TOPSECRET", output)
        self.assertNotIn("private-token-1234", output)
        self.assertNotIn("secret5678", output)
        self.assertNotIn("PRIVATE_SOURCE", output)
        self.assertNotIn("private.destination", output)

    def test_classification_not_command_echo(self):
        self.assertEqual(jobs_audit.categories("docker exec snapraid backup"), [
            "snapraid", "docker", "backup"])
        self.assertEqual(jobs_audit.categories("topsecret"), ["other"])

    def test_unreadable_config_fails_softly(self):
        buf = io.StringIO()
        with patch.object(jobs_audit, "read_command", return_value=None), \
             patch.object(jobs_audit.Path, "read_text", side_effect=OSError()), \
             contextlib.redirect_stdout(buf):
            jobs_audit.omv_jobs()
        self.assertIn("Unavailable", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
