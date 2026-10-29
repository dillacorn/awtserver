"""Unit checks for read-only TRAWL migration preflight size parsing."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "docker/privacy/migrate_trawl.py"
spec = importlib.util.spec_from_file_location("migrate_trawl", MODULE)
trawl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trawl)


class TrawlMigrationPreflightTests(unittest.TestCase):
    def test_docker_compose_shm_size_encodings(self):
        for value in (1073741824, "1073741824", "1g", "1gb",
                      "1024m", "1024mb", "1048576k", "1048576kb"):
            with self.subTest(value=value):
                self.assertEqual(trawl.normalize_shm_bytes(value), 1024 ** 3)

    def test_reject_unsupported_or_invalid_size(self):
        for value in (None, True, False, -1, -1073741824, "1.0gb",
                      "onegb", "1TB", "1gb-extra", "1 gb", {}, [], "0gb"):
            with self.subTest(value=value):
                self.assertNotEqual(trawl.normalize_shm_bytes(value), 1024 ** 3)

    def test_genuinely_different_sizes_do_not_match(self):
        for value in (0, 1024 ** 2, "512mb", "2gb", "1mb", "1024kb"):
            with self.subTest(value=value):
                self.assertNotEqual(trawl.normalize_shm_bytes(value), 1024 ** 3)


    @patch.object(trawl, "time")
    @patch.object(trawl, "health", side_effect=[False, False, True])
    @patch.object(trawl, "inspect",
                  return_value={"Id": "original-id", "State": {"Status": "running"}})
    def test_health_wait_allows_slow_start(self, inspect, health, time):
        time.monotonic.side_effect = [0.0, 1.0, 2.0]
        self.assertTrue(trawl.wait_health("original-id", timeout=60))
        self.assertEqual(health.call_count, 3)
        self.assertEqual(time.sleep.call_count, 2)

    @patch.object(trawl, "time")
    @patch.object(trawl, "health", return_value=False)
    @patch.object(trawl, "inspect",
                  return_value={"Id": "original-id", "State": {"Status": "running"}})
    def test_health_wait_expires_without_unbounded_retry(self, inspect, health, time):
        time.monotonic.side_effect = [0.0, 11.0]
        self.assertFalse(trawl.wait_health("original-id", timeout=10))
        time.sleep.assert_not_called()

    @patch.object(trawl, "health", return_value=True)
    @patch.object(trawl, "inspect",
                  return_value={"Id": "unexpected", "State": {"Status": "running"}})
    def test_health_wait_fails_if_target_container_changed(self, inspect, health):
        with self.assertRaisesRegex(trawl.Stop, "changed during health"):
            trawl.wait_health("original-id")
        health.assert_not_called()

    @patch.object(trawl, "health", return_value=True)
    @patch.object(trawl, "inspect",
                  return_value={"Id": "original-id", "State": {"Status": "exited"}})
    def test_health_wait_fails_if_container_stopped(self, inspect, health):
        with self.assertRaisesRegex(trawl.Stop, "stopped during health"):
            trawl.wait_health("original-id")
        health.assert_not_called()


if __name__ == "__main__":
    unittest.main()
