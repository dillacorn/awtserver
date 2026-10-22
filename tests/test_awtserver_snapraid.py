"""Offline safety tests for SnapRAID AIO v3.4 scheduling."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import awtserver_snapraid as s


class SnapTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            x=s.schedule_from_file(Path(td)/"missing.json")
            self.assertEqual(x["enabled"],False)
            self.assertEqual(s.render_cron(x).count("root /usr/bin/flock"),0)

    def test_enabled_root_job_has_flock_no_force_sync(self):
        result=s.render_cron({"enabled":True,"schedule":"15 2 * * *"})
        self.assertIn("15 2 * * * root /usr/bin/flock -n",result)
        self.assertNotIn("--force-sync",result)
        with self.assertRaises(ValueError):
            s.render_cron({"enabled":"true","schedule":"15 2 * * *"})

    def test_manage_existing_file_refuses_unowned_contents(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"cron"
            path.write_text("root bad command\n")
            with patch.object(s,"require_safe_file"):
                with self.assertRaisesRegex(ValueError,"unmanaged"):
                    s.safe_existing(path,s.MARKER)

    def test_sync_direct_api_is_guarded_before_write(self):
        with patch.object(s,"apply_guard",side_effect=ValueError("VM blocked")):
            with self.assertRaisesRegex(ValueError,"blocked"):
                s.sync({"enabled":False,"schedule":"30 1 * * *"})

    def test_local_staging_requires_checksum_and_vm(self):
        with patch.object(s,"apply_guard",side_effect=ValueError("blocked")):
            with self.assertRaisesRegex(ValueError,"blocked"):
                s.prepare_script(Path("/tmp/unverified"),"0"*64)
        with patch.object(s,"apply_guard"):
            with self.assertRaisesRegex(ValueError,"SHA256"):
                s.prepare_script(Path("/tmp/unverified"),"bad")

    def test_cron_state_preview_never_executes(self):
        with patch.object(s,"schedule_from_file",return_value=s.DEFAULT.copy()), \
             patch.object(s,"save_settings") as save, \
             patch.object(s,"sync") as sync, \
             contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(s.main(["enable","--schedule","15 2 * * *"]),0)
            self.assertIn("Preview only",out.getvalue())
            save.assert_not_called()
            sync.assert_not_called()

    def test_readonly_status_uses_expected_state(self):
        with patch.object(s,"schedule_from_file",return_value=s.DEFAULT.copy()), \
             patch.object(s,"prerequisites",return_value=["Missing binary: snapraid"]), \
             patch.object(s,"safe_existing",return_value=""), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(s.main(["status"]),0)
            self.assertIn("Missing binary",out.getvalue())


if __name__ == "__main__":
    unittest.main()
