"""Pure checks for the aMuTorrent four-directory extension. No Docker needed."""
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker/privacy"))
import extend_amutorrent_media as ext


class MediaExtensionTests(unittest.TestCase):
    def test_exact_new_overlay_matches_script(self):
        overlay = ROOT / "docker/privacy/compose.amutorrent-media.yml"
        self.assertEqual(overlay.read_text(), ext.NEW)
        self.assertEqual(len(ext.ALL_MOUNTS), 4)
        self.assertEqual(ext.ALL_MOUNTS["/AudioBooks"],
                         "/srv/mergerfs/data/root/AudioBooks")
        self.assertEqual(ext.ALL_MOUNTS["/Music"],
                         "/srv/mergerfs/data/root/Music")
        self.assertEqual(ext.ALL_MOUNTS["/Movies"],
                         "/srv/mergerfs/data/root/Movies")
        self.assertEqual(ext.ALL_MOUNTS["/Shows"],
                         "/srv/mergerfs/data/root/Shows")

    def test_previous_live_overlay_is_the_verified_old_version(self):
        data = ext.OLD.encode()
        blob = b"blob " + str(len(data)).encode() + b"\0" + data
        self.assertEqual(hashlib.sha1(blob).hexdigest(),
                         "85c5bcd301c37317c7c75ac836f2fdf04bf93a52")

    def test_all_mounts_are_writable_bind_mounts(self):
        volumes = [{"target": dest, "source": source, "type": "bind",
                    "read_only": False}
                   for dest, source in ext.ALL_MOUNTS.items()]
        ext.validate_volumes(volumes, ext.ALL_MOUNTS)

    def test_duplicate_target_is_rejected(self):
        volumes = [{"target": "/Movies", "source": ext.ALL_MOUNTS["/Movies"],
                    "type": "bind", "read_only": False}] * 2
        with self.assertRaisesRegex(ext.Stop, "Duplicate volume targets"):
            ext.validate_volumes(volumes, ext.OLD_MOUNTS)

    def test_changed_source_is_rejected(self):
        volumes = [{"target": "/Music", "source": "/tmp/not-music",
                    "type": "bind", "read_only": False}]
        with self.assertRaisesRegex(ext.Stop, "Unexpected Compose mount"):
            ext.validate_volumes(volumes, ext.EXTRA_MOUNTS)

    def test_read_only_mount_is_rejected(self):
        volumes = [{"target": "/Music",
                    "source": ext.EXTRA_MOUNTS["/Music"],
                    "type": "bind", "read_only": True}]
        with self.assertRaisesRegex(ext.Stop, "Unexpected Compose mount"):
            ext.validate_volumes(volumes, {"/Music": ext.EXTRA_MOUNTS["/Music"]})


if __name__ == "__main__":
    unittest.main()
