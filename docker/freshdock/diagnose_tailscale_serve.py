#!/usr/bin/env python3
"""Read-only, secret-safe diagnostic for nine OMV Tailscale Serve config mismatches.

Prints categories only: never DNS hostnames, proxy URLs, auth settings, JSON,
mount source paths, or secrets. Does not write, update or restart containers.
"""
import io
import json
import socket
import subprocess
import sys
import tarfile

import audit_enrollment as audit

NAMES = (
    "tailscale-audiobookshelf", "tailscale-brave", "tailscale-dockge",
    "tailscale-flame", "tailscale-freshrss", "tailscale-jellyfin",
    "tailscale-jellyseerr", "tailscale-navidrome", "tailscale-ntfy",
)
TOKEN = "${TS_CERT_DOMAIN}"


def run(args, *, binary=False):
    try:
        return subprocess.run(
            args, capture_output=True, text=not binary,
            timeout=25, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def json_cli(name, arguments):
    p = run(["docker", "exec", name, "tailscale", *arguments])
    if p is None or p.returncode or len(p.stdout) > 4 * 1024 * 1024:
        return None
    try:
        return json.loads(p.stdout)
    except ValueError:
        return None


def mounted(name, path):
    if not isinstance(path, str) or not path.startswith("/") or ".." in path.split("/"):
        return None
    p = run(["docker", "cp", f"{name}:{path}", "-"], binary=True)
    if p is None or p.returncode or len(p.stdout) > 4 * 1024 * 1024:
        return None
    try:
        with tarfile.open(fileobj=io.BytesIO(p.stdout), mode="r:*") as archive:
            members = [m for m in archive.getmembers() if m.isfile()]
            if len(members) != 1 or members[0].size > 1024 * 1024:
                return None
            f = archive.extractfile(members[0])
            return json.loads(f.read(1024 * 1024 + 1)) if f else None
    except (OSError, ValueError, tarfile.TarError, UnicodeError):
        return None


def web_key_kind(tree, domain):
    if not isinstance(tree, dict) or not isinstance(tree.get("Web"), dict):
        return "MISSING"
    keys = list(tree["Web"])
    if len(keys) != 1:
        return "MULTIPLE_OR_EMPTY"
    key = keys[0]
    if key == TOKEN + ":443":
        return "TEMPLATE"
    if isinstance(domain, str) and domain and key.lower() == domain.lower() + ":443":
        return "IDENTITY"
    return "OTHER"


def normalize_hosts(tree, domain):
    """Replace only matching domain keys, preserving handlers and policies."""
    if not isinstance(tree, dict):
        return None
    result = {}
    for key, value in tree.items():
        if key in ("Web", "AllowFunnel") and isinstance(value, dict):
            result[key] = {}
            for host, item in value.items():
                if host == TOKEN + ":443":
                    host = "[HOST]:443"
                elif (isinstance(domain, str) and domain and
                      host.lower() == domain.lower() + ":443"):
                    host = "[HOST]:443"
                result[key][host] = item
        else:
            result[key] = value
    return result


def masked_shape(tree):
    if not isinstance(tree, dict):
        return "INVALID"
    if not isinstance(tree.get("Web"), dict):
        return "NO_WEB"
    if not isinstance(tree.get("AllowFunnel"), dict):
        return "NO_FUNNEL"
    return "OK"


def compare_fields(a, b, domain):
    if not isinstance(a, dict) or not isinstance(b, dict):
        return "INVALID"
    a = normalize_hosts(a, domain)
    b = normalize_hosts(b, domain)
    different = [
        k for k in ("TCP", "Web", "AllowFunnel")
        if a.get(k) != b.get(k)
    ]
    if set(a) ^ set(b):
        different.append("OTHER_TOP_LEVEL_KEYS")
    return "MATCH" if not different else ",".join(different)


def main():
    if socket.gethostname() != "openmediavault":
        print("STOP: Unexpected host")
        return 1
    allc = audit.get_all()
    if not all(name in allc for name in NAMES):
        print("STOP: Tailscale service set changed")
        return 1
    print("READ ONLY: nine Tailscale Serve configuration comparisons")
    print("Output classifications only; no DNS values, proxy URLs or credentials.")
    for name in NAMES:
        c = allc[name]
        try:
            (project, directory, files), svc = audit.source_group(c)
            _, resolved = audit.project_config(project, directory, files)
            spec = resolved["services"][svc]
            configs = spec.get("configs") or []
            item = configs[0] if len(configs) == 1 else {}
            key = item.get("source")
            definition = resolved.get("configs", {}).get(key, {})
            target = item.get("target", "")
            source = json.loads(definition["content"])
            runtime = mounted(name, target)
            status = json_cli(name, ["status", "--json"])
            domain = (((status or {}).get("Self") or {}).get("DNSName") or "").rstrip(".")
            active = json_cli(name, ["serve", "status", "--json"])
            mount_types = [m.get("Type") for m in c.get("Mounts", [])
                           if m.get("Destination") == target]
            labels = c["Config"].get("Labels") or {}
            env = dict(x.split("=", 1) for x in c["Config"].get("Env", [])
                       if "=" in x)
            print(f"\n{name}:")
            print("  compose_sources:", len(files),
                  " config_mount_type:", mount_types[0] if len(mount_types) == 1 else "UNREPORTED",
                  " configured_target_matches:", env.get("TS_SERVE_CONFIG") == target)
            print("  parsed_source:", masked_shape(source),
                  " mounted_file:", masked_shape(runtime),
                  " active_serve:", masked_shape(active))
            print("  template_web_key:", web_key_kind(source, domain),
                  " mounted_web_key:", web_key_kind(runtime, domain),
                  " active_web_key:", web_key_kind(active, domain))
            print("  mounted_vs_source:", compare_fields(source, runtime, domain),
                  " active_vs_source:", compare_fields(source, active, domain),
                  " active_vs_mounted:", compare_fields(runtime, active, domain))
            print("  tailscale_identity_available:", bool(domain),
                  " created_by_compose:", bool(labels.get("com.docker.compose.service")))
        except (KeyError, TypeError, ValueError, audit.Stop):
            print(f"\n{name}: SOURCE_OR_RUNTIME_PARSE_ERROR")
    print("\nNO CHANGES: Freshdock and application containers untouched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
