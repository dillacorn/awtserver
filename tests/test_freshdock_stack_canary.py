"""Offline tests for Freshdock disposable Compose namespace canary."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker" / "freshdock"))
import freshdock_stack_canary as canary


class CanarySafetyTests(unittest.TestCase):
    def setUp(self):
        # Preflight uses host-local maintenance hours. Fix test time so CI
        # never accidentally runs these offline test cases in that window.
        clock = patch.object(canary, "datetime")
        obj = clock.start()
        obj.now.return_value.strftime.return_value = "1200"
        self.addCleanup(clock.stop)

    def test_child_uses_parent_network_not_host(self):
        yml = canary.compose_content("fdcanary-abc-parent", "fdcanary-abc-client")
        self.assertIn('network_mode: "service:parent"', yml)
        self.assertIn('freshdock.enable: "true"', yml)
        self.assertIn('freshdock.mode: "watch"', yml)
        self.assertEqual(yml.count('freshdock.enable'), 1)
        for unsafe in ("privileged:", "volumes:", "ports:", "network_mode: host"):
            self.assertNotIn(unsafe, yml)

    def test_version_is_pinned(self):
        self.assertEqual(canary.IMAGE, "ghcr.io/turbootzz/freshdock:1.7.1")

    def test_preflight_wrong_host_blocked(self):
        with patch.object(canary.os, "geteuid", return_value=0), \
             patch.object(canary.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(canary, "cmd", return_value=Mock(stdout="not-omv", returncode=0)), \
             patch.object(canary, "containers") as containers:
            with self.assertRaisesRegex(canary.Refused, "Not the verified OMV host"):
                canary.preflight()
            containers.assert_not_called()

    def test_paused_production_transmission_does_not_block(self):
        other = [{"Name": "/transmission", "Id": "old",
                  "State": {"Status": "paused"}}]
        wud = {"Config": {"Labels": {
            "com.docker.compose.project": "wud",
            "com.docker.compose.service": "wud",
            "com.docker.compose.project.working_dir": "/docker/wud"},
            "Env": ["WUD_WATCHER_LOCAL_INCLUDE=^(?:brave|gluetun)$",
                    "WUD_WATCHER_LOCAL_WATCHBYDEFAULT=false",
                    "WUD_WATCHER_LOCAL_WATCHEVENTS=false"]},
            "State": {"Status": "running"}}
        with patch.object(canary.os, "geteuid", return_value=0), \
             patch.object(canary.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(canary, "cmd", side_effect=[
                 Mock(stdout="openmediavault\n", returncode=0),
                 Mock(returncode=0)]), \
             patch.object(canary, "containers", return_value=other), \
             patch.object(canary, "single", return_value=wud):
            before, regex = canary.preflight()
        self.assertEqual(before["/transmission"], ("old", "paused"))
        self.assertFalse(canary.re.search(regex, "fdcanary123-parent"))

    def test_wud_wildcard_watcher_blocks(self):
        wud = {"Config": {"Labels": {
            "com.docker.compose.project": "wud",
            "com.docker.compose.service": "wud",
            "com.docker.compose.project.working_dir": "/docker/wud"},
            "Env": ["WUD_WATCHER_LOCAL_INCLUDE=^.*$",
                    "WUD_WATCHER_LOCAL_WATCHBYDEFAULT=true"]},
            "State": {"Status": "running"}}
        with patch.object(canary.os, "geteuid", return_value=0), \
             patch.object(canary.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(canary, "cmd", side_effect=[
                 Mock(stdout="openmediavault\n", returncode=0),
                 Mock(returncode=0)]), \
             patch.object(canary, "containers", return_value=[]), \
             patch.object(canary, "single", return_value=wud):
            with self.assertRaisesRegex(canary.Refused, "not strictly isolated"):
                canary.preflight()

    def test_prior_test_container_blocks(self):
        existing = [{"Name": "/fdcanaryold-client", "Id": "test",
                     "State": {"Status": "created"}}]
        with patch.object(canary.os, "geteuid", return_value=0), \
             patch.object(canary.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(canary, "cmd", side_effect=[
                 Mock(stdout="openmediavault\n", returncode=0),
                 Mock(returncode=0)]), \
             patch.object(canary, "containers", return_value=existing), \
             patch.object(canary, "single") as inspect:
            with self.assertRaisesRegex(canary.Refused, "Previous Freshdock"):
                canary.preflight()
            inspect.assert_not_called()

    def test_existing_container_change_is_detected(self):
        o = [{"Name": "/gluetun", "Id": "id1", "State": {"Status": "running"}}]
        with patch.object(canary, "containers", return_value=o):
            self.assertTrue(canary.check_existing({"/gluetun": ("id1", "running")}))
            self.assertFalse(canary.check_existing({"/gluetun": ("id1", "paused")}))

    def test_failed_preflight_does_not_start_containers(self):
        with patch.object(canary, "preflight",
                          side_effect=canary.Refused("unsafe watcher")), \
             patch.object(canary, "cmd") as cmd:
            with self.assertRaisesRegex(canary.Refused, "unsafe watcher"):
                canary.run_test()
            cmd.assert_not_called()


if __name__ == "__main__":
    unittest.main()
