"""Ensure live-restore config editing preserves existing keys and validates."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "docker/engine-upgrade-recovery/enable-live-restore.py"
spec = importlib.util.spec_from_file_location("live_restore", SCRIPT)
live_restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live_restore)


class LiveRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "daemon.json"
        self.file.write_text('{"log-driver":"json-file","features":{"buildkit":true}}\n')
        self.config = patch.object(live_restore, "CONFIG", self.file)
        self.config.start()
        self.addCleanup(self.config.stop)

    def test_preserves_keys_and_uses_reload_not_restart(self):
        with patch.object(live_restore.subprocess, "run") as run:
            run.return_value.returncode = 0
            live_restore.enable()
        result = json.loads(self.file.read_text())
        self.assertEqual(result["log-driver"], "json-file")
        self.assertEqual(result["features"], {"buildkit": True})
        self.assertTrue(result["live-restore"])
        self.assertTrue(any(call.args[0][:2] == ["systemctl", "reload"] for call in run.call_args_list))
        self.assertFalse(any("restart" in call.args[0] for call in run.call_args_list))
        self.assertEqual(len(list(self.file.parent.glob("daemon.json.before-omv-recovery-*"))), 1)

    def test_validation_failure_leaves_original_untouched(self):
        original = self.file.read_bytes()
        with patch.object(live_restore.subprocess, "run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "invalid config"
            with self.assertRaises(RuntimeError):
                live_restore.enable()
        self.assertEqual(self.file.read_bytes(), original)
        self.assertEqual(len(list(self.file.parent.glob("daemon.json.before-omv-recovery-*"))), 0)

    def test_invalid_json_does_not_modify_config(self):
        self.file.write_text('not-json')
        with self.assertRaises(json.JSONDecodeError):
            live_restore.enable()
        self.assertEqual(self.file.read_text(), 'not-json')


if __name__ == "__main__":
    unittest.main()
