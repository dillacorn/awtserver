"""Offline checks for the read-only Freshdock cutover audit."""
import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker" / "freshdock"))
import audit_migration as audit


def container(name, *, state="running", labels=None, env=None,
              net="bridge", image="alpine:3.20"):
    return {
        "Name": "/" + name,
        "Id": name + "-id",
        "Config": {"Labels": labels or {}, "Env": env or [], "Image": image},
        "State": {"Status": state},
        "HostConfig": {"NetworkMode": net},
    }


def sample():
    env = [
        "WUD_WATCHER_LOCAL_INCLUDE=^(?:brave|gluetun|transmission)$",
        "WUD_WATCHER_LOCAL_EXCLUDE=^(pihole|wud)$",
        "WUD_WATCHER_LOCAL_WATCHBYDEFAULT=false",
        "WUD_WATCHER_LOCAL_CRON=45 2 * * *",
        "WUD_TRIGGER_DOCKER_UPDATES_AUTO=true",
        "WUD_TRIGGER_SMTP_LEGACY_HOST=private.example",
        "WUD_TRIGGER_SMTP_LEGACY_PORT=587",
        "WUD_TRIGGER_SMTP_LEGACY_USER=secret@example.test",
        "WUD_TRIGGER_SMTP_LEGACY_PASS=PLEASE_NEVER_PRINT_SECRET",
        "WUD_TRIGGER_SMTP_LEGACY_FROM_ADDRESS=secret@example.test",
        "WUD_TRIGGER_SMTP_LEGACY_TO=private@example.test",
    ]
    wud = container("wud", labels={
        "com.docker.compose.project": "wud",
        "com.docker.compose.service": "wud",
        "com.docker.compose.project.working_dir": "/docker/wud",
    }, env=env, image="getwud/wud:9.4.1")
    apps = []
    for name, state in (("brave", "running"), ("gluetun", "running"),
                        ("transmission", "paused"), ("pihole", "running")):
        apps.append(container(name, state=state,
            net=("container:old-parent-id" if name == "transmission" else "bridge"),
            labels={
                "com.docker.compose.project": "privacy" if name in ("gluetun", "transmission") else name,
                "com.docker.compose.service": name,
                "com.docker.compose.project.working_dir": "/docker/privacy",
                "com.docker.compose.project.config_files": "/docker/privacy/compose.yml",
            }))
    return [wud, *apps]


class AuditTests(unittest.TestCase):
    def test_name_allowlist_requires_full_match(self):
        self.assertTrue(audit.matching_name("brave", "^(?:brave|gluetun)$"))
        self.assertFalse(audit.matching_name("brave-test", "^(?:brave|gluetun)$"))

    def test_invalid_pattern_fails_closed(self):
        with self.assertRaisesRegex(audit.Stop, "Invalid WUD watcher"):
            audit.matching_name("brave", "[")

    def test_wud_true_label_detected(self):
        self.assertTrue(audit.bool_label({"wud.watch": "TRUE"}, "wud.watch"))
        self.assertFalse(audit.bool_label({"wud.watch": "false"}, "wud.watch"))

    def test_audit_redacts_smtp_env_values_and_leaves_paused(self):
        out = io.StringIO()
        with patch.object(audit.socket, "gethostname", return_value="openmediavault"), \
             patch.object(audit, "getcontainers", return_value=sample()), \
             patch.object(audit, "run", return_value="29.9.1\n"), \
             contextlib.redirect_stdout(out):
            audit.main()
        report = out.getvalue()
        self.assertIn("SMTP required fields present: 6 / 6", report)
        self.assertIn("WUD effective candidate count: 3", report)
        self.assertIn("transmission | service=transmission | state=paused", report)
        self.assertIn("attached to CURRENT Gluetun: False", report)
        self.assertIn("Audit is READ ONLY", report)
        for secret in ("private.example", "secret@example.test",
                       "PLEASE_NEVER_PRINT_SECRET", "private@example.test"):
            self.assertNotIn(secret, report)

    def test_unexpected_host_never_queries_docker(self):
        with patch.object(audit.socket, "gethostname", return_value="wrong-host"), \
             patch.object(audit, "getcontainers") as getcontainers:
            with self.assertRaisesRegex(audit.Stop, "Wrong host"):
                audit.main()
            getcontainers.assert_not_called()

    def test_wud_missing_fails_closed(self):
        with patch.object(audit.socket, "gethostname", return_value="openmediavault"), \
             patch.object(audit, "getcontainers", return_value=[]):
            with self.assertRaisesRegex(audit.Stop, "WUD container missing"):
                audit.main()


if __name__ == "__main__":
    unittest.main()
