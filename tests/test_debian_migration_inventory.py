"""Offline tests: Debian migration discovery must not leak config secret values."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "migration" / "debian"))
import inventory


class InventoryTests(unittest.TestCase):
    def test_fstab_filters_credential_options(self):
        fstab = (
            "UUID=aaa /srv/archive ext4 defaults,nofail 0 2\n"
            "//nas/private /mnt/remote cifs credentials=/root/.secret,password=hidden,rw 0 0\n"
            "# private comment\n"
        )
        with patch.object(inventory, "text", return_value=fstab):
            rows = inventory.fstab()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["source"], "//nas/private")
        self.assertEqual(rows[1]["safe_options"], ["rw"])
        self.assertEqual(rows[1]["other_options_redacted"], 2)
        self.assertNotIn("hidden", str(rows))
        self.assertNotIn("/root/.secret", str(rows))

    def test_fail2ban_avoids_banned_ips(self):
        def fake_run(*args, **kwargs):
            if args == ("fail2ban-client", "status"):
                return "Status\n|- Number of jail: 1\n\`- Jail list: sshd\n"
            if args == ("fail2ban-client", "status", "sshd"):
                return (
                    "Currently banned: 2\nTotal banned: 10\n"
                    "Banned IP list: 203.0.113.5 198.51.100.99\n"
                )
            return ""
        with patch.object(inventory, "run", side_effect=fake_run), \
             patch.object(inventory, "names", return_value=[]):
            result = inventory.fail2ban()
        self.assertEqual(result["active_jails"][0]["name"], "sshd")
        self.assertEqual(result["active_jails"][0]["counts"]["Currently banned"], 2)
        self.assertNotIn("203.0.113.5", str(result))
        self.assertNotIn("198.51.100.99", str(result))

    def test_docker_discards_environment_values_and_labels(self):
        data = [{
            "Name": "/example", "Config": {
                "Image": "example:1", "Env": ["PRIVATE_PASSWORD=do-not-log",
                                                  "API_KEY=topsecret", "TZ=UTC"],
                "Labels": {
                    "com.docker.compose.project": "apps",
                    "com.docker.compose.service": "example",
                    "private.secret": "not-for-reporting",
                },
            },
            "State": {"Status": "running"},
            "HostConfig": {"NetworkMode": "bridge", "PortBindings": {}},
            "NetworkSettings": {"Networks": {"default": {}}},
            "Mounts": [{"Type": "bind", "Source": "/docker/example",
                        "Destination": "/config", "RW": True}],
        }]
        def fake_run(*args, **kwargs):
            if args[:3] == ("docker", "ps", "-aq"):
                return "test-id\n"
            return ""
        with patch.object(inventory, "run", side_effect=fake_run), \
             patch.object(inventory, "run_json", return_value=data):
            report = inventory.docker()
        self.assertEqual(len(report["containers"]), 1)
        self.assertEqual(report["containers"][0]["env_variable_NAMES_only"],
                         ["API_KEY", "PRIVATE_PASSWORD", "TZ"])
        self.assertEqual(report["containers"][0]["compose_project"], "apps")
        self.assertNotIn("do-not-log", str(report))
        self.assertNotIn("topsecret", str(report))
        self.assertNotIn("not-for-reporting", str(report))

    def test_cron_does_not_copy_command_or_env(self):
        raw = (
            "MAILTO=secret@example.org\n"
            "45 2 * * * /root/do-sync --password=private\n"
            "@reboot /root/boot-script --token=secret\n"
        )
        with patch.object(inventory, "run", return_value=raw), \
             patch.object(inventory, "names", return_value=[]):
            result = inventory.cron()
        self.assertEqual(len(result["root_crontab_schedules_only"]), 2)
        self.assertNotIn("secret@example.org", str(result))
        self.assertNotIn("--password=private", str(result))
        self.assertNotIn("--token=secret", str(result))

    def test_summary_does_not_publish_private_disk_identifiers(self):
        data = {
            "identity": {"hostname": "openmediavault",
                         "os_release": {"PRETTY_NAME": "Debian"},
                         "boot_mode": "UEFI"},
            "docker": {"containers": [{}], "volume_names": []},
            "host_features": {
                "status": {"fail2ban": {"running": True}},
                "fail2ban": {"active_jails": [{"name": "sshd"}]},
                "shares": {"samba": [], "nfs": []},
                "systemd": {"enabled_units": ["ssh.service"]},
                "cron": {"root_crontab_schedules_only": []},
            },
            "storage": {"snapraid": {"directives": [{"path": "secret/path"}]}},
            "packages": {"infrastructure": [{"name": "ssh"}]},
        }
        output = inventory.summary(data)
        self.assertIn("Fail2ban jails: sshd", output)
        self.assertNotIn("secret/path", output)


if __name__ == "__main__":
    unittest.main()
