"""Offline safety and output checks for Vaultwarden legacy Compose source audit."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker" / "freshdock"))
import vaultwarden_legacy_sources as audit


class VaultwardenSourceTests(unittest.TestCase):
    def test_discovers_root_and_backup_compose_without_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "compose.yml").write_text("services: {}")
            (root / "docker-compose.yml.backup-20261018").write_text("services: {}")
            (root / "backups").mkdir()
            (root / "backups" / "compose.override.yml.old").write_text("services: {}")
            (root / "vw-data").mkdir()
            (root / "vw-data" / "compose.yml").write_text("DO NOT READ ME")
            (root / "secret.env").write_text("PASSWORD=TOP_SECRET")
            with patch.object(audit, "ROOT", root):
                results = audit.candidates()
            self.assertEqual({x.name for x in results},
                             {"compose.yml", "docker-compose.yml.backup-20261018",
                              "compose.override.yml.old"})
            self.assertFalse(any("vw-data" in str(x) for x in results))

    def test_only_compose_services_are_requested_not_config(self):
        paths = [Path("/docker/vaultwarden/compose.yml"),
                 Path("/docker/vaultwarden/compose.override.yml")]
        with patch.object(audit, "ROOT", Path("/docker/vaultwarden")), \
             patch.object(audit, "command",
                          return_value=Mock(stdout="application\nvaultwarden\nnginx\n",
                                            returncode=0)) as command:
            services = audit.names_for(paths)
        self.assertEqual(services, {"application", "vaultwarden", "nginx"})
        self.assertEqual(command.call_args.args[0], [
            "docker", "compose", "-p", "vaultwarden",
            "--project-directory", "/docker/vaultwarden",
            "-f", str(paths[0]), "-f", str(paths[1]), "config", "--services",
        ])

    def test_report_does_not_expose_environment_or_mount_data(self):
        container = {
            "Name": "/vaultwarden",
            "Config": {
                "Env": ["TOKEN=DO_NOT_REVEAL"],
                "Labels": {
                    "com.docker.compose.project": "vaultwarden",
                    "com.docker.compose.service": "vaultwarden",
                    "com.docker.compose.project.config_files":
                    "/docker/vaultwarden/docker-compose.yml",
                },
            },
            "Created": "2026-10-01T10:00:00Z",
            "State": {"Status": "running"},
            "Mounts": [{"Source": "/very/private/DO_NOT_REVEAL"}],
        }
        output = io.StringIO()
        with patch.object(audit.socket, "gethostname", return_value="openmediavault"), \
             patch.object(audit, "live", return_value={"vaultwarden": {
                 "name": "vaultwarden", "state": "running",
                 "created": "2026-10-01T10:00:00",
                 "config_files": "/docker/vaultwarden/docker-compose.yml"
             }}), \
             patch.object(audit, "candidates", return_value=[]), \
             patch.object(audit, "ROOT", Path("/definitely/missing/vaultwarden")), \
             contextlib.redirect_stdout(output):
            audit.main()
        report = output.getvalue()
        self.assertIn("No checked backup defines both missing services", report)
        self.assertNotIn("DO_NOT_REVEAL", report)

    def test_wrong_host_refuses_before_docker(self):
        with patch.object(audit.socket, "gethostname", return_value="other"), \
             patch.object(audit, "live") as inspector:
            with self.assertRaisesRegex(RuntimeError, "Wrong host"):
                audit.main()
            inspector.assert_not_called()


if __name__ == "__main__":
    unittest.main()
