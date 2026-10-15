"""Offline behavioral tests: no real Docker daemon or APT operations."""
from contextlib import redirect_stdout
from io import StringIO
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "docker/engine-upgrade-recovery/docker-upgrade-recovery.py"
spec = importlib.util.spec_from_file_location("recovery", SCRIPT)
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = patch.object(recovery, "STATE_DIR", Path(self.tmp.name))
        self.state.start()
        self.addCleanup(self.state.stop)
        self.time = patch.object(recovery.time, "time", return_value=1000)
        self.time.start()
        self.addCleanup(self.time.stop)
        self.stdout = StringIO()
        self.redirect = redirect_stdout(self.stdout)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)
        self.markers = {"docker": "before-docker", "containerd": "before-containerd"}
        self.entries = [
            {"id": "a" * 64, "name": "pihole", "policy": "unless-stopped"},
            {"id": "b" * 64, "name": "transmission", "policy": "unless-stopped"},
        ]

    def snapshot(self):
        with patch.object(recovery, "markers", return_value=self.markers), \
             patch.object(recovery, "docker_entries", return_value=self.entries):
            recovery.snapshot(["/var/cache/apt/archives/docker-ce_29.9.1_amd64.deb\n"])

    def test_only_apt_docker_packages_trigger(self):
        with patch.object(recovery, "docker_entries", side_effect=AssertionError("unexpected")):
            recovery.snapshot(["/var/cache/apt/archives/some-app_1_amd64.deb\n"])
        self.assertFalse((Path(self.tmp.name) / recovery.PENDING).exists())
        self.snapshot()
        self.assertEqual(len(recovery.load(recovery.PENDING)["containers"]), 2)

    def test_existing_pre_upgrade_snapshot_is_not_overwritten(self):
        self.snapshot()
        with patch.object(recovery, "docker_entries", side_effect=AssertionError("overwrite")):
            recovery.snapshot(["containerd.io_2.4.2_amd64.deb"])
        self.assertEqual(len(recovery.load(recovery.PENDING)["containers"]), 2)

    def test_unchanged_daemon_does_not_start_anything(self):
        self.snapshot()
        with patch.object(recovery, "apt_busy", return_value=False), \
             patch.object(recovery.time, "time", return_value=1040), \
             patch.object(recovery, "markers", return_value=self.markers), \
             patch.object(recovery, "command", side_effect=AssertionError("docker unexpectedly called")):
            recovery.recover()
        self.assertIsNone(recovery.load(recovery.PENDING))

    def test_busy_apt_does_not_reconcile(self):
        self.snapshot()
        with patch.object(recovery, "apt_busy", return_value=True), \
             patch.object(recovery, "markers", side_effect=AssertionError("apt not finished")):
            recovery.recover()
        self.assertIsNotNone(recovery.load(recovery.PENDING))

    def test_start_only_missing_previously_running_container(self):
        self.snapshot()
        statuses = {
            self.entries[0]["id"]: {"state": "running", "policy": "unless-stopped", "health": "healthy"},
            self.entries[1]["id"]: {"state": "exited", "policy": "unless-stopped", "health": "none"},
        }
        calls = []
        def fake_command(*args, **kwargs):
            calls.append(args)
            return "29.9.1"
        with patch.object(recovery, "apt_busy", return_value=False), \
             patch.object(recovery.time, "time", return_value=1040), \
             patch.object(recovery, "markers", return_value={"docker":"after", "containerd":"after"}), \
             patch.object(recovery, "inspect_one", side_effect=lambda cid: statuses[cid]), \
             patch.object(recovery, "command", side_effect=fake_command):
            recovery.recover()
        self.assertEqual([c for c in calls if c[:2] == ("docker", "start")],
                         [("docker", "start", self.entries[1]["id"])])
        self.assertIsNotNone(recovery.load(recovery.PENDING))
        # The next timer run confirms the container remains up, rather than
        # treating a successful `docker start` command as proof of recovery.
        statuses[self.entries[1]["id"]]["state"] = "running"
        with patch.object(recovery, "apt_busy", return_value=False), \
             patch.object(recovery.time, "time", return_value=1100), \
             patch.object(recovery, "markers", return_value={"docker":"after", "containerd":"after"}), \
             patch.object(recovery, "inspect_one", side_effect=lambda cid: statuses[cid]), \
             patch.object(recovery, "command", side_effect=fake_command):
            recovery.recover()
        self.assertIsNone(recovery.load(recovery.PENDING))
        self.assertEqual(recovery.load(recovery.RESULT)["problems"], [])

    def test_missing_container_never_recreated(self):
        self.snapshot()
        with patch.object(recovery, "apt_busy", return_value=False), \
             patch.object(recovery.time, "time", return_value=1040), \
             patch.object(recovery, "markers", return_value={"docker":"after", "containerd":"after"}), \
             patch.object(recovery, "inspect_one", return_value=None), \
             patch.object(recovery, "command", return_value="29.9.1") as cmd:
            recovery.recover()
        self.assertFalse(any(c.args[1] in ("start", "compose") for c in cmd.call_args_list))
        self.assertEqual(len(recovery.load(recovery.RESULT)["problems"]), 2)

    def test_changed_policy_and_paused_are_not_started(self):
        self.snapshot()
        statuses = [
            {"state":"exited", "policy":"no", "health":"none"},
            {"state":"paused", "policy":"unless-stopped", "health":"none"},
        ]
        with patch.object(recovery, "apt_busy", return_value=False), \
             patch.object(recovery.time, "time", return_value=1040), \
             patch.object(recovery, "markers", return_value={"docker":"after", "containerd":"after"}), \
             patch.object(recovery, "inspect_one", side_effect=statuses), \
             patch.object(recovery, "command", return_value="29.9.1") as cmd:
            recovery.recover()
        self.assertFalse(any(c.args[1] == "start" for c in cmd.call_args_list))
        self.assertEqual(len(recovery.load(recovery.RESULT)["problems"]), 2)

    def test_dry_run_does_not_change_state(self):
        self.snapshot()
        with patch.object(recovery, "markers", return_value={"docker":"after", "containerd":"after"}), \
             patch.object(recovery, "inspect_one", return_value={"state": "exited", "policy": "unless-stopped", "health": "none"}), \
             patch.object(recovery, "command", return_value="29.9.1") as cmd:
            recovery.recover(dry_run=True)
        self.assertTrue(recovery.load(recovery.PENDING))
        self.assertFalse(any(c.args[1] == "start" for c in cmd.call_args_list))

    def test_transient_failures_retry_and_are_capped(self):
        self.snapshot()
        with patch.object(recovery, "apt_busy", return_value=False), \
             patch.object(recovery.time, "time", return_value=1040), \
             patch.object(recovery, "markers", return_value={"docker":"after", "containerd":"after"}), \
             patch.object(recovery, "inspect_one", return_value={"state": "exited", "policy": "unless-stopped", "health": "none"}), \
             patch.object(recovery, "command", side_effect=lambda *args, **kw: (_ for _ in ()).throw(RuntimeError("failed")) if args[1] == "start" else "29.9.1"):
            for i in range(recovery.MAX_ATTEMPTS):
                recovery.recover()
                if i != recovery.MAX_ATTEMPTS - 1:
                    self.assertEqual(recovery.load(recovery.PENDING)["attempts"], i + 1)
        self.assertIsNone(recovery.load(recovery.PENDING))
        self.assertEqual(len(recovery.load(recovery.RESULT)["problems"]), 2)


if __name__ == "__main__":
    unittest.main()
