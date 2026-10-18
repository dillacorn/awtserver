#!/usr/bin/env python3
"""Read-only resolution of stale Compose source paths on the OMV server.

No Compose contents, Docker environment values, credentials, bind mounts, or
Docker writes are printed or performed. Only checks RustDesk/Vaultwarden.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

TARGETS = {
    "rustdesk": {"hbbs", "hbbr"},
    "vaultwarden": {"nginx", "vaultwarden"},
}
CANDIDATE_NAMES = {
    "compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml",
}
ROOT = Path("/docker")


def query(args, timeout=20):
    try:
        return subprocess.run(args, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True,
                              timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def get_live():
    p = query(["docker", "ps", "-aq"])
    if p is None or p.returncode:
        raise RuntimeError("Cannot inventory Docker containers")
    ids = p.stdout.split()
    if not ids:
        return []
    p = query(["docker", "inspect", *ids], timeout=45)
    if p is None or p.returncode:
        raise RuntimeError("Cannot inspect actual Docker container labels")
    return json.loads(p.stdout)


def candidate_files(base):
    if not base.is_dir():
        return []
    found = []
    for current, dirs, files in os.walk(base, followlinks=False):
        depth = len(Path(current).relative_to(base).parts)
        if depth >= 3:
            dirs[:] = []
        dirs[:] = [d for d in dirs if not d.startswith(".") and
                   d not in ("node_modules", "data", "cache", "logs",
                             "backups", "backup", "volumes", "store")]
        for file in files:
            if file.lower() in CANDIDATE_NAMES:
                path = Path(current) / file
                if path.is_file():
                    found.append(path)
        if len(found) >= 30:
            break
    return sorted(found)[:30]


def services_from_file(path, directory, project):
    p = query(["docker", "compose", "-p", project,
               "--project-directory", str(directory),
               "-f", str(path), "config", "--services"], timeout=25)
    if p is None or p.returncode:
        return None
    return set(p.stdout.splitlines())


def report(live):
    for project, expected in TARGETS.items():
        root = ROOT / project
        print(f"\n===== {project.upper()} =====")
        print("Project directory exists:", root.is_dir())
        members = []
        for container in live:
            labels = container.get("Config", {}).get("Labels") or {}
            if labels.get("com.docker.compose.project") == project:
                service = labels.get("com.docker.compose.service", "(missing)")
                name = container["Name"].removeprefix("/")
                members.append((service, name, labels))
        print("Running/existing Compose members:")
        for service, name, _ in sorted(members):
            print(f"  {name}: service={service}")
        actual_services = {s for s, _, _ in members}
        print("Required services present in Docker:",
              all(s in actual_services for s in expected))
        source_files = set()
        for _, _, labels in members:
            for item in (labels.get("com.docker.compose.project.config_files")
                         or "").split(","):
                if item.strip():
                    source_files.add(item.strip())
        print("Recorded Compose paths:")
        for original in sorted(source_files):
            path = Path(original)
            print(f"  {original}:",
                  "file exists" if path.is_file() else "MISSING",
                  "(symlink)" if path.is_symlink() else "")
        candidates = candidate_files(root)
        print("Candidate Compose files in project directory:")
        if not candidates:
            print("  NONE found within depth 3")
        for candidate in candidates:
            services = services_from_file(candidate, root, project)
            if services is None:
                label = "services UNVERIFIED (Compose parsing/interpolation failed)"
            else:
                matched = sorted(expected & services)
                label = "matches: " + (", ".join(matched) or "(none)")
            print(f"  {candidate}: {label}")
        if not candidates or all(
            not (expected <= (services_from_file(path, root, project) or set()))
            for path in candidates
        ):
            print("CAUTION: No single candidate was verified to contain all",
                  "needed services. Do not recreate this project yet.")

def main():
    if socket.gethostname() != "openmediavault":
        raise RuntimeError("Wrong host: expected openmediavault")
    print("Read-only stale Compose path discovery; no containers modified.")
    report(get_live())
    print("\nRESULT: Discovery complete. No Compose or Docker writes performed.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        sys.exit(1)
