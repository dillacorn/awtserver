"""Offline tests: no Docker daemon, network or live OMV host required."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1] / 'docker' / 'privacy'
sys.path.insert(0, str(ROOT))
import auto_update as au
import activate_auto_update as activate


class PrivacyUpdaterTests(unittest.TestCase):
    def test_image_normalization(self):
        self.assertEqual(au.normalize_image('qmcgaw/gluetun'),
                         au.normalize_image('docker.io/qmcgaw/gluetun:latest'))

    def test_stale_network_refused(self):
        vpn = {'Id': 'new', 'State': {'Status': 'running',
               'Health': {'Status': 'healthy'}}}
        app = {'State': {'Status': 'running'},
               'HostConfig': {'NetworkMode': 'container:old'}}
        with patch.object(au, 'no_maintenance'), \
             patch.object(au, 'inspect', side_effect=lambda n: vpn if n == 'gluetun' else app), \
             patch.object(au, 'vpn_ready'), \
             patch.object(au, 'no_duplicate_compose_services'), \
             patch.object(au, 'compose_command') as compose:
            with self.assertRaisesRegex(au.Unsafe, 'not attached'):
                au.check_containers()
            compose.assert_not_called()

    def test_maintenance_paused_blocks_update(self):
        with patch.object(au, 'active_snapraid', return_value=False), \
             patch.object(au, 'inspect', return_value={'State': {'Status': 'paused'}}):
            with self.assertRaisesRegex(au.Unsafe, 'paused'):
                au.no_maintenance()

    def test_active_scrub_blocks_update(self):
        with patch.object(au, 'active_snapraid', return_value=True), \
             patch.object(au, 'inspect') as inspect:
            with self.assertRaisesRegex(au.Unsafe, 'SnapRAID'):
                au.no_maintenance()
            inspect.assert_not_called()

    def test_wud_allowlist_must_exclude_targets(self):
        wud = {'State': {'Status': 'running'}, 'Config': {'Env': [
            'WUD_WATCHER_LOCAL_WATCHBYDEFAULT=false',
            'WUD_WATCHER_LOCAL_INCLUDE=^(?:gluetun|brave)$']}}
        with patch.object(au, 'inspect', return_value=wud):
            with self.assertRaisesRegex(au.Unsafe, 'still watches gluetun'):
                au.wud_excludes()

    def test_allowlist_update_preserves_other_env_secrets(self):
        old = "WUD_WATCHER_LOCAL_INCLUDE='^(?:brave|gluetun|mullvad-browser|transmission|jellyfin|a|b|c|d|e|f|g|h)$'\nSMTP_SECRET='example'\n"
        edited, new = activate.expected_wud_include(
            old, '^(?:brave|gluetun|mullvad-browser|transmission|jellyfin|a|b|c|d|e|f|g|h)$')
        self.assertNotIn('|gluetun|', edited)
        self.assertNotIn('|mullvad-browser|', edited)
        self.assertNotIn('|transmission|', edited)
        self.assertIn("SMTP_SECRET='example'", edited)
        self.assertIn('jellyfin', new)
        self.assertEqual(activate.expected_wud_include(edited, new), (edited, new))

    def test_reject_arbitrary_wud_allowlist(self):
        with self.assertRaisesRegex(au.Unsafe, 'Unexpected WUD include'):
            activate.expected_wud_include('bad', '^.*$')

    def test_no_image_changes_does_not_modify_services(self):
        objects = {n: {'Image': n + '-old', 'Id': n} for n in au.SERVICES}
        conf = {'services': {n: {'image': n} for n in au.SERVICES}}
        def fake_run(args, **kwargs):
            if args == ['hostname']:
                return Mock(stdout='openmediavault\n')
            return Mock(stdout='', returncode=0)
        with patch.object(au, 'ROOT', Path('/tmp')), \
             patch.object(au.os, 'geteuid', return_value=0), \
             patch.object(au, 'run', side_effect=fake_run), \
             patch.object(au, 'check_containers', return_value=(objects, ['compose'], conf)), \
             patch.object(au, 'wud_excludes'), \
             patch.object(au, 'no_maintenance'), \
             patch.object(au, 'image_id', side_effect=lambda n: n + '-old'), \
             patch.object(au, 'compose_up') as up:
            au.update(True)
            up.assert_not_called()

    def test_gluetun_change_recreates_clients_in_order(self):
        objects = {n: {'Image': n + '-old', 'Id': n} for n in au.SERVICES}
        conf = {'services': {n: {'image': n} for n in au.SERVICES}}
        events = []
        def fake_run(args, **kwargs):
            if args == ['hostname']:
                return Mock(stdout='openmediavault\n')
            if 'stop' in args:
                events.append('stop-clients')
            return Mock(stdout='', returncode=0)
        def fake_up(cmd, name):
            events.append(name)
        def fake_inspect(name):
            return {'State': {'Status': 'running'},
                    'HostConfig': {'NetworkMode': 'container:new'}, 'Id': 'new'}
        with patch.object(au, 'ROOT', Path('/tmp')), \
             patch.object(au.os, 'geteuid', return_value=0), \
             patch.object(au, 'run', side_effect=fake_run), \
             patch.object(au, 'check_containers', return_value=(objects, ['compose'], conf)), \
             patch.object(au, 'wud_excludes'), \
             patch.object(au, 'no_maintenance'), \
             patch.object(au, 'image_id', side_effect=lambda n: n + '-new'), \
             patch.object(au, 'compose_up', side_effect=fake_up), \
             patch.object(au, 'inspect', side_effect=fake_inspect), \
             patch.object(au, 'wait_vpn'), \
             patch.object(au, 'vpn_ready'), \
             patch.object(au, 'notify'):
            au.update(True)
        self.assertEqual(events, ['stop-clients', 'gluetun',
                                  'transmission', 'mullvad-browser'])

    def test_failure_after_first_write_fails_closed(self):
        objects = {n: {'Image': n + '-old', 'Id': n} for n in au.SERVICES}
        conf = {'services': {n: {'image': n} for n in au.SERVICES}}
        def fake_run(args, **kwargs):
            return Mock(stdout='openmediavault\n' if args == ['hostname'] else '')
        with patch.object(au, 'ROOT', Path('/tmp')), \
             patch.object(au.os, 'geteuid', return_value=0), \
             patch.object(au, 'run', side_effect=fake_run), \
             patch.object(au, 'check_containers', return_value=(objects, ['compose'], conf)), \
             patch.object(au, 'wud_excludes'), \
             patch.object(au, 'no_maintenance'), \
             patch.object(au, 'image_id', side_effect=lambda n: n + '-new'), \
             patch.object(au, 'compose_up', side_effect=au.Unsafe('simulated failure')), \
             patch.object(au, 'emergency_stop') as stop:
            with self.assertRaisesRegex(au.Unsafe, 'simulated failure'):
                au.update(True)
            stop.assert_called_once()


if __name__ == '__main__':
    unittest.main()
