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
BASE_NAMES = {"compose.yml", "compose.yaml", "docker-compose.yml",
              "docker-compose.yaml"}
OVERLAY_NAMES = {"compose.override.yml", "compose.override.yaml",
                 "docker-compose.override.yml", "docker-compose.override.yaml"}
CANDIDATE_NAMES = BASE_NAMES | OVERLAY_NAMES
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


def services_from_files(paths, directory, project):
    """Ask Compose for service NAMES only. No resolved config or secrets printed."""
    args = ["docker", "compose", "-p", project,
            "--project-directory", str(directory)]
    for path in paths:
        args.extend(("-f", str(path)))
    p = query(args + ["config", "--services"], timeout=30)
    if p is None or p.returncode:
        return None
    return set(p.stdout.splitlines())


def services_from_file(path, directory, project):
    """Keep single-file checks available for the offline safety tests."""
    return services_from_files((path,), directory, project)


def candidate_stacks(files):
    """Probe individual bases/overrides and base+override in Compose order."""
    sets = []
    for file in files:
        sets.append((file,))
        if file.name.lower() not in BASE_NAMES:
            continue
        for overlay in files:
            if (overlay.parent == file.parent and
                    overlay.name.lower() in OVERLAY_NAMES):
                sets.append((file, overlay))
    return sets


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
        print("Candidate Compose source combinations (service names only):")
        if not candidates:
            print("  NONE found within depth 3")
        complete = []
        for files in candidate_stacks(candidates):
            services = services_from_files(files, root, project)
            print("  Files, in Compose order:", ", ".join(str(p) for p in files))
            if services is None:
                print("    UNVERIFIED: Compose parsing/interpolation failed")
                continue
            missing = sorted(actual_services - services)
            extra = sorted(services - actual_services)
            print("    Services:", ", ".join(sorted(services)) or "(none)")
            print("    Missing running services:", ", ".join(missing) or "none")
            print("    Other declared services:", ", ".join(extra) or "none")
            if expected <= services and actual_services <= services:
                complete.append((files, extra))
        if not complete:
            print("CAUTION: No checked Compose file combination defines all",
                  "currently existing project services. Do not recreate.")
        else:
            for files, extra in complete:
                print("POSSIBLE SOURCE:", " + ".join(str(p) for p in files),
                      "(all live services present; further config review required)")
                if extra:
                    print("CAUTION: Source declares additional services not",
                          "currently present:", ", ".join(extra))
        if any(not Path(x).is_file() for x in source_files):
            print("NOTE: Docker container labels still point at missing files.",
                  "A matching replacement is NOT proof the old config is identical.")

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
