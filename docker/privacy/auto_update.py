#!/usr/bin/env python3
"""Fail-closed, Compose-coordinated image updates for OMV's Gluetun clients.

No server data, Docker containers, or Compose files are changed without --apply.
Do not run while SnapRAID is active. WUD must exclude the three managed names.
"""
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path('/docker/privacy')
WUD_ROOT = Path('/docker/wud')
SERVICES = ('gluetun', 'transmission', 'mullvad-browser')
CLIENTS = SERVICES[1:]
SNAPRAID_MANAGED = ('audiobookshelf', 'brave', 'calibre', 'immich_server',
                    'jellyfin', 'mullvad-browser', 'transmission')

class Unsafe(RuntimeError):
    pass


def require(ok, message):
    if not ok:
        raise Unsafe(message)


def run(args, *, cwd=None, timeout=120, check=True):
    p = subprocess.run(args, cwd=cwd, env={**os.environ, 'COMPOSE_REMOVE_ORPHANS': '0'},
                       text=True, capture_output=True, timeout=timeout)
    if check and p.returncode:
        # Do not forward raw stderr: Compose can expose substituted secrets.
        raise Unsafe(f"Command failed ({args[0]} {args[1]}), code {p.returncode}")
    return p


def inspect(name):
    p = run(['docker', 'inspect', '--type', 'container', name], timeout=15)
    data = json.loads(p.stdout)
    require(len(data) == 1 and data[0]['Name'] == '/' + name,
            f'Unexpected container identity: {name}')
    return data[0]


def active_snapraid():
    for p in Path('/proc').iterdir():
        if not p.name.isdecimal():
            continue
        try:
            parts = (p / 'cmdline').read_bytes().split(b'\0')
            argv = [x.decode(errors='replace') for x in parts if x]
        except OSError:
            continue
        if (argv and (Path(argv[0]).name == 'snapraid' or
                     any(Path(a).name == 'snapraid-aio-script.sh' for a in argv[1:]))):
            return True
    return False


def compose_command(containers):
    paths = set()
    for name, obj in containers.items():
        labels = obj['Config'].get('Labels') or {}
        require(labels.get('com.docker.compose.project') == 'privacy'
                and labels.get('com.docker.compose.service') == name
                and labels.get('com.docker.compose.project.working_dir') == str(ROOT),
                f'{name}: unexpected Compose identity')
        path_list = labels.get('com.docker.compose.project.config_files', '').split(',')
        require(path_list and all(Path(p).is_file() and Path(p).is_absolute()
                                  and Path(p).parent == ROOT for p in path_list),
                f'{name}: missing or nonstandard Compose source')
        paths.add(tuple(path_list))
    require(len(paths) == 1, 'Compose overlay sets differ between services')
    result = ['docker', 'compose', '--project-directory', str(ROOT), '-p', 'privacy']
    for path in next(iter(paths)):
        result += ['-f', path]
    return result


def normalize_image(ref):
    return ref.removeprefix('docker.io/').removesuffix(':latest')


def compose_config(command, containers):
    config = json.loads(run(command + ['config', '--format', 'json'], cwd=ROOT).stdout)
    for name, obj in containers.items():
        svc = config['services'][name]
        require(svc.get('container_name') == name and
                normalize_image(svc.get('image', '')) == normalize_image(obj['Config']['Image']),
                f'{name}: live configuration differs from container')
        if name in CLIENTS:
            require(svc.get('network_mode') == 'service:gluetun',
                    f'{name}: VPN-only network mode missing')
            mounts = {(v['source'], v['target']) for v in svc.get('volumes', [])
                      if v.get('type') == 'bind'}
            live = {(v['Source'], v['Destination']) for v in obj['Mounts']
                    if v['Type'] == 'bind'}
            require(mounts == live, f'{name}: volume mounts differ')
    return config


def vpn_ready(vpn):
    require(vpn['State']['Status'] == 'running' and
            (vpn['State'].get('Health') or {}).get('Status') == 'healthy',
            'Gluetun is not healthy')
    route = run(['docker', 'exec', 'gluetun', 'ip', '-4', 'route', 'get', '1.1.1.1'],
                timeout=15).stdout
    require(re.search(r'\bdev tun0\b', route) is not None,
            'Gluetun traffic is not routed through tun0')
    public_ip = run(['docker', 'exec', 'gluetun', 'wget', '-qO-', '-T', '10',
                     'https://api.ipify.org'], timeout=20).stdout.strip()
    try:
        addr = ipaddress.ip_address(public_ip)
        require(addr.is_global, 'Gluetun exit IP not public')
    except ValueError as e:
        raise Unsafe('Cannot confirm VPN egress IP') from e


def no_maintenance():
    require(not active_snapraid(), 'SnapRAID maintenance still running')
    for name in SNAPRAID_MANAGED:
        require(inspect(name)['State']['Status'] != 'paused',
                f'{name} paused: do not override SnapRAID or a manual pause')


def wud_excludes():
    obj = inspect('wud')
    require(obj['State']['Status'] == 'running', 'WUD not running')
    env = dict(s.split('=', 1) for s in obj['Config']['Env'] if '=' in s)
    include = env.get('WUD_WATCHER_LOCAL_INCLUDE')
    require(include and env.get('WUD_WATCHER_LOCAL_WATCHBYDEFAULT') == 'false',
            'WUD watcher is not in strict allowlist mode')
    for name in SERVICES:
        require(not re.search(include, name), f'WUD still watches {name}')
        require((inspect(name)['Config'].get('Labels') or {}).get('wud.watch') != 'true',
                f'{name} explicitly opts into WUD')


def no_duplicate_compose_services(containers):
    # Compose can remove a duplicate/orphan with the same project/service label,
    # even without --remove-orphans (as happened to a WUD recovery archive).
    for name, obj in containers.items():
        found = run(['docker', 'ps', '-aq',
                     '--filter', 'label=com.docker.compose.project=privacy',
                     '--filter', f'label=com.docker.compose.service={name}'],
                    timeout=15).stdout.split()
        require(len(found) == 1 and found[0] == obj['Id'][:len(found[0])],
                f'{name}: duplicate Compose service containers need manual review')


def check_containers():
    no_maintenance()
    objects = {name: inspect(name) for name in SERVICES}
    no_duplicate_compose_services(objects)
    vpn = objects['gluetun']
    vpn_ready(vpn)
    for name in CLIENTS:
        c = objects[name]
        require(c['State']['Status'] == 'running', f'{name} not running')
        require(c['HostConfig']['NetworkMode'] == 'container:' + vpn['Id'],
                f'{name} not attached to current Gluetun')
    cmd = compose_command(objects)
    conf = compose_config(cmd, objects)
    return objects, cmd, conf


def image_id(image):
    return run(['docker', 'image', 'inspect', image, '--format', '{{.Id}}'],
               timeout=15).stdout.strip()


def compose_up(cmd, name):
    run(cmd + ['up', '-d', '--no-deps', '--no-build', '--pull', 'never',
               '--force-recreate', name], cwd=ROOT, timeout=180)


def wait_vpn(timeout_seconds=90):
    for _ in range(timeout_seconds // 5):
        try:
            vpn = inspect('gluetun')
            vpn_ready(vpn)
            return vpn
        except (Unsafe, subprocess.TimeoutExpired, ValueError):
            time.sleep(5)
    raise Unsafe('Gluetun VPN health/egress validation timed out')


def emergency_stop():
    # If anything fails after the first write, fail closed even if no rollback
    # is possible. Never unpause or start Transmission directly.
    for name in CLIENTS:
        try:
            c = inspect(name)
            if c['State']['Status'] == 'running':
                run(['docker', 'stop', '--time', '20', name], timeout=45)
        except Exception:
            print(f'ALERT: Could not confirm {name} stopped', file=sys.stderr)


def notify(subject, message):
    # OMV already uses the host mail transport for SnapRAID cron. No credentials
    # are read, copied or logged. A mail delivery failure is not an update pass.
    mail = shutil.which('mail')
    if mail is None:
        print('WARNING: mail unavailable; inspect journal for status', file=sys.stderr)
        return
    try:
        result = subprocess.run([mail, '-s', subject, 'root'], input=message,
                                text=True, capture_output=True, timeout=15)
        if result.returncode:
            print('WARNING: unable to submit update email', file=sys.stderr)
    except (OSError, subprocess.TimeoutExpired):
        print('WARNING: unable to submit update email', file=sys.stderr)


def update(apply):
    require(os.geteuid() == 0, 'Run as root')
    require(run(['hostname'], timeout=5).stdout.strip() == 'openmediavault',
            'Wrong host')
    require(ROOT.is_dir(), 'Missing privacy Compose directory')
    with open('/run/lock/omv-privacy-update.lock', 'a+', encoding='utf-8') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise Unsafe('Another privacy updater is running') from e
        objects, cmd, conf = check_containers()
        wud_excludes()
        print('PASS: SnapRAID inactive; VPN route/egress and namespace checked')
        print('PASS: WUD excludes all three managed containers')
        if not apply:
            print('DRY RUN: No images pulled, no containers changed')
            return
        # Pull first: download failures cause no container interruptions.
        for name in SERVICES:
            print(f'Pulling image for {name}...', flush=True)
            run(['docker', 'pull', conf['services'][name]['image']], timeout=1200)
        changed = {name for name in SERVICES
                   if image_id(conf['services'][name]['image']) != objects[name]['Image']}
        if not changed:
            print('No image changes; no containers recreated')
            return
        print('New image(s): ' + ', '.join(sorted(changed)), flush=True)
        no_maintenance()
        # Revalidate immediately before the first write.
        fresh, fresh_cmd, _ = check_containers()
        require(fresh_cmd == cmd and all(fresh[n]['Id'] == objects[n]['Id']
                                         for n in SERVICES),
                'Container identity changed during pull')
        wrote = False
        try:
            if 'gluetun' in changed:
                wrote = True
                # Stop both clients BEFORE switching Gluetun. This also avoids
                # running on a stale network namespace during recreation.
                run(cmd + ['stop', '--timeout', '45', *CLIENTS], cwd=ROOT, timeout=120)
                compose_up(cmd, 'gluetun')
                wait_vpn()
                changed.update(CLIENTS)  # namespace must always be reattached
            for name in CLIENTS:
                if name in changed:
                    wrote = True
                    vpn_ready(inspect('gluetun'))
                    compose_up(cmd, name)
                    c = inspect(name)
                    vpn = inspect('gluetun')
                    require(c['State']['Status'] == 'running' and
                            c['HostConfig']['NetworkMode'] == 'container:' + vpn['Id'],
                            f'{name}: failed post-update namespace check')
            vpn_ready(inspect('gluetun'))
            print('PASS: Updated services running with current verified VPN')
            notify('OMV privacy update succeeded',
                   'Updated: ' + ', '.join(sorted(changed)) + '\n'
                   'Verified Gluetun tunnel and current client network namespace.')
        except BaseException:
            if wrote:
                emergency_stop()
                print('FAIL CLOSED: VPN clients stopped. Manual review required.',
                      file=sys.stderr)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true',
                        help='pull images and coordinate updates (default: dry run)')
    args = parser.parse_args()
    try:
        update(args.apply)
    except (Unsafe, OSError, ValueError, subprocess.TimeoutExpired) as e:
        print(f'STOP: {e}', file=sys.stderr)
        if args.apply:
            notify('OMV privacy update FAILED',
                   f'Privacy update aborted: {e}\nCheck the systemd journal; VPN clients may be stopped.')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
