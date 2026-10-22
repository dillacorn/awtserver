"""Offline cron render/activation tests; no actual /etc/cron.d writes."""
import contextlib
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import awtserver as awt
import awtserver_cron as cron


def job(name="backup", schedule="15 2 * * *", enabled=True):
    value = awt.validate_job(name, schedule, "backup",
                             "/usr/local/libexec/awtserver-jobs/backup.sh")
    value["enabled"] = enabled
    return value


class CronRenderTests(unittest.TestCase):
    def test_render_order_user_and_disabled(self):
        contents = cron.render_cron([job("z", enabled=False), job("a", "5 1 * * 0")])
        self.assertTrue(contents.startswith(cron.MARKER))
        self.assertIn("5 1 * * 0 backup /usr/local/libexec/awtserver-jobs/backup.sh\n", contents)
        self.assertIn("# disabled: z\n", contents)
        self.assertLess(contents.index("# a\n"), contents.index("# disabled: z\n"))
        self.assertEqual(contents.count("backup /usr/local"), 1)
        self.assertTrue(contents.endswith("\n"))

    def test_refuses_invalid_content(self):
        for broken in (
            [dict(job(), extra="no")],
            [dict(job(), enabled="yes")],
            [job(), job()],
            [dict(job(), schedule="* * * * *; /bin/true")],
        ):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                cron.render_cron(broken)

    def test_read_only_diff_and_existing_same(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "awtserver"
            expected = cron.render_cron([job()])
            with patch.object(cron, "_checked_root_path"):
                proposed = cron.preview_cron([job()], path)
                self.assertIn("+15 2 * * * backup", proposed)
                self.assertFalse(path.exists())
                path.write_text(expected)
                self.assertEqual(cron.preview_cron([job()], path),
                                 "No cron changes required.\n")

    def test_never_overwrites_unmanaged_crontab(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "awtserver"
            path.write_text("0 1 * * * root echo unexpected\n")
            with patch.object(cron, "_checked_root_path"), self.assertRaisesRegex(ValueError, "unmanaged"):
                cron.preview_cron([job()], path)
            self.assertEqual(path.read_text(), "0 1 * * * root echo unexpected\n")

    def test_symlinks_refused(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "data"
            src.write_text(cron.MARKER)
            link = Path(td) / "awtserver"
            link.symlink_to(src)
            with self.assertRaisesRegex(ValueError, "symlink"):
                cron.existing_content(link)

    def test_root_check_rejects_unsafe_modes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "jobs"
            path.write_text("safe")
            with patch.object(cron.Path, "lstat") as mock_stat:
                s = path.stat()
                mock_stat.return_value = s
                # Current CI user should not be root; no reliance on actual UID.
                with patch.object(cron, "_checked_root_path", wraps=cron._checked_root_path):
                    with patch.object(s, "st_uid", 1000, create=True):
                        with self.assertRaises(ValueError):
                            cron._checked_root_path(path, directory=False)


class CronApplyTests(unittest.TestCase):
    def test_direct_module_calls_still_check_vm(self):
        with patch.object(cron, "apply_guard", side_effect=ValueError("blocked")):
            with self.assertRaisesRegex(ValueError, "blocked"):
                cron.sync_cron([job()])

    def test_apply_rejects_inactive_cron_without_writes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "awtserver"
            with patch.object(cron, "apply_guard"), patch.object(cron, "_checked_root_path"), \
                 patch.object(cron.subprocess, "run", return_value=MagicMock(returncode=3)):
                with self.assertRaisesRegex(ValueError, "not active"):
                    cron.sync_cron([job()], path)
                self.assertFalse(path.exists())

    def test_inactive_job_produces_managed_file_idempotently(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "awtserver"
            with patch.object(cron, "apply_guard"), patch.object(cron, "_checked_root_path"), \
                 patch.object(cron.subprocess, "run", return_value=MagicMock(returncode=0)):
                self.assertTrue(cron.sync_cron([job(enabled=False)], path))
                self.assertFalse(cron.sync_cron([job(enabled=False)], path))
            self.assertEqual(path.read_text(), cron.render_cron([job(enabled=False)]))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)

    def test_invalid_script_blocks_activation(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "awtserver"
            with patch.object(cron, "apply_guard"), patch.object(cron, "_checked_root_path"), \
                 patch.object(cron.subprocess, "run", return_value=MagicMock(returncode=0)), \
                 patch.object(cron.pwd, "getpwnam", side_effect=KeyError("missing")):
                with self.assertRaises(KeyError):
                    cron.sync_cron([job()], path)
                self.assertFalse(path.exists())

    def test_unmanaged_existing_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "awtserver"
            path.write_text("Unrelated job\n")
            with patch.object(cron, "apply_guard"), patch.object(cron, "_checked_root_path"):
                with self.assertRaisesRegex(ValueError, "unmanaged"):
                    cron.sync_cron([job(enabled=False)], path)
                self.assertEqual(path.read_text(), "Unrelated job\n")


if __name__ == "__main__":
    unittest.main()
