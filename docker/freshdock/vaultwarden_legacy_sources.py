#!/usr/bin/env python3
"""Read-only legacy Vaultwarden Compose recovery evidence.

Scans a bounded list of possible backup Compose files under /docker/vaultwarden.
Asks Docker Compose for *service names only*. No user containers or files changed,
and no environment values, Compose contents, or secrets are displayed.
"""
from pathlib import Path
import json
import os
import re
import socket
import subprocess
import sys

ROOT = Path("/docker/vaultwarden")
EXPECTED = {"vaultwarden", "nginx", "application", "tailscale"}
CANDIDATES = re.compile(
    r"^(?:docker-)?compose(?:\.override)?\.ya?ml"
    r"(?:[.-](?:backup|bak|old|save|original|orig|[0-9]{8,}).*)?$",
    re.IGNORECASE,
)
SKIP_DIRS = {"vw-data", "data", "ts", "state", "config", "cache", "log",
             "logs", ".git", "certs", "node_modules"}


def command(args, timeout=25):
    try:
        return subprocess.run(args, text=True, capture_output=True,
                              timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def candidates():
    result = []
    if not ROOT.is_dir():
        return []
    for directory, dirs, names in os.walk(ROOT, followlinks=False):
        level = len(Path(directory).relative_to(ROOT).parts)
        dirs[:] = [] if level >= 2 else [
            d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
        ]
        for name in names:
            path = Path(directory) / name
            if CANDIDATES.fullmatch(name) and path.is_file() and not path.is_symlink():
                result.append(path)
    return sorted(result)[:60]


def names_for(paths):
    args = ["docker", "compose", "-p", "vaultwarden",
            "--project-directory", str(ROOT)]
    for path in paths:
        args += ["-f", str(path)]
    p = command(args + ["config", "--services"])
    return set(p.stdout.splitlines()) if p is not None and p.returncode == 0 else None


def live():
    p = command(["docker", "ps", "-aq"])
    if p is None or p.returncode:
        raise RuntimeError("Cannot list Docker containers")
    ids = p.stdout.split()
    p = command(["docker", "inspect", *ids], timeout=45) if ids else None
    if ids and (p is None or p.returncode):
        raise RuntimeError("Cannot inspect Docker container labels")
    objs = json.loads(p.stdout) if ids else []
    found = {}
    for obj in objs:
        lbl = obj.get("Config", {}).get("Labels") or {}
        if lbl.get("com.docker.compose.project") == "vaultwarden":
            found[lbl.get("com.docker.compose.service", "?")] = {
                "name": obj["Name"].removeprefix("/"),
                "state": obj["State"]["Status"],
                "created": obj.get("Created", "?")[:19],
                "config_files": lbl.get("com.docker.compose.project.config_files", ""),
            }
    return found


def main():
    if socket.gethostname() != "openmediavault":
        raise RuntimeError("Wrong host")
    members = live()
    print("===== RUNNING VAULTWARDEN PROJECT =====")
    for service, info in sorted(members.items()):
        print(f"{service}: container={info['name']}, state={info['state']}, "
              f"created={info['created']}")
        for path in info["config_files"].split(","):
            if path.strip():
                print("  recorded source:", path,
                      "EXISTS" if Path(path).is_file() else "MISSING")
    print("\n===== PRESENT COMPOSE SOURCES =====")
    current = (ROOT / "compose.yml", ROOT / "compose.override.yml")
    print("Base+override both present:", all(f.is_file() for f in current))
    names = names_for(current) if all(f.is_file() for f in current) else None
    print("Services:", ", ".join(sorted(names)) if names is not None
          else "UNVERIFIED")
    print("Live services absent from current source:",
          ", ".join(sorted(members.keys() - (names or set()))) or "none")

    print("\n===== LEGACY/BACKUP COMPOSE CANDIDATES =====")
    all_candidates = candidates()
    backup = [p for p in all_candidates if p not in current]
    if not backup:
        print("No additional named Compose/backup candidates found in project tree")
    good = []
    for path in backup:
        names = names_for((path,))
        print(str(path), "services:",
              ", ".join(sorted(names)) if names is not None else "UNVERIFIED")
        if names and {"vaultwarden", "nginx"} <= names:
            good.append((path,))
        # Backup overlay may provide the missing services alongside today's base.
        if path.name.lower().startswith(("compose.override", "docker-compose.override")):
            base = ROOT / "compose.yml"
            if base.is_file():
                together = names_for((base, path))
                print("  paired with compose.yml:",
                      ", ".join(sorted(together))
                      if together is not None else "UNVERIFIED")
                if together and EXPECTED <= together:
                    good.append((base, path))
    print("\n===== VERDICT =====")
    if good:
        for files in good:
            print("POSSIBLE LEGACY SOURCE:", " + ".join(str(f) for f in files))
        print("Still requires comparison of effective Docker configuration; "
              "do NOT recreate yet.")
    else:
        print("No checked backup defines both missing services. Current nginx "
              "and vaultwarden containers are not represented by current "
              "Compose sources. Do NOT recreate these services.")
    print("READ ONLY: no Docker or file modifications.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print("STOP:", str(exc), file=sys.stderr)
        sys.exit(1)
