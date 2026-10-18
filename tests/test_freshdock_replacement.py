"""Offline safeguards for staged OMV WUD -> Freshdock replacement."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "docker" / "freshdock"
sys.path.insert(0, str(ROOT))
import replace_wud_daemon as stage1
import enroll_services as stage2


class MigrationTests(unittest.TestCase):
    def test_freshdock_scope_is_strictly_opt_in(self):
        self.assertIn('"false"', (ROOT / "compose.yml").read_text())
        self.assertEqual(stage2.SKIP, {
            "vaultwarden", "nginx-vaultwarden", "gluetun",
            "transmission", "mullvad-browser",
        })
        self.assertEqual(stage2.CRON, "45 2 * * *")
        self.assertEqual(stage1.IMAGE, "ghcr.io/turbootzz/freshdock:1.7.1")

    def test_label_overlay_only_changes_enabled_services(self):
        output = stage2.canary_labels({"application": "app", "tailscale": "ts"})
        self.assertIn('freshdock.enable: "true"', output)
        self.assertEqual(output.count('freshdock.enable: "true"'), 2)
        self.assertIn('freshdock.schedule: "45 2 * * *"', output)
        self.assertNotIn("gluetun:", output)

    def test_compose_order_parents_before_dependents(self):
        all_services = {
            "services": {
                "web": {"depends_on": {"tailscale": {"condition": "service_healthy"}},
                        "network_mode": "service:tailscale"},
                "tailscale": {},
                "database": {},
            }
        }
        ordered = stage2.order_services(
            {"web": "web", "tailscale": "ts", "database": "db"},
            all_services)
        self.assertLess(ordered.index("tailscale"), ordered.index("web"))

    def test_semantic_diff_only_whitelists_freshdock_labels(self):
        existing = {"services": {
            "web": {"image": "alpine", "volumes": ["/old:/data"],
                    "labels": {"existing": "value"}},
        }}
        after = {"services": {
            "web": {"image": "alpine", "volumes": ["/old:/data"],
                    "labels": {"existing": "value",
                               "freshdock.enable": "true",
                               "freshdock.mode": "nightly",
                               "freshdock.schedule": "45 2 * * *",
                               "freshdock.notify": "true"}},
        }}
        self.assertEqual(stage2.without_freshdock(after, {"web": "w"}), existing)
        after["services"]["web"]["volumes"] = ["/wrong:/data"]
        self.assertNotEqual(stage2.without_freshdock(after, {"web": "w"}), existing)

    def test_network_namespace_mismatch_blocks(self):
        project = {"services": {"client": {"network_mode": "service:parent"},
                                "parent": {}}}
        current = {
            "parent": {"Name": "/parent", "Id": "newid",
                       "Config": {"Labels": {
                           "com.docker.compose.project": "p",
                           "com.docker.compose.service": "parent"}},
                       "HostConfig": {"NetworkMode": "bridge"}},
            "client": {"Name": "/client", "Id": "clientid",
                       "Config": {"Labels": {
                           "com.docker.compose.project": "p",
                           "com.docker.compose.service": "client"}},
                       "HostConfig": {"NetworkMode": "container:oldid"}},
        }
        with self.assertRaisesRegex(stage2.Stop, "stale network"):
            stage2.verify_network("p", {"client": "client", "parent": "parent"},
                                  project, current)
        current["client"]["HostConfig"]["NetworkMode"] = "container:newid"
        stage2.verify_network("p", {"client": "client", "parent": "parent"},
                              project, current)

    def test_generated_toml_has_private_email_and_safe_scope(self):
        env = {
            stage1.REQUIRED["host"]: "smtp.example.test",
            stage1.REQUIRED["port"]: "587",
            stage1.REQUIRED["username"]: "private-user",
            stage1.REQUIRED["password"]: "sensitive-secret",
            stage1.REQUIRED["from"]: "sender@example.test",
            stage1.REQUIRED["to"]: "receiver@example.test",
        }
        result = stage1.smtp_toml(env)
        self.assertIn('tls = "starttls"', result)
        self.assertIn('watch_all = false', result)
        self.assertIn('triggers = ["succeeded", "failed"]', result)
        self.assertIn('password = "sensitive-secret"', result)

    def test_daemon_preflight_wrong_host_creates_nothing(self):
        with patch.object(stage1.os, "geteuid", return_value=0), \
             patch.object(stage1.socket, "gethostname", return_value="wrong"), \
             patch.object(stage1, "docker") as client:
            with self.assertRaisesRegex(stage1.Refused, "Wrong host"):
                stage1.assert_live_state()
            client.assert_not_called()

    def test_enrollment_wrong_host_creates_nothing(self):
        with patch.object(stage2.os, "geteuid", return_value=0), \
             patch.object(stage2.socket, "gethostname", return_value="wrong"), \
             patch.object(stage2, "docker") as client:
            with self.assertRaisesRegex(stage2.Stop, "confirmed OMV"):
                stage2.plan()
            client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
