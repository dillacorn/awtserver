"""Offline safety tests for WUD disposable Compose namespace canary."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker" / "wud"))
import wud_stack_canary as canary

class CanaryTests(unittest.TestCase):
    def test_client_shares_network_and_has_no_sensitive_mounts(self):
        compose = canary.compose_yaml("wudcanary000-parent", "wudcanary000-client")
        self.assertIn('network_mode: "service:vpn-parent"', compose)
        self.assertIn("image: alpine:3.20.10", compose)
        self.assertIn("image: alpine:3.24.2", compose)
        for forbidden in ("privileged:", "volumes:", "ports:", "/docker/privacy"):
            self.assertNotIn(forbidden, compose)

    def test_snapraid_blocks_before_inspecting_containers(self):
        with patch.object(canary.os, "geteuid", return_value=0), \
             patch.object(canary.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(canary, "call", side_effect=[Mock(stdout="openmediavault"), Mock(returncode=0)]), \
             patch.object(canary, "snapraid_active", return_value=True), \
             patch.object(canary, "check_disk_errors") as disk, \
             patch.object(canary, "all_containers") as containers:
            with self.assertRaisesRegex(canary.Blocked, "SnapRAID still running"):
                canary.baseline()
            disk.assert_not_called()
            containers.assert_not_called()

    def test_sata_error_blocks(self):
        log = "ata13.00: failed command: READ DMA EXT\nI/O error, dev sdb, sector 100"
        with patch.object(canary, "call", return_value=Mock(returncode=0, stdout=log)):
            with self.assertRaisesRegex(canary.Blocked, "Recent sdb/ata13"):
                canary.check_disk_errors()

    def test_unavailable_kernel_log_blocks(self):
        with patch.object(canary, "call", return_value=Mock(returncode=1, stdout="")):
            with self.assertRaisesRegex(canary.Blocked, "Cannot check"):
                canary.check_disk_errors()

    def test_watcher_label_override_blocks(self):
        existing = [{"Name": "/existing", "Config": {"Labels": {"wud.watch": "TRUE"}}}]
        with patch.object(canary.os, "geteuid", return_value=0), \
             patch.object(canary.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(canary, "call", side_effect=[Mock(stdout="openmediavault"), Mock(returncode=0)]), \
             patch.object(canary, "snapraid_active", return_value=False), \
             patch.object(canary, "check_disk_errors"), \
             patch.object(canary, "all_containers", return_value=existing), \
             patch.object(canary, "inspect") as inspect:
            with self.assertRaisesRegex(canary.Blocked, "wud.watch=true"):
                canary.baseline()
            inspect.assert_not_called()

    def test_existing_canary_blocks(self):
        existing = [{"Name": "/wudcanaryold-parent", "Config": {"Labels": {}}}]
        with patch.object(canary.os, "geteuid", return_value=0), \
             patch.object(canary.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(canary, "call", side_effect=[Mock(stdout="openmediavault"), Mock(returncode=0)]), \
             patch.object(canary, "snapraid_active", return_value=False), \
             patch.object(canary, "check_disk_errors"), \
             patch.object(canary, "all_containers", return_value=existing), \
             patch.object(canary, "inspect") as inspect:
            with self.assertRaisesRegex(canary.Blocked, "Leftover canary"):
                canary.baseline()
            inspect.assert_not_called()

    def test_wrong_compose_service_blocks(self):
        with self.assertRaisesRegex(canary.Blocked, "unexpected Compose"):
            canary.compose_labels({"Config": {"Labels": {}}},
                                  "privacy", "gluetun", "/docker/privacy")

    def test_production_state_change_reports_false(self):
        item = {"Name": "/gluetun", "Id": "xyz", "State": {"Status": "running"}}
        with patch.object(canary, "all_containers", return_value=[item]):
            self.assertTrue(canary.unchanged({"/gluetun": ("xyz", "running")}))
            self.assertFalse(canary.unchanged({"/gluetun": ("xyz", "paused")}))

    def test_unsafe_preflight_creates_no_test_containers(self):
        with patch.object(canary, "baseline", side_effect=canary.Blocked("transmission paused")), \
             patch.object(canary, "call") as docker:
            with self.assertRaisesRegex(canary.Blocked, "transmission paused"):
                canary.test()
            docker.assert_not_called()

if __name__ == "__main__":
    unittest.main()
