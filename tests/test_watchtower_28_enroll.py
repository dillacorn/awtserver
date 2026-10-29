"""Pure/read-only tests for guarded Watchtower 24-to-28 enrollment."""
import copy
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker/watchtower"))
import enroll_existing_28 as enroll
import watchtower_verify as verify


class EnrollmentTests(unittest.TestCase):
    def test_candidate_preserves_all_other_configuration(self):
        names = sorted(verify.EXPECTED)
        before = {
            "services": {"watchtower": {
                "command": enroll.expected_cmd(names),
                "environment": {"WATCHTOWER_CLEANUP": "false"},
                "volumes": ["/var/run/docker.sock:/var/run/docker.sock"],
            }}
        }
        manifest = {
            "source": "private",
            "schedule": verify.SCHEDULE,
            "container_names": names,
            "custom": {"retained": True},
        }
        original, old_manifest = copy.deepcopy(before), copy.deepcopy(manifest)
        expanded, candidate, new_manifest = enroll.candidates(before, manifest, names)
        self.assertEqual(len(expanded), 28)
        self.assertEqual(set(expanded), verify.EXPANDED)
        self.assertEqual(expanded[:24], names)
        self.assertEqual(expanded[24:], sorted(verify.ADDITIONAL))
        self.assertEqual(new_manifest["container_names"], expanded)
        self.assertEqual(new_manifest["custom"], {"retained": True})
        self.assertEqual(candidate["services"]["watchtower"]["command"],
                         enroll.expected_cmd(expanded))
        del candidate["services"]["watchtower"]["command"]
        original_service = copy.deepcopy(original["services"]["watchtower"])
        del original_service["command"]
        self.assertEqual(candidate["services"]["watchtower"], original_service)
        self.assertEqual(before, original)
        self.assertEqual(manifest, old_manifest)

    def test_not_allowing_second_transmission(self):
        names = sorted(verify.EXPECTED)
        with patch.object(verify, "ADDITIONAL",
                          verify.ADDITIONAL | {"transmission-brother"}):
            with self.assertRaisesRegex(enroll.Stop, "28 names"):
                enroll.candidates({"services": {"watchtower": {}}},
                                  {"container_names": names}, names)

    def test_private_files_reject_unsafe_permissions_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "private.json"
            path.write_text("{}")
            path.chmod(0o644)
            with self.assertRaisesRegex(enroll.Stop, "ownership/mode"):
                enroll.private_file(path)
            path.chmod(0o600)
            self.assertEqual(enroll.private_file(path, expected_uid=os.getuid()), b"{}")
            link = Path(temp) / "linked.json"
            link.symlink_to(path)
            with self.assertRaisesRegex(enroll.Stop, "unavailable"):
                enroll.private_file(link)

    def test_atomic_write_keeps_private_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "compose.yml"
            target.write_bytes(b"old")
            target.chmod(0o600)
            with patch.object(enroll, "ROOT", root):
                enroll.write_atomic(target, b"new")
            self.assertEqual(target.read_bytes(), b"new")
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
