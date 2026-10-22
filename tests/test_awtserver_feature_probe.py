"""Read-only private OMV feature probe suppression tests."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("feature_probe",
                                            ROOT / "migration/debian/feature_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_sensitive_omv_command_is_counted_not_printed(self):
        raw = '[{"enable":true,"command":"secret-password-example"},' \
              '{"enable":false,"command":"private-ip"}]'
        with patch.object(probe, "run", return_value=raw):
            result=probe.omv_jobs()
        self.assertEqual(result, {"total":2,"enabled":1})
        self.assertNotIn("command",str(result))
        self.assertNotIn("secret-password-example",str(result))

    def test_invalid_json_never_printed(self):
        with patch.object(probe,"run",return_value="password=do-not-echo"):
            self.assertEqual(probe.omv_jobs()["total"],None)

    def test_usb_report_returns_counts_only(self):
        raw='{"blockdevices":[{"type":"disk","tran":"usb","rm":false,' \
            '"name":"PRIVATE","children":[{"mountpoints":[null]}]}]}'
        with patch.object(probe,"run",return_value=raw):
            result=probe.usb_summary()
        self.assertEqual(result, {"usb_disks":1,"usb_unmounted":1})
        self.assertNotIn("PRIVATE",str(result))


if __name__ == "__main__":
    unittest.main()
