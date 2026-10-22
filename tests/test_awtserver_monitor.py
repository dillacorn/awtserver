"""Unit tests for disk capacity monitoring, mail preview and VM gate."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import awtserver_monitor as m


class MonitorTests(unittest.TestCase):
    def test_threshold_and_missing_mounts(self):
        cfg={"threshold":80,"mounts":["/","/missing"],"recipient":"admin@example.org"}
        report={"filesystems":[{"mount":"/","used_percent":85,"alert":True}],
                "errors":[],"alerts":["/"]}
        with patch.object(m.storage,"usage_report",return_value=report):
            result=m.capacity_alert(cfg,[])
        self.assertEqual(result["over_threshold"],["/"])
        self.assertEqual(result["missing_mounts"],["/missing"])
        self.assertTrue(result["needs_attention"])

    def test_do_not_send_without_vm_guard(self):
        with patch.object(m.awtserver,"apply_guard",side_effect=ValueError("blocked")):
            with self.assertRaisesRegex(ValueError,"blocked"):
                m.send_alert({"recipient":"admin@example.org"},
                             {"needs_attention":True})

    def test_preview_does_not_send(self):
        config={"threshold":80,"mounts":["/"],"recipient":"admin@example.org"}
        report={"threshold":80,"checked":[],"over_threshold":[],
                "missing_mounts":[],"failed_mounts":[],"needs_attention":False}
        with patch.object(m,"read_config",return_value=config), \
             patch.object(m,"capacity_alert",return_value=report), \
             patch.object(m,"send_alert") as send, \
             contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(m.main(["notify"]),0)
            self.assertIn("Preview only",out.getvalue())
            send.assert_not_called()

    def test_config_rejects_untrusted_mode(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"config.json"
            p.write_text('{"threshold":80,"mounts":["/"],"recipient":"admin@example.org"}')
            p.chmod(0o666)
            with self.assertRaises(ValueError):
                m.read_config(p)

    def test_stats_schema(self):
        with patch.object(m.os,"getloadavg",return_value=(1.1,2.2,3.3)), \
             patch.object(m.Path,"read_text",side_effect=[
                 "MemTotal: 1000 kB\nMemAvailable: 500 kB\n",
                 "500.0 123.0\n"
             ]):
            stats=m.system_stats()
        self.assertEqual(stats["memory_used_percent"],50.0)
        self.assertEqual(stats["uptime_seconds"],500)


if __name__ == "__main__":
    unittest.main()
