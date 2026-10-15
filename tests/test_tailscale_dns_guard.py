import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / 'docker/pihole/dns-guard/omv-pihole-tailscale-dns-guard'
INSTALLER = ROOT / 'docker/pihole/dns-guard/install.sh'


class GuardTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.calls = self.root / 'calls'
        self.calls.write_text('')
        for name, contents in {
            'docker': '''#!/bin/sh
case "$1" in
  inspect) echo 'true false';;
  port) echo '192.168.68.2:53'; if [ -n "${FAKE_NATIVE_DNS:-}" ]; then echo '100.124.11.69:53'; fi;;
  *) exit 5;;
esac
''',
            'tailscale': '''#!/bin/sh
[ "$1 $2" = 'ip -4' ] || exit 5
echo 100.124.11.69
''',
        }.items():
            script = self.bin / name
            script.write_text(contents)
            script.chmod(0o755)
        self.rescue = self.root / 'rescue.sh'
        self.rescue.write_text('''#!/bin/sh
printf '%s\\n' "$1" >> "$FAKE_CALLS"
''')
        self.rescue.chmod(0o755)

    def run_guard(self, native=False):
        env = dict(os.environ, PATH=str(self.bin)+os.pathsep+os.environ['PATH'],
                   OMV_DNS_RESCUE_PATH=str(self.rescue), FAKE_CALLS=str(self.calls))
        if native:
            env['FAKE_NATIVE_DNS'] = 'yes'
        return subprocess.run(['bash', str(GUARD)], capture_output=True,
                              text=True, env=env, timeout=5)

    def test_missing_native_dns_reapplies_rescue(self):
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls.read_text(), '--apply\n')

    def test_native_dns_removes_only_own_rescue(self):
        result = self.run_guard(native=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls.read_text(), '--remove\n')

    def test_installer_preflight_is_read_only(self):
        result = subprocess.run(['bash', str(INSTALLER), '--check'],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('CHECK ONLY', result.stdout)


if __name__ == '__main__':
    unittest.main()
