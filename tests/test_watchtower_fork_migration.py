"""Offline safety checks for Freshdock -> maintained Watchtower installation."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker/watchtower"))
import replace_freshdock as migration


def make_container(name, running=True, labels=None, network="bridge",
                   identity=None, health=None, cap_add=None, privileged=False,
                   env=None):
    identity = identity or name + "0123456789abcdef"
    return {
        "Id": identity,
        "Name": "/" + name,
        "State": {"Status": "running" if running else "exited",
                  "Paused": False,
                  "Health": {"Status": health} if health else {}},
        "Config": {"Image": "busybox:latest", "Labels": labels or {},
                   "Env": env or []},
        "HostConfig": {"NetworkMode": network,
                       "CapAdd": cap_add or [], "Privileged": privileged,
                       "RestartPolicy": {"Name": "no"}},
    }


def compose_labels():
    return {
        "com.docker.compose.project": "apps",
        "com.docker.compose.service": "app",
    }


class MigrationTests(unittest.TestCase):
    def fleet(self):
        labels = compose_labels() | {
            "freshdock.enable": "true",
            "freshdock.mode": "nightly",
            "freshdock.schedule": migration.MODE_CRON,
        }
        fleet = {f"app{i:02d}": make_container(
            f"app{i:02d}", labels=labels
        ) for i in range(21)}
        gluetun = make_container(
            "gluetun", labels=compose_labels() |
            {"com.docker.compose.service": "gluetun"}, health="healthy",
            cap_add=["NET_ADMIN"])
        fleet["gluetun"] = gluetun
        for name in ("transmission", "mullvad-browser"):
            fleet[name] = make_container(
                name, labels=compose_labels() |
                {"com.docker.compose.service": name},
                network="container:" + gluetun["Id"])
        return fleet

    def test_allowlist_is_exactly_24(self):
        fleet = self.fleet()
        targets = migration.selection(fleet)
        self.assertEqual(len(targets), 24)
        self.assertIn("gluetun", targets)
        self.assertIn("transmission", targets)
        self.assertIn("mullvad-browser", targets)
        self.assertNotIn("freshdock", targets)

    def test_vpn_firewall_bypass_and_capability_guards(self):
        fleet = self.fleet()
        fleet["gluetun"]["HostConfig"]["CapAdd"] = []
        with self.assertRaisesRegex(migration.Stop, "NET_ADMIN"):
            migration.selection(fleet)
        fleet = self.fleet()
        fleet["gluetun"]["Config"]["Env"] = [
            "FIREWALL_OUTBOUND_SUBNETS=0.0.0.0/0"]
        with self.assertRaisesRegex(migration.Stop, "nonlocal outbound"):
            migration.selection(fleet)
        fleet = self.fleet()
        fleet["gluetun"]["Config"]["Env"] = [
            "FIREWALL_OUTBOUND_SUBNETS=192.168.68.0/24"]
        self.assertEqual(len(migration.selection(fleet)), 24)
        fleet["transmission"]["HostConfig"]["Privileged"] = True
        with self.assertRaisesRegex(migration.Stop, "override"):
            migration.selection(fleet)

    def test_legacy_vaultwarden_explicitly_denied(self):
        fleet = self.fleet()
        fleet["vaultwarden"] = fleet.pop("app00")
        with self.assertRaisesRegex(migration.Stop, "Legacy Vaultwarden"):
            migration.selection(fleet)

    def test_ineligible_network_or_unreviewed_client_blocks(self):
        fleet = self.fleet()
        fleet["transmission"]["HostConfig"]["NetworkMode"] = "bridge"
        with self.assertRaisesRegex(migration.Stop, "CURRENT Gluetun"):
            migration.selection(fleet)
        fleet = self.fleet()
        fleet["unreviewed"] = make_container(
            "unreviewed", labels=compose_labels(),
            network="container:" + fleet["gluetun"]["Id"])
        with self.assertRaisesRegex(migration.Stop, "Unreviewed"):
            migration.selection(fleet)

    def test_selected_parent_with_unselected_live_client_blocks(self):
        fleet = self.fleet()
        fleet["stray"] = make_container(
            "stray", labels=compose_labels(),
            network="container:" + fleet["app00"]["Id"])
        with self.assertRaisesRegex(migration.Stop, "Unsafe partial network group"):
            migration.selection(fleet)

    def test_stopped_unselected_network_client_blocks(self):
        fleet = self.fleet()
        fleet["stray"] = make_container(
            "stray", running=False, labels=compose_labels(),
            network="container:" + fleet["app00"]["Id"])
        with self.assertRaisesRegex(migration.Stop, "Unsafe partial network group"):
            migration.selection(fleet)

    def test_dependency_label_cannot_hide_network_parent(self):
        fleet = self.fleet()
        fleet["transmission"]["Config"]["Labels"][
            "com.docker.compose.depends_on"] = "unrelated:service_started:false"
        with self.assertRaisesRegex(migration.Stop, "omits network parent"):
            migration.selection(fleet)
        fleet = self.fleet()
        fleet["transmission"]["Config"]["Labels"][
            "com.docker.compose.depends_on"] = "gluetun:service_started:false"
        self.assertEqual(len(migration.selection(fleet)), 24)
        fleet["transmission"]["Config"]["Labels"][
            "com.centurylinklabs.watchtower.depends-on"] = "unrelated"
        with self.assertRaisesRegex(migration.Stop, "omits network parent"):
            migration.selection(fleet)

    def test_explicit_legacy_watchtower_optout_blocks(self):
        fleet = self.fleet()
        fleet["app00"]["Config"]["Labels"][
            "com.centurylinklabs.watchtower.enable"] = "false"
        with self.assertRaisesRegex(migration.Stop, "legacy Watchtower opt-out"):
            migration.selection(fleet)

    def test_stopped_freshdock_target_count_blocks(self):
        fleet = self.fleet()
        fleet["app00"]["State"]["Status"] = "exited"
        with self.assertRaisesRegex(migration.Stop, "count changed"):
            migration.selection(fleet)

    def test_schedule_drift_blocks(self):
        fleet = self.fleet()
        fleet["app00"]["Config"]["Labels"]["freshdock.schedule"] = "wrong"
        with self.assertRaisesRegex(migration.Stop, "schedule"):
            migration.selection(fleet)

    def test_shoutrrr_tls_and_escapes(self):
        base = {
            "host": "smtp.example.org",
            "port": 587,
            "username": "alice@example.com",
            "password": "a&b:c?pw",
            "from": "sender@example.com",
            "to": ["one@example.com", "two@example.com"],
            "tls": "starttls",
        }
        smtp = migration.smtp_url(base)
        self.assertIn("encryption=ExplicitTLS", smtp)
        self.assertIn("requirestarttls=yes", smtp)
        self.assertIn("usestarttls=yes", smtp)
        self.assertIn("a%26b%3Ac%3Fpw", smtp)
        self.assertIn("one%40example.com%2Ctwo%40example.com", smtp)
        self.assertNotIn(base["password"], smtp)
        implicit = migration.smtp_url(
            base | {"port": 465, "tls": "implicit"})
        self.assertIn("encryption=ImplicitTLS", implicit)
        self.assertIn("requirestarttls=no", implicit)

    def test_compose_is_strictly_targeted_and_no_deploy_app_changes(self):
        wanted = migration.selection(self.fleet())
        obj = migration.compose(wanted)
        svc = obj["services"]["watchtower"]
        self.assertEqual(svc["image"], migration.VERSION)
        self.assertEqual(svc["command"][:2],
                         ["--schedule", "0 45 2 * * *"])
        self.assertEqual(svc["command"][-24:], list(wanted))
        self.assertEqual(len(svc["command"]), 27)
        self.assertEqual(svc["environment"]["WATCHTOWER_NOTIFICATION_URL"],
                         "/run/secrets/notification_url")
        self.assertIn(
            "./notification_url:/run/secrets/notification_url:ro",
            svc["volumes"],
        )
        self.assertNotIn("app00", obj["services"])
        self.assertNotIn("freshdock", obj["services"])
        self.assertNotIn("password", json.dumps(obj).lower())

    def test_post_update_verifier_detects_outage(self):
        fleet = self.fleet()
        names = list(migration.selection(fleet))
        updater = make_container(
            "watchtower", labels=compose_labels())
        updater["Config"]["Cmd"] = [
            "--schedule", migration.SCHEDULE, "--no-startup-message", *names]
        fleet["watchtower"] = updater
        old = make_container("freshdock", running=False)
        old["HostConfig"]["RestartPolicy"]["Name"] = "no"
        fleet["freshdock"] = old
        self.assertEqual(migration.verify_runtime(
            fleet, {"container_names": names}), names)
        fleet["app00"]["State"]["Status"] = "exited"
        with self.assertRaises(migration.Stop):
            migration.verify_runtime(fleet, {"container_names": names})
        fleet["app00"]["State"]["Status"] = "running"
        fleet["gluetun"]["State"]["Health"]["Status"] = "unhealthy"
        with self.assertRaisesRegex(migration.Stop, "Gluetun"):
            migration.verify_runtime(fleet, {"container_names": names})
        fleet["gluetun"]["State"]["Health"]["Status"] = "healthy"
        fleet["watchtower"]["Config"]["Cmd"][1] = "0 55 2 * * *"
        with self.assertRaisesRegex(migration.Stop, "schedule"):
            migration.verify_runtime(fleet, {"container_names": names})

    def test_verifier_timer_and_notification_security(self):
        service, timer = migration.verifier_units()
        self.assertIn("--verify --notify-on-failure", service)
        self.assertIn("OnCalendar=*-*-* 05:00:00 America/New_York", timer)
        self.assertIn("Persistent=true", timer)
        self.assertNotIn("password", service.lower() + timer.lower())

    def test_smtp_alert_requires_real_tls(self):
        cfg = {
            "host": "smtp.example.org", "port": 587,
            "username": "alice", "password": "private-credential",
            "from": "alice@example.org", "to": ["bob@example.org"],
            "tls": "starttls",
        }
        with patch.object(migration.smtplib, "SMTP") as ctor:
            client = ctor.return_value.__enter__.return_value
            client.has_extn.return_value = False
            with self.assertRaises(migration.Stop):
                migration.smtp_send(cfg, "test", "body")
            client.login.assert_not_called()
            client.send_message.assert_not_called()
        with patch.object(migration.smtplib, "SMTP") as ctor:
            client = ctor.return_value.__enter__.return_value
            client.has_extn.return_value = True
            migration.smtp_send(cfg, "test", "body")
            client.starttls.assert_called_once()
            client.login.assert_called_once_with("alice", "private-credential")
            client.send_message.assert_called_once()

    def test_read_only_default_does_not_call_apply(self):
        with patch.object(migration, "preflight",
                          return_value=({}, tuple(
                              [f"app{i}" for i in range(21)] +
                              list(migration.VPN)),
                              {"password": "x"})), \
             patch.object(migration, "apply") as mutate, \
             patch("sys.argv", ["replace_freshdock.py"]):
            self.assertEqual(migration.main(), 0)
            mutate.assert_not_called()

    def test_stage_writes_only_new_root(self):
        source = Path(migration.__file__).read_text()
        for name in ("docker compose down", "docker rm -f",
                     "docker volume rm", "docker prune",
                     "docker compose restart"):
            self.assertNotIn(name, source)


if __name__ == "__main__":
    unittest.main()
