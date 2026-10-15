import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'docker/pihole/tailscale-dns-rescue.sh'


class RescueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bin = self.directory / 'bin'
        self.bin.mkdir()
        for name, script in {
            'docker': '''#!/bin/sh
case "$1" in
  inspect) printf 'true false\\n';;
  port) printf '192.168.68.2:53\\n';;
  *) printf 'UNEXPECTED docker invocation: %s\\n' "$*" >&2; exit 2;;
esac
''',
            'tailscale': '''#!/bin/sh
[ "$1 $2" = 'ip -4' ] || exit 2
printf '100.124.11.69\\n'
''',
            'ip': '''#!/bin/sh
printf '579: tailscale0 inet 100.124.11.69/32 scope global tailscale0\\n'
''',
            'iptables': '''#!/usr/bin/env python3
import os,sys
from pathlib import Path
args=sys.argv[1:]
protocol = args[args.index('-p')+1]
state=Path(os.environ['FAKE_RULE_DIR'])/protocol
if '-C' in args: sys.exit(0 if state.exists() else 1)
if '-I' in args: state.write_text('installed')
elif '-D' in args: state.unlink()
else: sys.exit(2)
'''
        }.items():
            f = self.bin / name
            f.write_text(script)
            f.chmod(0o755)

    def run_script(self, action):
        env = dict(os.environ, PATH=str(self.bin)+':'+os.environ['PATH'], FAKE_RULE_DIR=str(self.directory))
        return subprocess.run(['bash',str(SCRIPT),action],text=True,capture_output=True,env=env,timeout=5)

    def test_check_apply_remove_without_docker_restart(self):
        result=self.run_script('--check')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Absent udp',result.stdout)
        self.assertFalse((self.directory/'udp').exists())
        result=self.run_script('--apply')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue((self.directory/'udp').exists())
        self.assertTrue((self.directory/'tcp').exists())
        result=self.run_script('--check')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Present tcp',result.stdout)
        result=self.run_script('--remove')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((self.directory/'udp').exists())
        self.assertFalse((self.directory/'tcp').exists())

if __name__ == '__main__':
    unittest.main()
