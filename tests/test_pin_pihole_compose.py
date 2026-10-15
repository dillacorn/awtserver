import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'docker/pihole/pin-compose-files.py'
spec = importlib.util.spec_from_file_location('pin_pihole', SCRIPT)
pin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pin)


class PinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        for name in ('compose.yml', 'compose.override.yml',
                     'compose.tailscale-dns.yml', 'compose.ipv6-dns.yml'):
            (self.directory / name).write_text('services: {}\n')

    def test_live_label_file_chain(self):
        labels = {
            'com.docker.compose.project.working_dir': str(self.directory),
            'com.docker.compose.project.config_files': ','.join(str(self.directory / n)
                for n in ('compose.yml','compose.tailscale-dns.yml')),
        }
        with patch.object(pin, 'run', return_value=json.dumps(labels)):
            names = pin.active_files('pihole', self.directory)
            self.assertEqual(pin.normalized_files(names, self.directory),
                             ['compose.yml','compose.tailscale-dns.yml'])

    def test_different_directory_rejected(self):
        labels = {'com.docker.compose.project.working_dir': '/docker/other',
                  'com.docker.compose.project.config_files': '/docker/other/compose.yml'}
        with patch.object(pin, 'run', return_value=json.dumps(labels)):
            with self.assertRaises(ValueError):
                pin.active_files('pihole', self.directory)

    def test_escape_rejected(self):
        with self.assertRaises(ValueError):
            pin.normalized_files(['../compose.yml'], self.directory)

    def test_symlink_rejected(self):
        link = self.directory / 'fake.yml'
        link.symlink_to(self.directory / 'compose.yml')
        with self.assertRaises(ValueError):
            pin.normalized_files(['compose.yml', 'fake.yml'], self.directory)

    def test_conflicting_compose_file_protected(self):
        with self.assertRaisesRegex(ValueError, 'refusing'):
            pin.collect_updates(['compose.yml', 'compose.tailscale-dns.yml'],
                                {'COMPOSE_FILE': 'compose.yml'})

    def test_missing_ipv6_values_rejected(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(pin,'run', return_value=''):
            with self.assertRaisesRegex(ValueError, 'LAN_INTERFACE missing'):
                pin.collect_updates(['compose.yml','compose.ipv6-dns.yml'], {})

    def test_tailscale_ip_pinned(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(pin,'run', return_value='100.124.11.69'):
            values = pin.collect_updates(['compose.yml','compose.tailscale-dns.yml'], {})
            self.assertEqual(values['TAILSCALE_IP'], '100.124.11.69')

    def test_tailscale_changed_ip_fails_closed(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(pin,'run', return_value='100.124.11.69'):
            with self.assertRaisesRegex(ValueError, 'differs'):
                pin.collect_updates(['compose.yml','compose.tailscale-dns.yml'],
                                    {'TAILSCALE_IP': '100.65.5.5'})

    def test_apply_preserves_env_and_is_idempotent(self):
        path = self.directory / '.env'
        path.write_text('PASSWORD=keep_this_secret\n')
        updates = {'COMPOSE_FILE': 'compose.yml:compose.override.yml', 'TAILSCALE_IP': '100.64.2.3'}
        pin.apply(self.directory, path.read_text(), updates)
        first = path.read_text()
        self.assertIn('PASSWORD=keep_this_secret', first)
        self.assertIn('COMPOSE_FILE=compose.yml:compose.override.yml', first)
        self.assertIn('TAILSCALE_IP=100.64.2.3', first)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(list(self.directory.glob('.env.before-compose-pin-*'))), 1)
        pin.apply(self.directory, first, updates)
        self.assertEqual(path.read_text(), first)
        self.assertEqual(len(list(self.directory.glob('.env.before-compose-pin-*'))), 1)

    def test_duplicate_managed_var_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            pin.parse_env('COMPOSE_FILE=compose.yml\nCOMPOSE_FILE=compose.yaml\n')

    def test_preview_is_only_compose_config(self):
        commands = []
        def mock_run(*args, env=None):
            commands.append((args,env))
            return ''
        with patch.object(pin,'run',side_effect=mock_run):
            self.assertEqual(pin.preview(self.directory, ['compose.yml'], {}),
                             {'COMPOSE_FILE':'compose.yml'})
        self.assertEqual(commands[0][0][-2:], ('config','--quiet'))
        self.assertNotIn('up', commands[0][0])

if __name__ == '__main__':
    unittest.main()
