"""Pure verification of the separate Prowlarr Tailscale/Pi-hole templates."""
from pathlib import Path
import os
import stat
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker/privacy"))
import setup_prowlarr_access as p


class AccessTests(unittest.TestCase):
    def test_templates_are_scoped(self):
        sidecar = (ROOT / "docker/privacy/compose.prowlarr-access.yml").read_text()
        mount = (ROOT / "docker/pihole/compose.prowlarr.yml").read_text()
        nginx = (ROOT / "docker/pihole/conf.d/prowlarr.conf").read_text()
        self.assertIn("tailscale-prowlarr", sidecar)
        self.assertIn("http://gluetun:9696", sidecar)
        self.assertIn('AllowFunnel', sidecar)
        self.assertIn("false", sidecar)
        self.assertIn("env_file:", sidecar)
        self.assertIn("prowlarr-certs:ro", mount)
        self.assertEqual(nginx.count("prowlarr.example-tailnet.ts.net"), 3)
        self.assertIn("http://gluetun:9696", nginx)
        self.assertNotIn("server_name amutorrent.", nginx)

    def test_dns_change_is_one_entry_added_after_existing_record(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "compose.yml"
            raw = """services:
  pihole:
    environment:
      FTLCONF_dns_hosts: |-
        192.168.68.10 transmission.time-puffin.ts.net
        192.168.68.10 amutorrent.time-puffin.ts.net
        192.168.68.10 dockge.time-puffin.ts.net
"""
            path.write_text(raw)
            current = {"pihole": {"environment": {
                "FTLCONF_dns_hosts": (
                    "192.168.68.10 transmission.time-puffin.ts.net\n"
                    "192.168.68.10 amutorrent.time-puffin.ts.net\n"
                    "192.168.68.10 dockge.time-puffin.ts.net")}}}
            src, edited, fqdn, ip = p.locate_dns([path], "time-puffin.ts.net", current)
            self.assertEqual(src, path)
            self.assertEqual(fqdn, "prowlarr.time-puffin.ts.net")
            self.assertEqual(ip, "192.168.68.10")
            self.assertIn(
                "192.168.68.10 amutorrent.time-puffin.ts.net\n"
                "        192.168.68.10 prowlarr.time-puffin.ts.net\n"
                "        192.168.68.10 dockge.time-puffin.ts.net",
                edited,
            )
            self.assertEqual(path.read_text(), raw)

    def test_duplicate_existing_dns_record_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "compose.yml"
            path.write_text("    192.168.68.10 amutorrent.time-puffin.ts.net\n")
            current = {"pihole": {"environment": {"FTLCONF_dns_hosts":
                "192.168.68.10 amutorrent.time-puffin.ts.net\n"
                "192.168.68.10 amutorrent.time-puffin.ts.net"}}}
            with self.assertRaisesRegex(p.Stop, "exactly one"):
                p.locate_dns([path], "time-puffin.ts.net", current)

    def test_dnsproxy_quad9_is_matched_by_namespace_and_compose_service(self):
        # Observed host: Docker container name differs from Compose service.
        parent = {"Id": "a" * 64}
        container = {
            "Name": "/dnsproxy-quad9",
            "HostConfig": {"NetworkMode": "container:" + parent["Id"]},
            "State": {"Status": "running"},
            "Config": {"Labels": {
                "com.docker.compose.project": "pihole",
                "com.docker.compose.service": "dnsproxy"
            }},
        }
        files = [Path("/docker/pihole/compose.yml")]
        with patch.object(p, "files_from_container", return_value=files):
            self.assertEqual(
                p.identify_pi_proxy(
                    parent, [container],
                    {"dnsproxy": {"network_mode": "service:pihole"}}, files),
                ("dnsproxy-quad9", "dnsproxy"))

    def test_unknown_pihole_namespace_dependent_rejected(self):
        parent = {"Id": "b" * 64}
        unknown = {
            "Name": "/unexpected",
            "HostConfig": {"NetworkMode": "container:" + parent["Id"]},
            "State": {"Status": "running"},
            "Config": {"Labels": {}},
        }
        with self.assertRaisesRegex(p.Stop, "Unexpected container"):
            p.identify_pi_proxy(parent, [unknown], {}, [])

    def test_missing_proxy_service_rejected(self):
        parent = {"Id": "c" * 64}
        existing = {
            "Name": "/dnsproxy-quad9",
            "HostConfig": {"NetworkMode": "container:" + parent["Id"]},
            "State": {"Status": "running"},
            "Config": {"Labels": {
                "com.docker.compose.project": "pihole",
                "com.docker.compose.service": "dnsproxy"
            }},
        }
        with self.assertRaisesRegex(p.Stop, "absent from active Compose"):
            p.identify_pi_proxy(parent, [existing], {}, [])

    @staticmethod
    def acl_fixture(path):
        # Linux POSIX ACL v2: owner rwx, named user r-x, group r--,
        # mask r-x, other no permissions. The named user forces xattr ACL.
        path.write_bytes(b"original compose\n")
        os.chmod(path, 0o750)
        value = struct.pack("<I", 2) + b"".join(
            struct.pack("<HHI", tag, perms, uid) for tag, perms, uid in (
                (1, 7, 0), (2, 5, 20001), (4, 4, 0),
                (16, 5, 0), (32, 0, 0)))
        os.setxattr(path, "system.posix_acl_access", value)
        return p.file_metadata(path)

    def test_atomic_dns_change_preserves_posix_acl_and_owner(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "compose.override.yml"
            baseline = self.acl_fixture(source)
            self.assertIn("system.posix_acl_access", baseline[3])
            p.atomic(source, b"modified compose\n", original=b"original compose\n")
            self.assertEqual(source.read_bytes(), b"modified compose\n")
            self.assertEqual(p.file_metadata(source), baseline)
            p.atomic(source, b"original compose\n", original=b"modified compose\n")
            self.assertEqual(source.read_bytes(), b"original compose\n")
            self.assertEqual(p.file_metadata(source), baseline)

    def test_acl_copy_error_leaves_original_inode_and_bytes_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "compose.override.yml"
            baseline = self.acl_fixture(source)
            inode = source.stat().st_ino
            with patch.object(p.os, "setxattr",
                              side_effect=OSError("ACL copy denied")):
                with self.assertRaises(OSError):
                    p.atomic(source, b"modified compose\n",
                             original=b"original compose\n")
            self.assertEqual(source.read_bytes(), b"original compose\n")
            self.assertEqual(source.stat().st_ino, inode)
            self.assertEqual(p.file_metadata(source), baseline)

    def test_changed_unrelated_services_blocked(self):
        with self.assertRaisesRegex(p.Stop, "Unrelated service changed"):
            p.compare({"pihole": {}, "dnsproxy": {"image": "old"}},
                      {"pihole": {}, "dnsproxy": {"image": "different"}},
                      "pihole")


if __name__ == "__main__":
    unittest.main()
