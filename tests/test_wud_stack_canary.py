"""Offline safeguards for the disposable WUD shared-namespace test."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker" / "wud"))
import wud_stack_canary as canary


class CanaryTests(unittest.TestCase):
    def test_compose_shared_network_only(self):
        text = canary.compose_yaml("wudcanary000-parent", "wudcanary000-client")
        self.assertIn('network_mode: "service:vpn-parent"', text)
        self.assertIn("image: alpine:3.20.0", text)
        self.assertIn("container_name: wudcanary000-client", text)
        for forbidden in ("privileged:", "volumes:", "ports:", "/docker/privacy"):
            self.assertNotIn(forbidden, text)

    def test_watcher_label_override_blocks(self):
        existing = [{"Name": "/existing", "Config": {"Labels": {"wud.watch": "TRUE"}}}]
        with patch.object(canary.os, "geteuid", return_value=0), \
             patch.object(canary.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(canary, "call", side_effect=[
                 Mock(stdout="openmediavault"), Mock(returncode=0)]), \
             patch.object(canary, "all_containers", return_value=existing), \
             patch.object(canary, "inspect") as inspector:
            with self.assertRaisesRegex(canary.Blocked, "wud.watch=true"):
                canary.baseline()
            inspector.assert_not_called()

    def test_existing_canary_blocks(self):
        existing = [{"Name": "/wudcanaryold-parent", "Config": {"Labels": {}}}]
        with patch.object(canary.os, "geteuid", return_value=0), \
             patch.object(canary.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(canary, "call", side_effect=[
                 Mock(stdout="openmediavault"), Mock(returncode=0)]), \
             patch.object(canary, "all_containers", return_value=existing), \
             patch.object(canary, "inspect") as inspector:
            with self.assertRaisesRegex(canary.Blocked, "Leftover canary"):
                canary.baseline()
            inspector.assert_not_called()

    def test_nonproduction_state_does_not_block_canary(self):
        # The canary is completely separate: stale/paused production containers
        # and SnapRAID must not be preconditions for inspecting WUD.
        original = [{"Name": "/transmission", "Id": "paused-id",
                     "State": {"Status": "paused"},
                     "Config": {"Labels": {}}}]
        wud = {"Config": {"Image": canary.WUD_IMAGE,
               "Env": ["WUD_WATCHER_LOCAL_INCLUDE=^(?:brave|gluetun)$",
                       "WUD_WATCHER_LOCAL_WATCHBYDEFAULT=false",
                       "WUD_WATCHER_LOCAL_WATCHEVENTS=false"],
               "Labels": {"com.docker.compose.project": "wud",
                          "com.docker.compose.service": "wud",
                          "com.docker.compose.project.working_dir": "/docker/wud"}},
               "State": {"Status": "running", "Health": {"Status": "healthy"}}}
        with patch.object(canary.os, "geteuid", return_value=0), \
             patch.object(canary.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(canary, "call", side_effect=[
                 Mock(stdout="openmediavault"), Mock(returncode=0)]), \
             patch.object(canary, "all_containers", return_value=original), \
             patch.object(canary, "inspect", return_value=wud):
            before, regex = canary.baseline()
            self.assertEqual(before["/transmission"], ("paused-id", "paused"))
            self.assertFalse(canary.re.search(regex, "wudcanary123-parent"))

    def test_missing_or_unhealthy_wud_blocks(self):
        wud = {"Config": {"Image": canary.WUD_IMAGE, "Labels": {}},
               "State": {"Status": "created"}}
        with patch.object(canary.os, "geteuid", return_value=0), \
             patch.object(canary.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(canary, "call", side_effect=[
                 Mock(stdout="openmediavault"), Mock(returncode=0)]), \
             patch.object(canary, "all_containers", return_value=[]), \
             patch.object(canary, "inspect", return_value=wud):
            with self.assertRaises(canary.Blocked):
                canary.baseline()

    def test_wrong_compose_service_blocks(self):
        with self.assertRaisesRegex(canary.Blocked, "unexpected Compose"):
            canary.compose_labels({"Config": {"Labels": {}}},
                                  "wud", "wud", "/docker/wud")

    def test_production_state_change_detected(self):
        item = {"Name": "/gluetun", "Id": "xyz", "State": {"Status": "running"}}
        with patch.object(canary, "all_containers", return_value=[item]):
            self.assertTrue(canary.unchanged({"/gluetun": ("xyz", "running")}))
            self.assertFalse(canary.unchanged({"/gluetun": ("xyz", "paused")}))

    def test_failed_preflight_creates_no_test_containers(self):
        with patch.object(canary, "baseline", side_effect=canary.Blocked("wrong host")), \
             patch.object(canary, "call") as docker:
            with self.assertRaisesRegex(canary.Blocked, "wrong host"):
                canary.test()
            docker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
