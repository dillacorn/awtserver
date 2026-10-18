"""Safety tests for comprehensive non-mutating Freshdock enrollment audit."""
import io
import sys
import unittest
import contextlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker" / "freshdock"))
import audit_enrollment as audit


class AuditTests(unittest.TestCase):
    def test_selection_is_always_named_opt_in(self):
        source = (Path(audit.__file__)).read_text()
        self.assertNotIn("docker stop", source)
        self.assertNotIn("docker rm", source)
        self.assertEqual(len(audit.SKIP), 5)

    def test_runtime_comparison_never_prints_secrets(self):
        client = {
            "Config": {
                "Image": "example:latest",
                "Env": ["PASSWORD=SECRET_NEVER_PRINT"],
            },
            "HostConfig": {
                "NetworkMode": "bridge",
                "RestartPolicy": {"Name": "unless-stopped"},
            },
            "Mounts": [
                {"Type": "bind", "Source": "/private/data",
                 "Destination": "/data"},
            ],
        }
        spec = {
            "image": "example:latest",
            "restart": "unless-stopped",
            "environment": {"PASSWORD": "DIFFERENT_SECRET_NEVER_PRINT"},
            "volumes": [
                {"type": "bind", "source": "/private/data", "target": "/data"},
            ],
        }
        problems = audit.safe_diffs(client, spec, {}, "test")
        report = " ".join(problems)
        self.assertIn("configured environment values differ", report)
        self.assertNotIn("SECRET_NEVER_PRINT", report)
        self.assertNotIn("DIFFERENT_SECRET_NEVER_PRINT", report)
        spec["environment"]["PASSWORD"] = "SECRET_NEVER_PRINT"
        self.assertEqual(audit.safe_diffs(client, spec, {}, "test"), [])

    def test_named_volumes_do_not_raise_false_bind_source_mismatch(self):
        client = {
            "Config": {"Image": "demo:latest", "Env": []},
            "HostConfig": {"NetworkMode": "bridge",
                           "RestartPolicy": {"Name": "unless-stopped"}},
            "Mounts": [{
                "Type": "volume", "Name": "project_data",
                "Source": "/var/lib/docker/volumes/project_data/_data",
                "Destination": "/data",
            }],
        }
        spec = {
            "image": "demo:latest", "restart": "unless-stopped",
            "volumes": [{"type": "volume", "source": "data", "target": "/data"}],
        }
        self.assertEqual(audit.safe_diffs(client, spec, {}, "project"), [])

    def test_source_owner_missing_reports_failure(self):
        with self.assertRaisesRegex(audit.Stop, "Missing Compose ownership"):
            audit.source_group({"Config": {"Labels": {}}})

    def test_wrong_host_prevents_docker_read(self):
        with patch.object(audit.socket, "gethostname", return_value="bad"), \
             patch.object(audit, "get_all") as docker_read:
            with self.assertRaisesRegex(audit.Stop, "Wrong host"):
                audit.main()
            docker_read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
