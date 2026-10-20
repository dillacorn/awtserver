"""Offline tests for the native-host Debian migration read-only audit."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "migration" / "debian"))
import native_audit


class NativeAuditTests(unittest.TestCase):
    def test_systemd_shows_runtime_vs_enabled(self):
        def fake_out(*args, **kwargs):
            if args[:2] == ("systemctl", "show"):
                return "LoadState=loaded\nActiveState=inactive\nUnitFileState=enabled"
            return None
        with patch.object(native_audit, "out", side_effect=fake_out):
            state = native_audit.unit_status("proftpd.service")
        self.assertEqual(state, {"loaded": "loaded",
                                 "active": "inactive", "enabled": "enabled"})

    def test_omv_job_commands_never_printed(self):
        private = json.dumps([
            {"enable": True, "command": "secret password=not-for-output"},
            {"enable": False, "command": "another-secret"},
        ])
        def fake_out(*args, **kwargs):
            if args[:2] == ("omv-confdbadm", "read"):
                return private
            return None
        io = StringIO()
        with patch.object(native_audit, "out", side_effect=fake_out), \
             patch.object(native_audit.shutil, "which", return_value="/usr/bin/omv-confdbadm"), \
             redirect_stdout(io):
            native_audit.omv_config_counts()
        output = io.getvalue()
        self.assertIn("2 entries, 1 explicitly enabled", output)
        self.assertNotIn("secret", output)
        self.assertNotIn("password", output)

    def test_mount_audit_reports_unmounted_disk_without_secret_uuid(self):
        fixtures = {
            "blockdevices": [
                {"name": "sda", "type": "disk", "size": 240000000000,
                 "children": [{"name": "sda1", "type": "part",
                               "mountpoints": ["/"]}]},
                {"name": "sdb", "type": "disk", "size": 64000000000,
                 "tran": "usb", "children": [
                     {"name": "sdb1", "type": "part",
                      "mountpoints": [None]}]},
            ]
        }
        def fake_out(*args, **kwargs):
            if args[:2] == ("findmnt", "-n"):
                return "/srv/mergerfs/data fuse.mergerfs"
            if args[:2] == ("lsblk", "-J"):
                return json.dumps(fixtures)
            return None
        io = StringIO()
        with patch.object(native_audit, "out", side_effect=fake_out), \
             patch.object(native_audit, "unit_status",
                          return_value={"loaded": "loaded",
                                        "active": "active", "enabled": "enabled"}), \
             redirect_stdout(io):
            native_audit.mounts()
        output = io.getvalue()
        self.assertIn("fuse.mergerfs", output)
        self.assertIn("Entirely unmounted disk: sdb", output)
        self.assertNotIn("Entirely unmounted disk: sda", output)

    def test_missing_omv_config_database_is_safe(self):
        io = StringIO()
        with patch.object(native_audit.shutil, "which", return_value=None), \
             redirect_stdout(io):
            native_audit.omv_config_counts()
        self.assertIn("unavailable", io.getvalue())


if __name__ == "__main__":
    unittest.main()
