"""Static tests for the single Transmission /Music mount extension."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker/privacy"))
import extend_transmission_music as m


class TransmissionMusicTests(unittest.TestCase):
    def test_overlay_matches_exact_checked_helper(self):
        contents = (ROOT / "docker/privacy/compose.transmission-music.yml").read_text()
        self.assertEqual(contents, m.EXPECTED)
        self.assertIn("/srv/mergerfs/data/root/Music:/Music:rw", contents)
        self.assertNotIn("gluetun:\n", contents)
        self.assertNotIn("amutorrent:\n", contents)

    def test_other_mounts_remain_unchanged(self):
        self.assertEqual(m.EXISTING["/AudioBooks"],
                         "/srv/mergerfs/data/root/AudioBooks")
        self.assertEqual(m.EXISTING["/downloads"],
                         "/srv/mergerfs/data/root/downloads")
        self.assertEqual(m.AM_MEDIA["/Music"], m.NEW_SOURCE)
        self.assertEqual(len(m.AM_MEDIA), 4)
        self.assertEqual(m.BASE[-1], "compose.amutorrent-media.yml")

    def test_missing_volumes_are_rejected(self):
        with self.assertRaisesRegex(m.Stop, "effective Compose volume"):
            m.check_compose_volume([], "/Music", m.NEW_SOURCE)

    def test_wrong_mount_source_is_rejected(self):
        with self.assertRaisesRegex(m.Stop, "effective Compose volume"):
            m.check_compose_volume([{"type": "bind", "target": "/Music",
                                   "source": "/not/music", "read_only": False}],
                                   "/Music", m.NEW_SOURCE)

    def test_read_only_mount_is_rejected(self):
        with self.assertRaisesRegex(m.Stop, "effective Compose volume"):
            m.check_compose_volume([{"type": "bind", "target": "/Music",
                                   "source": m.NEW_SOURCE, "read_only": True}],
                                   "/Music", m.NEW_SOURCE)

    def test_exact_bind_mount_passes(self):
        m.check_compose_volume([{"type": "bind", "target": "/Music",
                                "source": m.NEW_SOURCE, "read_only": False}],
                               "/Music", m.NEW_SOURCE)

    def test_process_and_permission_checks(self):
        expected = {"/Music": m.NEW_SOURCE}
        mounts = [{"Destination": "/Music", "Source": m.NEW_SOURCE,
                   "Type": "bind", "RW": True}]
        container = {"State": {"Status": "running"}, "Mounts": mounts}
        success = SimpleNamespace(returncode=0, stdout="PID COMMAND\n"
                                  "1 /usr/bin/transmission-daemon\n")
        with patch.object(m, "inspect", return_value=container), patch.object(
             m, "run", return_value=success) as command:
            self.assertEqual(m.wait_transmission("1000", "1000", expected),
                             container)
            self.assertTrue(any("--" not in str(call) and "1000:1000" in str(call)
                                for call in command.call_args_list))


if __name__ == "__main__":
    unittest.main()
