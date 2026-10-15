#!/usr/bin/env python3
"""Pin a live Pi-hole stack's Compose file set in the local .env.

This only edits .env, never runs Compose up, stops a container, or reloads Docker.
"""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

KEY_PATTERN = re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$')
IPV6_KEYS = ('LAN_INTERFACE', 'LAN_IPV6_SUBNET', 'LAN_IPV6_GATEWAY', 'PIHOLE_IPV6')


def run(*args, env=None):
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed ({result.returncode}): {result.stderr.strip()[:250]}')
    return result.stdout.strip()


def parse_env(data):
    values = {}
    for line in data.splitlines():
        match = KEY_PATTERN.match(line)
        if not match or line.lstrip().startswith('#'):
            continue
        name, raw = match.groups()
        if name in values:
            raise ValueError(f'duplicate .env key: {name}')
        # Reject complex values for keys we manage, do not parse unrelated secrets.
        if name in ('COMPOSE_FILE', 'TAILSCALE_IP', *IPV6_KEYS):
            if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
                raw = raw[1:-1]
            if not raw or '\n' in raw or '$' in raw or '#' in raw:
                raise ValueError(f'unsupported .env value for {name}; review manually')
        values[name] = raw
    return values


def active_files(container, directory):
    import json
    labels = json.loads(run('docker', 'inspect', '--format', '{{json .Config.Labels}}', container))
    if not labels or 'com.docker.compose.project.config_files' not in labels:
        raise ValueError(f'{container} has no Compose configuration-file labels')
    working = labels.get('com.docker.compose.project.working_dir', '')
    if Path(working).resolve() != directory:
        raise ValueError(f'{container} belongs to another working directory: {working}')
    return labels['com.docker.compose.project.config_files'].split(',')


def normalized_files(files, directory):
    if not files:
        raise ValueError('no Compose files selected')
    names = []
    for file in files:
        path = Path(file)
        if not path.is_absolute():
            path = directory / path
        if path.is_symlink() or not path.is_file() or path.resolve().parent != directory:
            raise ValueError(f'missing or unsafe Compose file: {file}')
        if path.name in names:
            raise ValueError(f'duplicate Compose file: {path.name}')
        names.append(path.name)
    if names[0] not in ('compose.yml', 'compose.yaml', 'docker-compose.yml', 'docker-compose.yaml'):
        raise ValueError('the first selected file must be a base Compose file')
    return names


def collect_updates(names, existing):
    updates = {'COMPOSE_FILE': ':'.join(names)}
    old = existing.get('COMPOSE_FILE')
    if old and old != updates['COMPOSE_FILE']:
        raise ValueError('existing COMPOSE_FILE differs; refusing to overwrite a managed file set')
    if 'compose.tailscale-dns.yml' in names:
        ip = run('tailscale', 'ip', '-4').splitlines()[0].strip()
        addr = ipaddress.ip_address(ip)
        if addr.version != 4 or addr not in ipaddress.ip_network('100.64.0.0/10'):
            raise ValueError('Tailscale did not return a valid tailnet IPv4 address')
        value = os.environ.get('TAILSCALE_IP') or existing.get('TAILSCALE_IP') or ip
        if value != ip:
            raise ValueError('TAILSCALE_IP differs from current tailnet address; update manually before pinning')
        updates['TAILSCALE_IP'] = ip
    if 'compose.ipv6-dns.yml' in names:
        for key in IPV6_KEYS:
            value = os.environ.get(key) or existing.get(key)
            if not value:
                raise ValueError(f'{key} missing: set the existing IPv6 overlay variable, not a guessed value')
            updates[key] = value
    for key, value in updates.items():
        if '\n' in value or '\r' in value or '#' in value:
            raise ValueError(f'unsafe value in {key}')
    return updates


def preview(directory, files, existing):
    updates = collect_updates(files, existing)
    env = os.environ.copy()
    # Explicit generated variables take priority for Compose validation.
    env.update(updates)
    args = ['docker', 'compose', '--project-directory', str(directory)]
    for file in files:
        args.extend(('-f', str(directory / file)))
    run(*args, 'config', '--quiet', env=env)
    return updates


def apply(directory, existing_text, updates):
    path = directory / '.env'
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('refusing unusual .env file')
    existing = parse_env(existing_text)
    additions = [f'{key}={value}' for key, value in updates.items() if key not in existing]
    if not additions:
        print('Already pinned; no file changes')
        return
    if path.exists():
        backup = directory / ('.env.before-compose-pin-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        if backup.exists():
            raise ValueError(f'backup already exists: {backup}')
        shutil.copy2(path, backup)
        os.chmod(backup, 0o600)
        print(f'Backup: {backup}')
    content = existing_text
    if content and not content.endswith('\n'):
        content += '\n'
    content += '# Pinned Pi-hole Compose deployment: bare docker compose commands preserve overlays\n'
    content += '\n'.join(additions) + '\n'
    fd, name = tempfile.mkstemp(dir=directory, prefix='.env.pin-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        # .env frequently contains credentials; do not carry insecure world-readable modes.
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    print(f'Pinned {updates["COMPOSE_FILE"]} in {path}; no containers touched')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-dir', default='.', type=Path)
    parser.add_argument('--container', default='pihole')
    parser.add_argument('--file', action='append', dest='files', help='Explicit ordered Compose file; repeat to specify complete set')
    parser.add_argument('--apply', action='store_true', help='Write .env after validation; never runs Compose up')
    args = parser.parse_args()
    directory = args.project_dir.resolve()
    if not directory.is_dir():
        parser.error('project directory missing')
    path = directory / '.env'
    if path.is_symlink():
        parser.error('.env cannot be a symlink')
    existing_text = path.read_text(encoding='utf-8') if path.is_file() else ''
    existing = parse_env(existing_text)
    files = normalized_files(args.files if args.files else active_files(args.container, directory), directory)
    updates = preview(directory, files, existing)
    print('Validated Compose files: ' + ', '.join(files))
    print('Existing .env COMPOSE_FILE: ' + (existing.get('COMPOSE_FILE') or '(not set)'))
    if args.apply:
        if os.geteuid() != 0:
            parser.error('--apply requires root')
        apply(directory, existing_text, updates)
    else:
        print('CHECK ONLY: no changes made; --apply pins files without restarting anything')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        sys.exit('ERROR: ' + str(error))
