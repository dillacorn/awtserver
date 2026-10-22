"""Opt-in unprivileged temporary-directory write tests for awtserver.

These never operate on a real cron directory, apt, Docker, backup media,
systemd services, production SnapRAID or OS installation targets.
"""
from __future__ import annotations
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import awtserver as cli
import awtserver_cron as cron
import awtserver_installer as installer
import awtserver_snapraid as snapraid
import awtserver_monitor as monitor
import awtserver_backup as backup


class RealSandboxWrites(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("Never run real write tests as root")
        if os.environ.get("AWTSERVER_SANDBOX_TEST") != "1":
            self.skipTest("AWTSERVER_SANDBOX_TEST=1 required")
        self.tmp = tempfile.TemporaryDirectory(prefix="awtserver-safe-test-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.assertTrue(self.base.name.startswith("awtserver-safe-test-"))

    def confined(self, path):
        path = Path(path)
        if not path.absolute().is_relative_to(self.base):
            raise AssertionError("Sandbox test target outside temporary directory")
        return path

    def test_real_job_state_write_toggle_and_reload(self):
        with self.assertRaises(ValueError):
            cli.apply_guard(True)
        file = self.confined(self.base / "jobs" / "jobs.json")
        job = cli.validate_job("demo", "45 3 * * *", "backup",
                               "/usr/local/libexec/awtserver-jobs/demo")
        cli.save_jobs([job], file)
        self.assertEqual(cli.load_jobs(file), [job])
        self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        job["enabled"] = True
        cli.save_jobs([job], file)
        self.assertTrue(cli.load_jobs(file)[0]["enabled"])
        self.assertEqual(list(file.parent.iterdir()), [file])

    def test_actual_cron_write_idempotence_and_unmanaged_conflict(self):
        target = self.confined(self.base / "cron.d" / "awtserver")
        target.parent.mkdir(mode=0o700)
        with self.assertRaises(ValueError):
            cron.sync_cron([], target)

        def confined_metadata(path, *, directory):
            path = self.confined(path)
            if directory and not path.is_dir():
                raise AssertionError("Expected sandbox directory")
            if not directory and not path.is_file():
                raise AssertionError("Expected sandbox file")
        with patch.object(cron, "apply_guard", return_value=None), \
             patch.object(cron, "_checked_root_path", side_effect=confined_metadata), \
             patch.object(cron.subprocess, "run",
                          return_value=MagicMock(returncode=0)) as status:
            self.assertTrue(cron.sync_cron([], target))
            self.assertFalse(cron.sync_cron([], target))
            self.assertEqual(target.read_text(), cron.render_cron([]))
            job = cli.validate_job("demo", "45 3 * * *", "backup",
                                   "/usr/local/libexec/awtserver-jobs/demo")
            self.assertTrue(cron.sync_cron([job], target))
            self.assertIn("# disabled: demo", target.read_text())
            self.assertNotIn("45 3 * * * backup", target.read_text())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
            target.write_text("unmanaged cron text\n")
            with self.assertRaisesRegex(ValueError, "unmanaged"):
                cron.sync_cron([], target)
            self.assertEqual(target.read_text(), "unmanaged cron text\n")
            self.assertTrue(status.called)

    def test_temporary_install_copy_and_existing_install_refusal(self):
        target = self.confined(self.base / "awtserver-install")
        command = self.confined(self.base / "awtserver-command")
        def clear(dest, link):
            for item in (dest, link):
                self.confined(item)
                if os.path.lexists(item):
                    raise ValueError("Existing installation or command")
        with patch.object(installer.awtserver, "apply_guard", return_value=None), \
             patch.object(installer, "target_is_clear", side_effect=clear):
            installer.install(dest=target, command=command)
            self.assertTrue(command.is_symlink())
            self.assertEqual(command.resolve(), target / "awtserver")
            self.assertTrue((target / "docs/quick/remote-apps.md").is_file())
            self.assertTrue((target / "docs/examples/omv-schedules-2026-10-22.json").is_file())
            with self.assertRaisesRegex(ValueError, "Existing installation"):
                installer.install(dest=target, command=command)
            self.assertTrue(command.is_symlink())

    def test_mutating_entrypoints_blocked_on_real_host(self):
        with self.assertRaises(ValueError):
            cron.sync_cron([])
        with self.assertRaises(ValueError):
            snapraid.sync({"enabled": False, "schedule": "45 3 * * *"})
        with self.assertRaises(ValueError):
            snapraid.save_settings({"enabled": False, "schedule": "45 3 * * *"},
                                   self.confined(self.base / "snapraid.json"))
        with self.assertRaises(ValueError):
            snapraid.prepare_script(self.confined(self.base / "script"), "0" * 64)
        with self.assertRaises(ValueError):
            monitor.send_alert({"recipient": "nobody@example.invalid"},
                               {"needs_attention": True})
        with self.assertRaises(ValueError):
            backup.snapshot("/never-mounted", "UNKNOWN", Path("/never-existing"))
        with self.assertRaises(ValueError):
            backup.restore_stage("/never-mounted", "UNKNOWN", Path("/never-existing"))
        with self.assertRaises(ValueError):
            installer.install(dest=self.confined(self.base / "blocked-install"),
                              command=self.confined(self.base / "blocked-command"))
        self.assertEqual(list(self.base.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
