"""Unit tests for USB UUID verification and non-destructive encrypted backup."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, call
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import awtserver_backup as b


class BackupTests(unittest.TestCase):
    def test_target_must_be_mount_and_match_uuid(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            def lookup(cmd,timeout=15):
                field=cmd[3]
                return {"TARGET":str(p),"SOURCE":"/dev/sdz1",
                        "UUID":"USB-UUID","FSTYPE":"ext4"}[field]
            with patch.object(b,"exec_capture",side_effect=lookup):
                result=b.backup_target(str(p),"USB-UUID")
                self.assertEqual(result["repository"],str(p/b.REPO_FOLDER))
                with self.assertRaisesRegex(ValueError,"UUID mismatch"):
                    b.backup_target(str(p),"OTHER")

    def test_refuse_subdirectory_destination(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"child"
            p.mkdir()
            with patch.object(b,"exec_capture",return_value=td):
                with self.assertRaisesRegex(ValueError,"mountpoint"):
                    b.backup_target(str(p),"UUID")

    def test_vm_gate_precedes_any_backup(self):
        with patch.object(b,"apply_guard",side_effect=ValueError("blocked")):
            with self.assertRaisesRegex(ValueError,"blocked"):
                b.snapshot("/mnt/usb","UUID",Path("/root/password"))

    def test_backup_plan_explicitly_excludes_live_dbs(self):
        with patch.object(b,"backup_target",return_value={"repository":"/usb/restic"}) as called:
            plan=b.backup_plan("/usb","UUID")
            self.assertIn("/etc",plan["included"])
            self.assertTrue(any("Docker" in x for x in plan["excluded"]))
            called.assert_called_once_with("/usb","UUID")

    def test_preview_never_runs_restic(self):
        with patch.object(b,"backup_target",return_value={"repository":"/usb/restic"}), \
             patch.object(b,"snapshot") as snap, \
             contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(b.main(["snapshot","--mount","/usb","--uuid","UUID",
                                    "--password-file","/root/key"]),0)
            self.assertIn("Preview only",out.getvalue())
            snap.assert_not_called()


if __name__ == "__main__":
    unittest.main()
