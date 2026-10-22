"""Offline safety and behavior tests for awtserver.py (no root or VM needed)."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import awtserver as awt


class Profiles(unittest.TestCase):
    def test_reproducible_packages(self):
        self.assertEqual(awt.packages_for(["base", "storage", "base"]),
                         sorted(set(awt.PROFILES["base"] + awt.PROFILES["storage"])))

    def test_optional_samba_absent_by_default(self):
        self.assertNotIn("samba", awt.packages_for(list(awt.DEFAULT_PROFILES)))
        self.assertNotIn("docker.io", awt.packages_for(list(awt.DEFAULT_PROFILES)))
        self.assertIn("samba", awt.packages_for(["sharing"]))

    def test_docker_provider_must_be_explicit(self):
        self.assertEqual(awt.packages_for(["docker-debian"]),
                         ["docker-compose", "docker.io"])
        with self.assertRaisesRegex(ValueError, "Ambiguous Docker profile"):
            awt.packages_for(["docker"])
        self.assertNotIn("docker.io", awt.packages_for(["base", "storage"]))

    def test_existing_backup_providers_remain_opt_in(self):
        self.assertEqual(awt.packages_for(["borg"]), ["borgbackup"])
        self.assertEqual(awt.packages_for(["timeshift"]), ["timeshift"])
        self.assertEqual(awt.packages_for(["recovery"]), ["restic"])
        self.assertNotIn("borgbackup", awt.packages_for(list(awt.DEFAULT_PROFILES)))

    def test_unknown_profile_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown profile"):
            awt.packages_for(["nonexistent"])

    def test_plan_no_destructive_operations(self):
        plan = awt.profile_plan(["storage"])
        self.assertIn("mount changes", " ".join(plan["excluded"]))
        self.assertEqual(plan["packages"], ["mergerfs", "smartmontools", "snapraid"])


class Schedules(unittest.TestCase):
    def test_valid_cron(self):
        for expression in ("15 2 * * *", "*/5 * * * 1-5",
                           "0,30 1-3/2 * 1,6 0", "0 0 1 * 7"):
            with self.subTest(expression=expression):
                self.assertTrue(awt.valid_cron(expression))

    def test_bad_cron(self):
        for expression in ("@reboot", "* * * * * ; echo x", "60 2 * * *",
                           "10 24 * * *", "* * 0 * *", "* * * 13 *",
                           "* * * * 8", "*/0 * * * *", "2-1 * * * *",
                           "5 * * *", "* * * * *\nSHELL=/bin/sh",
                           "2/3 * * * *", "* * * * mon"):
            with self.subTest(expression=expression):
                self.assertFalse(awt.valid_cron(expression))

    def test_job_input_restrictions(self):
        valid = awt.validate_job("backup", "15 2 * * *", "backup",
                                 "/usr/local/libexec/awtserver-jobs/backup.sh")
        self.assertFalse(valid["enabled"])
        for kw in (
            {"name": "../evil"}, {"user": "root"}, {"user": "root;rm"},
            {"script": "/bin/sh"}, {"script": "/usr/local/libexec/awtserver-jobs/e.sh;rm"},
            {"schedule": "* * * * * /bin/true"},
        ):
            item = dict(name="backup", schedule="15 2 * * *", user="backup",
                        script="/usr/local/libexec/awtserver-jobs/backup.sh")
            item.update(kw)
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                awt.validate_job(**item)

    def test_state_round_trip_and_symlink_refusal(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "private" / "jobs.json"
            job = awt.validate_job("scrub", "5 3 * * 0", "backup",
                                    "/usr/local/libexec/awtserver-jobs/scrub")
            awt.save_jobs([job], path)
            self.assertEqual(awt.load_jobs(path), [job])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            symlink = Path(root) / "link"
            symlink.symlink_to(path)
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                awt.load_jobs(symlink)
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                awt.save_jobs([job], symlink)

    def test_corrupted_state_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "jobs.json"
            path.write_text('[{"name":"a"}]')
            with self.assertRaises((ValueError, KeyError)):
                awt.load_jobs(path)


class Safety(unittest.TestCase):
    @patch.object(awt, "virtual_machine", return_value=False)
    @patch.object(awt, "parse_os_release", return_value={"ID": "debian", "VERSION_ID": "13"})
    @patch.object(awt.os, "geteuid", return_value=0)
    def test_real_host_rejected(self, *_):
        with self.assertRaisesRegex(ValueError, "virtual machine"):
            awt.apply_guard(True)

    @patch.object(awt, "virtual_machine", return_value=True)
    @patch.object(awt, "parse_os_release", return_value={"ID": "debian", "VERSION_ID": "12"})
    @patch.object(awt.os, "geteuid", return_value=0)
    def test_wrong_release_rejected(self, *_):
        with self.assertRaisesRegex(ValueError, "Debian 13"):
            awt.apply_guard(True)

    @patch.object(awt, "virtual_machine", return_value=True)
    @patch.object(awt, "parse_os_release", return_value={"ID": "debian", "VERSION_ID": "13"})
    @patch.object(awt.os, "geteuid", return_value=1000)
    def test_root_required(self, *_):
        with self.assertRaisesRegex(ValueError, "root"):
            awt.apply_guard(True)

    def test_explicit_confirmation_required(self):
        with self.assertRaisesRegex(ValueError, "confirm-vm"):
            awt.apply_guard(False)

    @patch.object(awt.subprocess, "run", side_effect=AssertionError("subprocess attempted"))
    def test_default_install_is_preview(self, mocked):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(awt.main(["install", "--profiles", "storage"]), 0)
        self.assertIn("Preview only", output.getvalue())
        mocked.assert_not_called()

    @patch.object(awt, "apply_guard", side_effect=ValueError("blocked"))
    @patch.object(awt.subprocess, "run", side_effect=AssertionError("subprocess attempted"))
    def test_apply_guard_precedes_apt(self, run, guard):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(awt.main(["install", "--apply"]), 1)
        run.assert_not_called()
        guard.assert_called_once_with(False)

    @patch.object(awt, "apply_guard")
    @patch.object(awt.subprocess, "run")
    def test_vm_install_never_allows_package_removals(self, run, guard):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(awt.main(["install", "--apply", "--confirm-vm",
                                       "--profiles", "storage"]), 0)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0], ["apt-get", "update"])
        self.assertIn("--no-remove", commands[1])
        self.assertIn("--simulate", commands[1])
        self.assertIn("--no-remove", commands[2])
        self.assertIn("-y", commands[2])
        guard.assert_called_once_with(True)

    def test_cron_sync_preview_never_applies(self):
        import awtserver_cron as cron
        with patch.object(awt, "load_jobs", return_value=[]), \
             patch.object(cron, "preview_cron", return_value="diff\\n"), \
             patch.object(cron, "sync_cron") as sync, \
             patch.object(awt, "apply_guard") as guard:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(awt.main(["jobs", "sync"]), 0)
            self.assertIn("Preview only", output.getvalue())
            sync.assert_not_called()
            guard.assert_not_called()

    def test_cron_sync_apply_gate_before_changes(self):
        import awtserver_cron as cron
        with patch.object(awt, "load_jobs", return_value=[]), \
             patch.object(cron, "preview_cron", return_value="diff\\n"), \
             patch.object(cron, "sync_cron") as sync, \
             patch.object(awt, "apply_guard", side_effect=ValueError("blocked")):
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(awt.main(["jobs", "sync", "--apply", "--confirm-vm"]), 1)
            sync.assert_not_called()

    def test_job_preview_does_not_persist(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "jobs.json"
            with patch.object(awt, "JOBS_FILE", path):
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = awt.main(["jobs", "add", "--name", "backup",
                                   "--schedule", "15 2 * * *", "--user", "backup",
                                   "--script", "/usr/local/libexec/awtserver-jobs/backup"])
                self.assertEqual(rc, 0)
                self.assertFalse(path.exists())

    def test_job_add_toggle_remove_declarative(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "jobs.json"
            with patch.object(awt, "JOBS_FILE", path), patch.object(awt, "apply_guard"):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(awt.main(["jobs", "add", "--name", "backup",
                        "--schedule", "15 2 * * *", "--user", "backup",
                        "--script", "/usr/local/libexec/awtserver-jobs/backup",
                        "--apply", "--confirm-vm"]), 0)
                    self.assertEqual(awt.main(["jobs", "enable", "--name", "backup",
                        "--apply", "--confirm-vm"]), 0)
                self.assertTrue(awt.load_jobs(path)[0]["enabled"])
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(awt.main(["jobs", "remove", "--name", "backup",
                        "--apply", "--confirm-vm"]), 0)
                self.assertEqual(awt.load_jobs(path), [])


if __name__ == "__main__":
    unittest.main()
