"""Safety regression tests for three-container Freshdock privacy enrollment."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker" / "freshdock"))
import enroll_privacy_stack as privacy


class PrivacyEnrollmentTests(unittest.TestCase):
    def test_scope_and_label_policy(self):
        self.assertEqual(privacy.SERVICES,
                         ("gluetun", "transmission", "mullvad-browser"))
        self.assertEqual(privacy.OTHER,
                         ("tailscale-transmission", "tailscale-mullvad"))
        self.assertEqual(privacy.policy(), {
            "freshdock.enable": "true",
            "freshdock.mode": "nightly",
            "freshdock.schedule": "45 2 * * *",
            "freshdock.notify": "true",
        })
        text = privacy.overlay_text()
        for name in privacy.SERVICES:
            self.assertIn("  " + name + ":", text)
        for name in privacy.OTHER + ("vaultwarden",):
            self.assertNotIn("  " + name + ":", text)
        self.assertEqual(text.count("freshdock.enable:"), 3)
        self.assertNotIn("watch_all", text)

    def test_vpn_does_not_pass_without_tun0(self):
        c = {"State": {"Status": "running", "Health": {"Status": "healthy"}}}
        class Result:
            returncode = 0
            stdout = "1.1.1.1 via 192.168.1.1 dev eth0"
        with patch.object(privacy, "call", return_value=Result()):
            self.assertFalse(privacy.healthy_vpn(c))
        c["State"]["Health"]["Status"] = "unhealthy"
        with patch.object(privacy, "call") as call:
            self.assertFalse(privacy.healthy_vpn(c))
            call.assert_not_called()

    def test_planned_mode_never_applies(self):
        with patch.object(privacy, "plan", return_value=({}, (), {})), \
             patch.object(privacy, "apply") as apply:
            with patch("sys.argv", ["enroll_privacy_stack.py"]):
                self.assertEqual(privacy.main(), 0)
            apply.assert_not_called()

    def test_existing_overlay_is_a_hard_stop(self):
        with patch.object(privacy.os, "geteuid", return_value=0), \
             patch.object(privacy.socket, "gethostname", return_value="openmediavault"), \
             patch.object(privacy.OVERLAY, "exists", return_value=True), \
             patch.object(privacy, "containers") as c:
            with self.assertRaisesRegex(privacy.Stop, "Existing privacy"):
                privacy.plan()
            c.assert_not_called()

    def test_safety_properties_in_source(self):
        text = Path(privacy.__file__).read_text()
        self.assertIn('"--pull", "never"', text)
        self.assertIn('"--no-build"', text)
        self.assertIn('"--force-recreate"', text)
        self.assertIn('"transmission", "mullvad-browser"', text)
        self.assertIn('call("docker", "update", "--restart=no", "freshdock"', text)
        self.assertIn('"service:gluetun"', text)
        self.assertIn('len(current) == 24', text)
        self.assertNotIn("docker compose down", text)


if __name__ == "__main__":
    unittest.main()
