#!/usr/bin/env python3
"""Guarded one-time WUD handoff and systemd timer setup; dry run by default."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import re
import sys
import time

import auto_update as au

WUD_ENV = Path('/docker/wud/.env')
UNIT = Path('/etc/systemd/system/omv-privacy-auto-update.service')
TIMER = Path('/etc/systemd/system/omv-privacy-auto-update.timer')
SERVICE_TEXT = '''[Unit]
Description=Update OMV privacy VPN stack with network-namespace verification
Wants=network-online.target
After=network-online.target docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /docker/privacy/auto_update.py --apply
TimeoutStartSec=65min
'''
TIMER_TEXT = '''[Unit]
Description=Nightly coordinated OMV privacy stack updates

[Timer]
OnCalendar=*-*-* 01:30:00
RandomizedDelaySec=5min
Persistent=false
Unit=omv-privacy-auto-update.service

[Install]
WantedBy=timers.target
'''


def expected_wud_include(text, observed):
    match = re.fullmatch(r'\^\(\?:([A-Za-z0-9_|-]+)\)\$', observed)
    au.require(match is not None, 'Unexpected WUD include regex; refusing to edit')
    names = match.group(1).split('|')
    au.require(len(names) >= 10 and len(set(names)) == len(names),
               'Unexpected WUD allowlist')
    removed = set(au.SERVICES)
    remaining = [n for n in names if n not in removed]
    au.require(len(remaining) >= 10, 'WUD allowlist too short')
    new = '^(?:' + '|'.join(remaining) + ')$'
    old_line = "WUD_WATCHER_LOCAL_INCLUDE='" + observed + "'"
    new_line = "WUD_WATCHER_LOCAL_INCLUDE='" + new + "'"
    lines = text.splitlines(keepends=True)
    au.require(sum(line.rstrip('\r\n') == old_line for line in lines) == 1,
               'Private WUD .env and effective allowlist disagree')
    return ''.join(new_line + '\n' if line.rstrip('\r\n') == old_line
                   else line for line in lines), new


def validate_preflight():
    au.require(os.geteuid() == 0, 'Run as root')
    au.require(au.run(['hostname'], timeout=5).stdout.strip() == 'openmediavault',
               'Unexpected host')
    au.check_containers()  # no paused containers, VPN healthy, current namespaces
    wud = au.inspect('wud')
    labels = wud['Config'].get('Labels') or {}
    au.require(wud['State']['Status'] == 'running'
               and (wud['State'].get('Health') or {}).get('Status') == 'healthy',
               'WUD is not healthy')
    au.require(labels.get('com.docker.compose.project') == 'wud'
               and labels.get('com.docker.compose.service') == 'wud'
               and labels.get('com.docker.compose.project.working_dir') == '/docker/wud',
               'Unexpected WUD Compose identity')
    au.require(labels.get('com.docker.compose.project.config_files') == '/docker/wud/compose.yml',
               'Unexpected WUD Compose source')
    au.require(WUD_ENV.is_file() and not WUD_ENV.is_symlink()
               and WUD_ENV.stat().st_uid == 0
               and WUD_ENV.stat().st_mode & 0o777 == 0o600,
               'Private WUD .env must be a root-owned regular 0600 file')
    for name in au.SERVICES:
        au.require((au.inspect(name)['Config'].get('Labels') or {}).get('wud.watch') != 'true',
                   f'{name} overrides WUD exclusion via label')
    au.require(au.Path('/docker/privacy/auto_update.py').is_file(),
               'Updater script is not installed in /docker/privacy')
    for path, content in ((UNIT, SERVICE_TEXT), (TIMER, TIMER_TEXT)):
        au.require(not path.is_symlink() and
                   (not path.exists() or path.read_text() == content),
                   f'Existing systemd unit differs: {path}')
    env = dict(s.split('=', 1) for s in wud['Config']['Env'] if '=' in s)
    au.require(env.get('WUD_WATCHER_LOCAL_WATCHBYDEFAULT') == 'false'
               and env.get('WUD_WATCHER_LOCAL_WATCHATSTART') == 'false'
               and env.get('WUD_WATCHER_LOCAL_WATCHEVENTS') == 'false',
               'Unexpected WUD watcher mode')
    previous = env.get('WUD_WATCHER_LOCAL_INCLUDE', '')
    edited, new = expected_wud_include(WUD_ENV.read_text(), previous)
    au.require(au.Path('/docker/wud/compose.yml').is_file(),
               'WUD Compose missing')
    current_time = datetime.now().strftime('%H%M')
    au.require(not ('0230' <= current_time <= '0320'),
               'Too close to WUD scheduled update / Docker engine maintenance')
    return edited, new, previous


def atomic_write(path, content):
    tmp = path.with_name(path.name + '.privacy-update-tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def recreate_wud(expect):
    cmd = ['docker', 'compose', '--project-directory', '/docker/wud',
           '-p', 'wud', '-f', '/docker/wud/compose.yml']
    au.run(cmd + ['config', '--quiet'], cwd=au.WUD_ROOT)
    au.run(cmd + ['up', '-d', '--no-deps', '--no-build', '--pull', 'never',
                  '--force-recreate', 'wud'], cwd=au.WUD_ROOT, timeout=180)
    for _ in range(18):
        wud = au.inspect('wud')
        env = dict(s.split('=', 1) for s in wud['Config']['Env'] if '=' in s)
        if (wud['State']['Status'] == 'running'
            and (wud['State'].get('Health') or {}).get('Status') == 'healthy'
            and env.get('WUD_WATCHER_LOCAL_INCLUDE') == expect):
            return
        time.sleep(5)
    raise au.Unsafe('WUD did not restart healthy with expected allowlist')


def activate(apply):
    edited, new, previous = validate_preflight()
    print('PASS: WUD, VPN, Compose, and SnapRAID preflight')
    print('WUD managed privacy containers will be excluded; other names unchanged')
    if not apply:
        print('DRY RUN: no configuration, containers or timer changed')
        return
    # Idempotence: rerunning is safe if the handoff already happened.
    text = WUD_ENV.read_text()
    if edited != text:
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        backup = WUD_ENV.with_name('.env.before-privacy-' + stamp)
        with open(backup, 'x') as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(text)
        print('WUD allowlist backed up privately (path not logged)')
        try:
            atomic_write(WUD_ENV, edited)
            recreate_wud(new)
        except Exception:
            atomic_write(WUD_ENV, text)
            try:
                recreate_wud(previous)
            except Exception:
                print('CRITICAL: WUD rollback also failed; inspect locally!', file=sys.stderr)
            raise
    au.wud_excludes()
    for path, content in ((UNIT, SERVICE_TEXT), (TIMER, TIMER_TEXT)):
        if not path.exists():
            path.write_text(content)
            path.chmod(0o644)
    au.run(['systemctl', 'daemon-reload'], timeout=30)
    au.run(['systemctl', 'enable', '--now', TIMER.name], timeout=30)
    au.require(au.run(['systemctl', 'is-active', TIMER.name], check=False).returncode == 0,
               'Privacy updater timer is not active')
    print('PASS: WUD exclusion effective; privacy timer enabled for 01:30')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        activate(args.apply)
    except (au.Unsafe, OSError, ValueError, TimeoutError) as e:
        print(f'STOP: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
