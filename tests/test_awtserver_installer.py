"""Command-only installer, updater and uninstaller safety tests."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "awtserver"))
import awtserver_installer as installer


class InstallerTests(unittest.TestCase):
    def test_full_source_files_present(self):
        installer.check_source()
        paths = [str(x) for x in installer.file_list()]
        self.assertIn("awtserver_installer.py", paths)
        self.assertIn("docs/quick/android-auto.md", paths)
        self.assertEqual(len(paths), len(set(paths)))

    def test_nested_archive_installs_flat_files_with_existing_manifest(self):
        # GitHub source paths changed, but /opt/awtserver layout and format 2 did not.
        with tempfile.TemporaryDirectory() as td:
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as archive:
                for relative in installer.file_list():
                    archive.add(
                        installer.source_file(installer.ROOT, relative),
                        arcname=str(Path("awtserver-archive") / installer.repository_file(relative)),
                    )
            with patch.object(installer, "_download", side_effect=[
                json.dumps({"sha": "a" * 40}).encode("utf-8"), buf.getvalue()
            ]):
                source, revision = installer.fetch_main(Path(td))
            self.assertEqual(revision, "a" * 40)
            self.assertTrue((source / "awtserver").is_file())
            self.assertFalse((source / "awtserver").is_dir())
            self.assertEqual(
                installer.manifest_for(installer.ROOT)["files"],
                installer.manifest_for(source)["files"],
            )

    def test_preview_writes_nothing(self):
        with patch.object(installer, "install", side_effect=AssertionError("apply called")):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(installer.main([]), 0)
        self.assertIn("Preview only", output.getvalue())

    def test_apply_is_explicit_and_service_apply_guard_is_not_relaxed(self):
        with patch.object(installer, "install") as apply:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(installer.main(["install", "--apply"]), 0)
            apply.assert_called_once_with()
        with patch.object(installer, "command_install_guard",
                          side_effect=ValueError("root only")):
            with self.assertRaisesRegex(ValueError, "root only"):
                installer.install()

    def test_debian12_omv_command_only_guard(self):
        with patch.object(installer.os, "geteuid", return_value=0), \
             patch.object(installer.awtserver, "parse_os_release",
                          return_value={"ID": "debian", "VERSION_ID": "12"}), \
             patch.object(installer.awtserver, "apply_guard",
                          side_effect=AssertionError("VM write guard invoked")):
            installer.command_install_guard()
        with patch.object(installer.os, "geteuid", return_value=1000):
            with self.assertRaisesRegex(ValueError, "root"):
                installer.command_install_guard()
        with patch.object(installer.os, "geteuid", return_value=0), \
             patch.object(installer.awtserver, "parse_os_release",
                          return_value={"ID": "ubuntu", "VERSION_ID": "24"}):
            with self.assertRaisesRegex(ValueError, "Debian"):
                installer.command_install_guard()

    def test_rejects_existing_command_or_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dest = root / "install"
            cmd = root / "command"
            cmd.symlink_to(root / "missing")
            with self.assertRaisesRegex(ValueError, "Existing"):
                installer.target_is_clear(dest, cmd)
            cmd.unlink()
            dest.mkdir()
            with self.assertRaisesRegex(ValueError, "Existing"):
                installer.target_is_clear(dest, cmd)

    def test_real_install_update_uninstall_code_only(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            dest, command = base / "program", base / "command"
            unrelated = base / "my-data"
            unrelated.write_text("preserve this")
            with patch.object(installer, "command_install_guard"), \
                 patch.object(installer, "checked_parent"), \
                 patch.object(installer, "require_root_owned"):
                installer.install(dest=dest, command=command, revision="old")
                self.assertEqual(command.resolve(), dest / "awtserver")
                self.assertTrue((dest / installer.MARKER).exists())
                self.assertEqual((dest / "awtserver").stat().st_mode & 0o777, 0o755)
                self.assertEqual((dest / "awtserver.py").stat().st_mode & 0o777, 0o644)
                self.assertEqual(installer.checked_install(dest, command)["revision"], "old")
                check = subprocess.run([sys.executable, str(command), "docs", "android-auto"],
                                       capture_output=True, text=True, check=False)
                self.assertEqual(check.returncode, 0, check.stderr)
                self.assertIn("Tailscale Auto Rules", check.stdout)
                # Command execution must not add __pycache__ to managed files.
                self.assertFalse(any(p.name == "__pycache__" for p in dest.rglob("*")))

                with self.assertRaisesRegex(ValueError, "Existing"):
                    installer.install(dest=dest, command=command)

                source = base / "new-source"
                for rel in installer.file_list():
                    output = source / rel
                    output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(installer.source_file(installer.ROOT, rel), output)
                guide = source / "docs/quick/android-auto.md"
                guide.write_text(guide.read_text() + "\nNew test revision.\n")
                self.assertTrue(installer.update(source, dest=dest, command=command,
                                                 revision="new"))
                self.assertEqual(installer.checked_install(dest, command)["revision"], "new")
                self.assertFalse(installer.update(source, dest=dest, command=command,
                                                  revision="new"))
                self.assertIn("New test revision.", guide.read_text())
                self.assertEqual(unrelated.read_text(), "preserve this")

                extra = dest / "user-file.txt"
                extra.write_text("preserve")
                with self.assertRaisesRegex(ValueError, "foreign"):
                    installer.uninstall(dest, command)
                self.assertEqual(extra.read_text(), "preserve")
                extra.unlink()

                code = dest / "awtserver_docs.py"
                code.write_text(code.read_text() + "\n# change\n")
                with self.assertRaisesRegex(ValueError, "changed"):
                    installer.uninstall(dest, command)
                self.assertTrue(command.is_symlink())
                code.write_bytes(source.joinpath("awtserver_docs.py").read_bytes())

                installer.uninstall(dest, command)
                self.assertFalse(os.path.lexists(dest))
                self.assertFalse(os.path.lexists(command))
                self.assertEqual(unrelated.read_text(), "preserve this")


if __name__ == "__main__":
    unittest.main()
