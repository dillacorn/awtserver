"""Unit tests for the first-install-only awtserver VM command installer."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import awtserver_installer as installer


class InstallerTests(unittest.TestCase):
    def test_full_source_files_present(self):
        installer.check_source()
        files = [str(x) for x in installer.file_list()]
        self.assertIn("awtserver_installer.py", files)
        self.assertIn("docs/quick/android-auto.md", files)
        self.assertEqual(len(files), len(set(files)))

    def test_preview_writes_nothing(self):
        with patch.object(installer, "install", side_effect=AssertionError("apply called")):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(installer.main([]), 0)
        self.assertIn("Preview only", output.getvalue())

    def test_apply_requires_confirm(self):
        with patch.object(installer, "install", side_effect=AssertionError("unexpected")):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(installer.main(["--apply"]), 1)

    def test_direct_install_rechecks_vm_gate(self):
        with patch.object(installer.awtserver, "apply_guard",
                          side_effect=ValueError("VM only")):
            with self.assertRaisesRegex(ValueError, "VM only"):
                installer.install()

    def test_rejects_existing_command_or_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dest = root / "install"
            command = root / "command"
            command.symlink_to(root / "missing")
            with self.assertRaisesRegex(ValueError, "Existing"):
                installer.target_is_clear(dest, command)
            command.unlink()
            dest.mkdir()
            with self.assertRaisesRegex(ValueError, "Existing"):
                installer.target_is_clear(dest, command)

    def test_vm_install_copies_whitelisted_files_and_is_not_overwritable(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            dest = base / "awtserver"
            command = base / "command"
            # The real VM/root gate is independently tested. This isolated
            # test uses temporary paths and stubs only destination uid checks.
            def clear(d, c):
                if os.path.lexists(d) or os.path.lexists(c):
                    raise ValueError("Existing installation or command found")
            with patch.object(installer.awtserver, "apply_guard") as gated, \
                 patch.object(installer, "target_is_clear", side_effect=clear):
                installer.install(dest=dest, command=command)
                gated.assert_called_once_with(True)
                self.assertTrue(command.is_symlink())
                self.assertEqual(command.resolve(), dest / "awtserver")
                self.assertEqual((dest / "docs/quick/android-auto.md").is_file(), True)
                self.assertEqual((dest / "awtserver").stat().st_mode & 0o777, 0o755)
                self.assertEqual((dest / "awtserver.py").stat().st_mode & 0o777, 0o644)
                self.assertEqual((dest / installer.MARKER).is_file(), True)
                with self.assertRaisesRegex(ValueError, "Existing"):
                    installer.install(dest=dest, command=command)
                self.assertTrue((dest / installer.MARKER).exists())


if __name__ == "__main__":
    unittest.main()
