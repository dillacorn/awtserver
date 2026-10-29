"""Unit checks for read-only TRAWL migration preflight size parsing."""
import importlib.util
from pathlib import Path
import unittest

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


if __name__ == "__main__":
    unittest.main()
