"""Read-only tests for qBittorrent rollback's backup integrity gates."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker/watchtower"))
import rollback_qbittorrent_to_transmission as rollback
import watchtower_verify_qbittorrent as verify
import enroll_qbittorrent_29 as enroll


class RollbackBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backup = self.root / "20261030T012345Z"
        self.backup.mkdir(mode=0o700)
        self.old_names = sorted(verify.EXPANDED)
        compose = {"services": {"watchtower": {
            "image": "nickfedor/watchtower:1.23.1",
            "command": enroll.expected_cmd(self.old_names),
        }}}
        manifest = {"container_names": self.old_names,
                    "schedule": verify.SCHEDULE}
        verifier = b"transmission\nUnapproved additional Gluetun namespace user\n"
        for filename, content in (
            ("compose.yml", (json.dumps(compose) + "\n").encode()),
            ("targets.json", (json.dumps(manifest) + "\n").encode()),
            ("watchtower_verify.py", verifier),
        ):
            dest = self.backup / filename
            dest.write_bytes(content)
            dest.chmod(0o600)

    def check(self):
        with patch.object(rollback, "BACKUP_ROOT", self.root):
            return rollback.check_backup(self.backup)

    def test_exact_backup_is_accepted(self):
        docs, names = self.check()
        self.assertEqual(names, self.old_names)
        self.assertEqual(len(docs), 3)

    def test_wrong_timestamp_is_rejected(self):
        renamed = self.root / "not-a-transition"
        self.backup.rename(renamed)
        with patch.object(rollback, "BACKUP_ROOT", self.root):
            with self.assertRaisesRegex(rollback.Stop, "timestamped"):
                rollback.check_backup(renamed)

    def test_backup_missing_target_or_world_readable_fails(self):
        target = self.backup / "targets.json"
        target.chmod(0o644)
        with self.assertRaisesRegex(rollback.Stop, "root-private"):
            self.check()
        target.chmod(0o600)
        manifest = json.loads(target.read_text())
        manifest["container_names"] = ["transmission"]
        target.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(rollback.Stop, "exactly"):
            self.check()

    def test_symlink_is_not_followed(self):
        target = self.backup / "targets.json"
        other = self.root / "external.json"
        other.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(other)
        with self.assertRaisesRegex(rollback.Stop, "absent"):
            self.check()


if __name__ == "__main__":
    unittest.main()
