"""Retired Freshdock deletion must not interrupt Watchtower's health alerts."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker/watchtower"))
from test_watchtower_fork_migration import make_container, compose_labels
import watchtower_verify as wt
import retire_freshdock as retire


def fleet():
    labels = compose_labels()
    all_containers = {name: make_container(name, labels=labels.copy())
                      for name in wt.EXPECTED}
    all_containers["gluetun"]["HostConfig"]["CapAdd"] = ["NET_ADMIN"]
    all_containers["gluetun"]["State"]["Health"] = {"Status": "healthy"}
    parent = all_containers["gluetun"]["Id"]
    for name in ("transmission", "mullvad-browser"):
        all_containers[name]["HostConfig"]["NetworkMode"] = "container:" + parent
    names = sorted(wt.EXPECTED)
    updater = make_container("watchtower")
    updater["Config"]["Cmd"] = [
        "--schedule", wt.SCHEDULE, "--no-startup-message", *names]
    updater["Config"]["Image"] = "nickfedor/watchtower:1.23.1"
    all_containers["watchtower"] = updater
    return all_containers, names


class StandaloneVerifierTests(unittest.TestCase):
    def test_unlabeled_services_verify_after_freshdock_deletion(self):
        all_containers, names = fleet()
        self.assertEqual(wt.verify_runtime(all_containers, names), names)
        self.assertNotIn("freshdock", all_containers)
        for obj in all_containers.values():
            self.assertNotIn("freshdock.enable", obj["Config"]["Labels"])

    def test_outage_bad_deps_and_firewall_bypass_are_detected(self):
        all_containers, names = fleet()
        all_containers["app-ntfy"]["State"]["Status"] = "exited"
        with self.assertRaisesRegex(wt.Stop, "app-ntfy: application not running"):
            wt.verify_runtime(all_containers, names)
        all_containers, names = fleet()
        all_containers["transmission"]["HostConfig"]["NetworkMode"] = "bridge"
        with self.assertRaisesRegex(wt.Stop, "current Gluetun"):
            wt.verify_runtime(all_containers, names)
        all_containers, names = fleet()
        all_containers["gluetun"]["Config"]["Env"] = [
            "FIREWALL_OUTBOUND_SUBNETS=0.0.0.0/0"]
        with self.assertRaisesRegex(wt.Stop, "public firewall bypass"):
            wt.verify_runtime(all_containers, names)
        all_containers, names = fleet()
        all_containers["app-flame"]["Config"]["Labels"][
            "com.docker.compose.project.config_files"] = "/missing/fake/compose.yml"
        with self.assertRaisesRegex(wt.Stop, "Compose file unavailable"):
            wt.verify_runtime(all_containers, names)
        all_containers, names = fleet()
        all_containers["watchtower"]["Config"]["Cmd"][-1] = "vaultwarden"
        with self.assertRaisesRegex(wt.Stop, "allowlist changed"):
            wt.verify_runtime(all_containers, names)
        all_containers, names = fleet()
        all_containers["unknown"] = make_container(
            "unknown", network="container:" + all_containers["gluetun"]["Id"])
        with self.assertRaisesRegex(wt.Stop, "additional Gluetun namespace"):
            wt.verify_runtime(all_containers, names)


    def test_28_targets_and_standalone_trawl_is_rejected(self):
        all_containers, names = fleet()
        parent = all_containers["gluetun"]["Id"]
        for name in wt.ADDITIONAL:
            c = make_container(name, labels=compose_labels())
            if name in wt.GLUETUN_CLIENTS:
                c["HostConfig"]["NetworkMode"] = "container:" + parent
            all_containers[name] = c
        names = sorted(wt.EXPANDED)
        all_containers["watchtower"]["Config"]["Cmd"] = [
            "--schedule", wt.SCHEDULE, "--no-startup-message", *names
        ]
        self.assertEqual(wt.verify_runtime(all_containers, names), names)
        all_containers["trawl"]["Config"]["Labels"] = {}
        with self.assertRaisesRegex(wt.Stop, "missing Compose project/service"):
            wt.verify_runtime(all_containers, names)

    def test_unapproved_second_transmission_is_rejected(self):
        all_containers, names = fleet()
        parent = all_containers["gluetun"]["Id"]
        all_containers["transmission-brother"] = make_container(
            "transmission-brother", network="container:" + parent
        )
        with self.assertRaisesRegex(wt.Stop, "additional Gluetun namespace"):
            wt.verify_runtime(all_containers, names)

    def test_original_targets_reject_unenrolled_trawl(self):
        all_containers, names = fleet()
        all_containers["trawl"] = make_container(
            "trawl", network="container:" + all_containers["gluetun"]["Id"]
        )
        with self.assertRaisesRegex(wt.Stop, "excluded dependent trawl"):
            wt.verify_runtime(all_containers, names)

    def test_private_credentials_and_allowlist_mode(self):
        cfg = {
            "host": "smtp.example.org", "port": 587,
            "username": "alice", "password": "not-committed",
            "from": "alice@example.org", "to": ["bob@example.org"],
            "tls": "starttls",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "targets.json"
            manifest.write_text(json.dumps({
                "schedule": wt.SCHEDULE,
                "container_names": sorted(wt.EXPECTED),
            }))
            manifest.chmod(0o600)
            private = root / "alert_smtp.json"
            private.write_text(json.dumps(cfg))
            private.chmod(0o600)
            self.assertEqual(wt.read_targets(root), sorted(wt.EXPECTED))
            manifest.write_text(json.dumps({
                "schedule": wt.SCHEDULE,
                "container_names": sorted(wt.EXPANDED)
            }))
            self.assertEqual(wt.read_targets(root), sorted(wt.EXPANDED))
            manifest.write_text(json.dumps({
                "schedule": wt.SCHEDULE,
                "container_names": sorted(wt.EXPECTED)
            }))
            self.assertEqual(wt.read_smtp(root), cfg)
            private.chmod(0o644)
            with self.assertRaisesRegex(wt.Stop, "permissions too open"):
                wt.read_smtp(root)
            private.chmod(0o600)
            manifest.write_text(json.dumps({"schedule": wt.SCHEDULE,
                                            "container_names": ["app-ntfy"]}))
            with self.assertRaisesRegex(wt.Stop, "24/28-target policy"):
                wt.read_targets(root)

    def test_smtp_mandatory_tls(self):
        cfg = {
            "host": "smtp.example.org", "port": 587,
            "username": "alice", "password": "secret",
            "from": "alice@example.org", "to": ["bob@example.org"],
            "tls": "starttls",
        }
        with patch.object(wt.smtplib, "SMTP") as smtp:
            client = smtp.return_value
            client.has_extn.return_value = False
            with self.assertRaisesRegex(wt.Stop, "required STARTTLS"):
                wt.send_tls(cfg, "test", "test")
            client.login.assert_not_called()
        with patch.object(wt.smtplib, "SMTP") as smtp:
            client = smtp.return_value
            client.has_extn.return_value = True
            wt.send_tls(cfg, "test", "test")
            client.starttls.assert_called_once()
            client.login.assert_called_once_with("alice", "secret")


class RetirementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wtci-retire-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.root = root / "watchtower-fork"
        self.old = root / "freshdock"
        self.units = root / "units"
        self.root.mkdir()
        self.old.mkdir()
        self.units.mkdir()
        self.service = self.units / "watchtower-fork-verify.service"
        self.source = root / "watchtower_verify.py.from-github"
        self.source.write_text(Path(wt.__file__).read_text())
        self.original_service = (
            "[Service]\nType=oneshot\n" + retire.OLD_EXEC + "\n")
        self.service.write_text(self.original_service)
        self.credentials = {
            "host": "smtp.example.org", "port": 587,
            "username": "alice", "password": "fake",
            "from": "alice@example.org", "to": ["bob@example.org"],
            "tls": "starttls",
        }
        (self.root / "targets.json").write_text(json.dumps({
            "container_names": sorted(wt.EXPECTED),
            "schedule": wt.SCHEDULE,
        }))
        (self.root / "targets.json").chmod(0o600)
        (self.root / "replace_freshdock.py").write_text("# retired entry point\n")

    def common(self):
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(retire, "ROOT", self.root))
        stack.enter_context(patch.object(retire, "OLD", self.old))
        stack.enter_context(patch.object(retire, "UNITS", self.units))
        stack.enter_context(patch.object(retire, "SERVICE", self.service))
        stack.enter_context(patch.object(wt, "ROOT", self.root))
        stack.enter_context(patch.object(wt, "send_tls"))
        stack.enter_context(patch.object(wt, "verify_runtime"))
        return stack

    def test_successful_retirement_only_deletes_old_app(self):
        before, _ = fleet()
        after = dict(before)
        after.pop("freshdock", None)
        with self.common(), \
             patch.object(wt, "docker_inventory", return_value=after), \
             patch.object(retire, "command",
                          return_value=SimpleNamespace(returncode=0)) as cmd:
            retire.apply(self.original_service, self.credentials, self.source)
            self.assertFalse(self.old.exists())
            self.assertFalse((self.root / "replace_freshdock.py").exists())
            self.assertTrue((self.root / "watchtower_verify.py").is_file())
            self.assertEqual((self.root / "alert_smtp.json").stat().st_mode & 0o777,
                             0o600)
            self.assertIn(retire.NEW_EXEC, self.service.read_text())
            self.assertTrue(any(call.args[:3] == ("docker", "rm", "freshdock")
                                for call in cmd.call_args_list))
            self.assertFalse(any("volume" in call.args or "prune" in call.args
                                 for call in cmd.call_args_list))

    def test_failed_systemd_handoff_preserves_old_service(self):
        def failed_command(*args, **kwargs):
            if args[:3] == ("systemctl", "start", "watchtower-fork-verify.service"):
                raise wt.Stop("Systemd verifier failed")
            return SimpleNamespace(returncode=0)
        with self.common(), \
             patch.object(retire, "command", side_effect=failed_command) as cmd:
            with self.assertRaisesRegex(wt.Stop, "Systemd verifier failed"):
                retire.apply(self.original_service, self.credentials, self.source)
            self.assertTrue(self.old.exists())
            self.assertEqual(self.service.read_text(), self.original_service)
            self.assertFalse((self.root / "watchtower_verify.py").exists())
            self.assertFalse((self.root / "alert_smtp.json").exists())
            self.assertTrue((self.root / "replace_freshdock.py").exists())
            self.assertFalse(any(c.args[:3] == ("docker", "rm", "freshdock")
                                 for c in cmd.call_args_list))

    def test_prefix_check_is_component_safe(self):
        self.assertTrue(retire.has_prefix("/docker/freshdock/private", "/docker/freshdock"))
        self.assertFalse(retire.has_prefix("/docker/freshdock-other", "/docker/freshdock"))
        self.assertFalse(retire.has_prefix("/docker/freshdoc", "/docker/freshdock"))


if __name__ == "__main__":
    unittest.main()
