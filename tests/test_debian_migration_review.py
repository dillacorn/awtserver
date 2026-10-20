"""Offline tests for the private Debian transition inventory review printer."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "migration" / "debian"))
import review


def fixture():
    return {
        "schema": 1,
        "collected_at_utc": "2026-10-20T13:52:04+00:00",
        "identity": {
            "hostname": "openmediavault",
            "os_release": {"PRETTY_NAME": "Debian GNU/Linux 12"},
            "boot_mode": "UEFI",
        },
        "storage": {
            "block_devices": {"blockdevices": [
                {"name": "sda", "type": "disk", "size": 1000,
                 "fstype": None, "mountpoints": [],
                 "children": [{"name": "sda1", "type": "part", "size": 500,
                               "fstype": "ext4", "mountpoints": ["/srv/storage"]}]}
            ]},
            "fstab_safe_fields_only": [
                {"source": "//server/secret", "target": "/mnt/secret",
                 "fstype": "cifs", "other_options_redacted": 3},
                {"source": "UUID=aa", "target": "/srv/storage",
                 "fstype": "ext4", "other_options_redacted": 0},
            ],
            "mounts": {"filesystems": [{"target": "/", "fstype": "ext4",
                "children": [{"target": "/srv/merge", "fstype": "fuse.mergerfs",
                              "source": "/srv/secret-branch"}]}]},
            "snapraid": {
                "directives": [{"directive": "parity", "values": ["/srv/parity/parity"]},
                               {"directive": "exclude", "values": ["secret*.env"]}],
                "status_summary": ["No sync is in progress"],
            },
        },
        "host_features": {
            "status": {"fail2ban": {"enabled": True, "running": True}},
            "systemd": {"enabled_units": ["fail2ban.service", "ssh.service"],
                        "timers": ["watchtower-fork-verify.timer"],
                        "local_unit_file_names": ["watchtower-fork-verify.timer"]},
            "fail2ban": {
                "active_jails": [{"name": "ssh", "counts": {"Currently banned": 2}}],
                "jail_directory_names_only": ["ssh.local"],
                "filter_directory_names_only": ["sshd.conf"],
                "jail_local_exists": True,
            },
            "sshd": {"effective_allowlisted_settings": {"permitrootlogin": ["prohibit-password"]}},
            "shares": {"samba": [{"name": "media", "path": "/srv/media"}], "nfs": []},
            "ups": {"apcaccess_status_and_charge_only": ["STATUS : ONLINE"],
                    "nut_ups_names": []},
            "mail": {"installed_mail_executables": ["mailx"],
                     "postfix_filenames": []},
        },
        "network": {
            "addresses": [{"ifname": "eth0", "addr_info": [
                {"local": "203.0.113.10", "family": "inet"}]}],
            "tailscale": {"state": "Running", "peer_count": 5,
                          "ips": ["100.64.15.16"]},
            "firewall": {"nft_tables_only": ["table inet filter"],
                         "iptables_rules_count": 10, "ufw_status_header": []},
        },
        "accounts": {"root_and_regular_users": [{"name": "root", "uid": 0, "gid": 0,
                                                  "home": "/root"}]},
        "packages": {"infrastructure": [{"package": "fail2ban", "version": "1.0"}],
                     "manual_packages": ["fail2ban"]},
        "docker": {"containers": [{"name": "pihole", "state": "running",
                                  "compose_project": "pihole",
                                  "compose_service": "pihole",
                                  "compose_working_dir": "/docker/pihole",
                                  "compose_config_files": "/docker/pihole/compose.yml",
                                  "private_secret": "neverprint"},
                                 {"name": "legacy", "state": "exited",
                                  "compose_project": None,
                                  "compose_service": None,
                                  "compose_working_dir": None,
                                  "compose_config_files": None}],
                   "volume_names": ["pihole-data"],
                   "docker_version": "28.0", "compose_version": "2.37"},
    }


class ReviewTests(unittest.TestCase):
    def test_focus_and_privacy(self):
        result = review.emit_review(fixture())
        self.assertIn("Fail2ban jail.d filenames: ssh.local", result)
        self.assertIn("Jail ssh", result)
        self.assertIn("watchtower-fork-verify.timer", result)
        self.assertIn("pihole | running | pihole/pihole", result)
        self.assertIn("Missing Compose provenance: legacy", result)
        self.assertIn("Samba shares", result)
        self.assertIn("  /srv/merge (sources recorded privately)", result)
        self.assertIn("No sync is in progress", result)
        for secret in ("203.0.113.10", "100.64.15.16",
                       "/srv/secret-branch", "secret*.env", "neverprint",
                       "//server/secret"):
            self.assertNotIn(secret, result)

    def test_unknown_schema_and_host_rejected(self):
        data = fixture()
        data["identity"]["hostname"] = "different-host"
        with self.assertRaisesRegex(ValueError, "schema or host"):
            review.emit_review(data)
        data = fixture()
        data["schema"] = 999
        with self.assertRaisesRegex(ValueError, "schema or host"):
            review.emit_review(data)

    def test_inventory_path_validation(self):
        for path in (Path("/tmp/inventory.json"),
                     Path("/root/public/inventory.json"),
                     Path("relative/inventory.json")):
            with self.assertRaises((ValueError, OSError)):
                review.checked_path(path)


if __name__ == "__main__":
    unittest.main()
