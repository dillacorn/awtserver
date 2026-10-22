"""No-network tests for quick guide registry and command dispatcher."""
import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr
import io

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import awtserver_docs as docs
import awtserver_tui as tui


class GuideTests(unittest.TestCase):
    def test_unique_slugs_and_all_bundled_guides(self):
        slugs = [x[1] for x in docs.entries()]
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertIn("remote-apps", slugs)
        self.assertIn("android-auto", slugs)
        for category, slug, title, _ in docs.entries():
            value = docs.read_topic(slug)
            self.assertTrue(value.startswith("# "))
            self.assertGreater(len(value), 100)
            self.assertLess(len(value.splitlines()), 35)
            self.assertIn(slug, docs.index_text())

    def test_prevent_path_traversal_and_missing_guide(self):
        for slug in ("../../etc/passwd", "remote-apps/../../etc/passwd", "", "random"):
            with self.subTest(slug=slug), self.assertRaises(ValueError):
                docs.read_topic(slug)

    def test_guide_index_categories(self):
        groups = docs.groups()
        self.assertEqual(groups[0][0], "Remote access")
        self.assertEqual(len(groups[0][1]), 3)
        self.assertIn("Android Auto Rules", docs.index_text())

    def test_list_and_open_from_docs_cli(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(docs.main([]), 0)
        self.assertIn("remote-apps", output.getvalue())
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(docs.main(["android-auto"]), 0)
        self.assertIn("Tailscale Auto Rules", output.getvalue())

    def test_short_tui_navigation_and_guide_loading(self):
        root = tui.menu_for("root")
        self.assertEqual([item[0] for item in root],
                         ["Status", "Packages", "Schedules", "Guides", "Quit"])
        self.assertIn(("Remote access", "menu:guide:Remote access"),
                      tui.menu_for("guides"))
        self.assertIn(("Docker application checklist", "doc:remote-apps"),
                      tui.menu_for("guide:Remote access"))
        self.assertIn("Compose", tui.get_details("doc:remote-apps"))
        with self.assertRaises(ValueError):
            tui.menu_for("guide:nonexistent")

    def test_wrapped_tui_guides_do_not_hide_long_instructions(self):
        raw = "# **Tailscale**\n\n1. Configure **MagicDNS** at [Tailscale Settings](https://example.com/very/long/path) then test outside the house."
        lines = tui.detail_lines(raw, 42, markdown=True)
        self.assertTrue(lines)
        self.assertTrue(all(len(line) <= 36 for line in lines))
        self.assertIn("MagicDNS", " ".join(lines))
        self.assertNotIn("https://", " ".join(lines))
        self.assertTrue(any(line.startswith("1.") for line in lines))

    def test_quick_guide_full_reference_urls_survive_install(self):
        for slug in ("remote-apps", "dns", "docker", "storage", "jobs"):
            text = docs.read_topic(slug)
            self.assertNotIn("](../../", text)
            self.assertNotIn("](../", text)
        self.assertIn("github.com/dillacorn/awtserver", docs.read_topic("remote-apps"))

    def test_terminal_command_without_install(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "awtserver"), "docs", "android-auto"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Tailscale Auto Rules", result.stdout)
        result = subprocess.run([sys.executable, str(ROOT / "awtserver"), "doctor"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"services"', result.stdout)


if __name__ == "__main__":
    unittest.main()
