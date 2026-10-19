"""Safety regression tests for three-container Freshdock privacy enrollment."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker" / "freshdock"))
import enroll_privacy_stack as privacy


class PrivacyEnrollmentTests(unittest.TestCase):
    def setUp(self):
        # Deterministic time for offline preflight tests, including UTC CI.
        clock = patch.object(privacy, "datetime")
        obj = clock.start()
        obj.now.return_value.strftime.return_value = "1200"
        self.addCleanup(clock.stop)

    def test_stopped_archives_are_not_active_enrollment(self):
        base = {
            "freshdock.enable": "true",
            "com.docker.compose.project": "ntfy",
            "com.docker.compose.service": "application",
        }
        current = {"Name": "/app-ntfy",
                   "State": {"Status": "running"},
                   "Config": {"Labels": dict(base)}}
        old = {"Name": "/app-ntfy-old-1792392342",
               "State": {"Status": "exited", "Paused": False},
               "Config": {"Labels": dict(base)}}
        fleet = {"app-ntfy": current,
                 "app-ntfy-old-1792392342": old}
        self.assertEqual(privacy.current_enrolled(fleet), {"app-ntfy"})

    def test_archive_must_be_stopped_with_matching_live_successor(self):
        base = {
            "freshdock.enable": "true",
            "com.docker.compose.project": "ntfy",
            "com.docker.compose.service": "application",
        }
        old = {"State": {"Status": "running", "Paused": False},
               "Config": {"Labels": dict(base)}}
        active = {"State": {"Status": "running"},
                  "Config": {"Labels": dict(base)}}
        fleet = {"app-ntfy": active,
                 "app-ntfy-old-1792392342": old}
        with self.assertRaisesRegex(privacy.Stop, "not stopped"):
            privacy.current_enrolled(fleet)
        old["State"]["Status"] = "exited"
        active["Config"]["Labels"]["com.docker.compose.service"] = "wrong"
        with self.assertRaisesRegex(privacy.Stop, "identity mismatch"):
            privacy.current_enrolled(fleet)
        active["Config"]["Labels"]["com.docker.compose.service"] = "application"
        del fleet["app-ntfy"]
        with self.assertRaisesRegex(privacy.Stop, "no running"):
            privacy.current_enrolled(fleet)

    def test_legacy_archive_name_is_not_treated_as_normal(self):
        bad = {"State": {"Status": "exited", "Paused": False},
               "Config": {"Labels": {"freshdock.enable": "true"}}}
        with self.assertRaisesRegex(privacy.Stop, "no running"):
            privacy.current_enrolled({"app-ntfy-old-1792392342": bad})

    def test_uses_live_opted_in_fleet_without_hardcoded_names(self):
        policy = privacy.policy()
        own = {
            "com.docker.compose.project": "existing",
            "com.docker.compose.service": "service",
            "com.docker.compose.project.working_dir": "/docker/existing",
            "com.docker.compose.project.config_files": "/docker/existing/compose.yml",
        }
        fleet = {}
        for i in range(21):
            fleet[f"selected-{i:02d}"] = {
                "State": {"Status": "running", "Paused": False},
                "Config": {"Labels": own | policy},
            }
        fleet["freshdock"] = {
            "State": {"Status": "running"},
            "Config": {
                "Image": "ghcr.io/turbootzz/freshdock:1.7.1",
                "Env": ["FRESHDOCK_WATCH_ALL=false",
                        "FRESHDOCK_COMPOSE_AWARE=true"],
                "Labels": {},
            },
        }
        with patch.object(privacy.os, "geteuid", return_value=0), \
             patch.object(privacy.socket, "gethostname",
                          return_value="openmediavault"), \
             patch.object(privacy, "containers", return_value=fleet), \
             patch.object(privacy.Path, "is_file", return_value=True):
            with self.assertRaisesRegex(
                privacy.Stop,
                "Privacy Compose project no longer has all five containers"
            ):
                privacy.plan()

    def test_known_unsafe_updater_refuses_apply(self):
        self.assertFalse(privacy.SHARED_NETWORK_AUTOUPDATE_VERIFIED)
        with patch.object(privacy, "plan", return_value=({}, (), {})), \
             patch.object(privacy, "apply") as update:
            with patch("sys.argv", ["enroll_privacy_stack.py", "--apply"]):
                self.assertEqual(privacy.main(), 1)
            update.assert_not_called()

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
             patch.object(privacy, "OVERLAY", Mock(**{"exists.return_value": True})), \
             patch.object(privacy, "containers") as c:
            with self.assertRaisesRegex(privacy.Stop, "Existing privacy"):
                privacy.plan()
            c.assert_not_called()

    def test_parent_is_health_gated_before_clients(self):
        text = Path(privacy.__file__).read_text()
        parent = text.index('"--force-recreate", "gluetun"')
        health_gate = text.index('raise Stop("Recreated Gluetun did not become VPN healthy")')
        clients = text.index('"transmission", "mullvad-browser", timeout=240')
        self.assertLess(parent, health_gate)
        self.assertLess(health_gate, clients)
        self.assertGreaterEqual(text.count('"--no-deps"'), 2)

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
