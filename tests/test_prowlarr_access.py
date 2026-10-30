"""Pure verification of the separate Prowlarr Tailscale/Pi-hole templates."""
from pathlib import Path
import sys
import tempfile
import unittest

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

    def test_changed_unrelated_services_blocked(self):
        with self.assertRaisesRegex(p.Stop, "Unrelated service changed"):
            p.compare({"pihole": {}, "dnsproxy": {"image": "old"}},
                      {"pihole": {}, "dnsproxy": {"image": "different"}},
                      "pihole")


if __name__ == "__main__":
    unittest.main()
