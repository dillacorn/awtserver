"""Offline read-only storage and threshold tests."""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "awtserver"))
import awtserver_storage as s


class StorageTests(unittest.TestCase):
    def test_relevant_mounts_filter_virtual_and_deduplicate(self):
        rows = [
            {"target":"/", "fstype":"ext4", "source":"/dev/root"},
            {"target":"/srv/media", "fstype":"fuse.mergerfs", "source":"disks"},
            {"target":"/srv/media", "fstype":"fuse.mergerfs", "source":"disks"},
            {"target":"/proc", "fstype":"proc", "source":"proc"},
            {"target":"/var/lib/docker/overlay", "fstype":"overlay", "source":"none"},
        ]
        self.assertEqual([m["target"] for m in s.relevant_mounts(rows)], ["/", "/srv/media"])
        self.assertEqual(s.pool_report(rows)["pools"][0]["mount"], "/srv/media")

    def test_threshold_and_exit_code(self):
        mounts = [{"target":"/", "source":"disk", "fstype":"ext4"},
                  {"target":"/data", "source":"disk2", "fstype":"ext4"}]
        def usage(path):
            return {"mount":path,"used_percent":85 if path == "/data" else 55,
                    "available_bytes":15,"size_bytes":100,"used_bytes":85}
        with patch.object(s, "mount_table", return_value=mounts), \
             patch.object(s, "disk_usage", side_effect=usage), \
             redirect_stdout(io.StringIO()) as out:
            self.assertEqual(s.main(["usage", "--threshold", "80"]), 2)
            self.assertIn("ALERT", out.getvalue())
            self.assertEqual(s.usage_report(90)["alerts"], [])

    def test_invalid_threshold(self):
        with self.assertRaises(ValueError):
            s.usage_report(100, mounts=[])
        with self.assertRaises(ValueError):
            s.usage_report(0, mounts=[])

    def test_statvfs_percentage(self):
        class V:
            f_blocks=100
            f_frsize=1024
            f_bfree=25
            f_bavail=20
        with patch.object(s.os, "statvfs", return_value=V()):
            u=s.disk_usage("/tmp")
        self.assertEqual(u["used_percent"], 80.0)
        self.assertEqual(u["available_bytes"], 20480)

    def test_readonly_backend_commands(self):
        with patch.object(s, "run_json", return_value={"blockdevices":[]} ) as run:
            self.assertEqual(s.block_devices(), {"blockdevices":[]})
            self.assertEqual(run.call_args.args[0][:2], ["lsblk", "--json"])
        with patch.object(s.shutil, "which", return_value=None):
            self.assertFalse(any(x["installed"] for x in s.tool_catalog()))


if __name__ == "__main__":
    unittest.main()
