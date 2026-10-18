"""Offline checks for read-only missing Compose source discovery."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker" / "freshdock"))
import resolve_missing_compose as discovery


class SourceDiscoveryTests(unittest.TestCase):
    def test_candidate_files_only_lists_compose_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "compose.yml").write_text("services: {}")
            (base / "secret.env").write_text("password=PRIVATE")
            (base / "nested").mkdir()
            (base / "nested" / "docker-compose.yaml").write_text("services: {}")
            found = discovery.candidate_files(base)
            self.assertEqual({x.name for x in found},
                             {"compose.yml", "docker-compose.yaml"})
            self.assertNotIn(base / "secret.env", found)

    def test_missing_project_does_not_throw(self):
        with tempfile.TemporaryDirectory() as base:
            self.assertEqual(discovery.candidate_files(Path(base) / "missing"), [])

    def test_live_report_never_prints_environment_or_mounts(self):
        container = {
            "Name": "/hbbs",
            "Config": {
                "Env": ["PASSWORD=ABSOLUTE_SECRET_VALUE"],
                "Labels": {
                    "com.docker.compose.project": "rustdesk",
                    "com.docker.compose.service": "hbbs",
                    "com.docker.compose.project.config_files":
                    "/docker/rustdesk/docker-compose.yml",
                },
            },
            "Mounts": [{"Source": "/private/ABSOLUTE_SECRET_PATH"}],
        }
        output = io.StringIO()
        with patch.object(discovery, "ROOT", Path("/nonexistent/testroot")), \
             patch.object(discovery, "candidate_files", return_value=[]), \
             contextlib.redirect_stdout(output):
            discovery.report([container])
        report = output.getvalue()
        self.assertIn("hbbs: service=hbbs", report)
        self.assertNotIn("ABSOLUTE_SECRET_VALUE", report)
        self.assertNotIn("ABSOLUTE_SECRET_PATH", report)

    def test_wrong_host_rejects_before_docker(self):
        with patch.object(discovery.socket, "gethostname", return_value="bad-host"), \
             patch.object(discovery, "get_live") as live:
            with self.assertRaisesRegex(RuntimeError, "Wrong host"):
                discovery.main()
            live.assert_not_called()

    def test_compose_services_unverified_on_parse_error(self):
        with patch.object(discovery, "query", return_value=None):
            self.assertIsNone(discovery.services_from_file(
                Path("/docker/rustdesk/compose.yml"),
                Path("/docker/rustdesk"), "rustdesk"))


if __name__ == "__main__":
    unittest.main()
