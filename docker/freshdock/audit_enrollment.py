#!/usr/bin/env python3
"""ONE-SHOT, READ-ONLY, ALL-SERVICE Compose enrollment audit.

Explains why Docker's recorded Compose hashes differ from the current source
without changing any service or printing secrets, environment variables,
mount paths, or resolved Compose contents. Works before or after WUD cutover.
"""
import json
import re
import socket
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

SKIP = {"gluetun", "transmission", "mullvad-browser",
        "vaultwarden", "nginx-vaultwarden"}
ROOT = Path("/docker/freshdock")

class Stop(RuntimeError):
    pass

def cmd(argv, timeout=45):
    try:
        return subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None

def docker(*args):
    return cmd(["docker", *args])

def require(ok, msg):
    if not ok:
        raise Stop(msg)

def get_all():
    p = docker("ps", "-aq")
    require(p is not None and p.returncode == 0, "Docker inventory unavailable")
    ids = p.stdout.split()
    if not ids:
        return {}
    p = cmd(["docker", "inspect", *ids], timeout=70)
    require(p is not None and p.returncode == 0, "Docker inspection unavailable")
    return {c["Name"].removeprefix("/"): c for c in json.loads(p.stdout)}

def source_names(allc):
    if "wud" in allc:
        w = allc["wud"]
        require(w["State"]["Status"] == "running", "WUD not running")
        lbl = w["Config"].get("Labels") or {}
        require(lbl.get("com.docker.compose.project") == "wud" and
                lbl.get("com.docker.compose.service") == "wud",
                "WUD Compose identity not verified")
        env = dict(x.split("=", 1) for x in w["Config"]["Env"] if "=" in x)
        regex = env.get("WUD_WATCHER_LOCAL_INCLUDE", "")
        require(regex.startswith("^(?:") and regex.endswith(")$") and
                env.get("WUD_WATCHER_LOCAL_WATCHBYDEFAULT") == "false",
                "Unexpected WUD selection policy")
        return {n for n in allc if re.fullmatch(regex, n) and
                str((allc[n]["Config"].get("Labels") or {})
                    .get("wud.watch", "")).lower() != "false"}
    require("freshdock" in allc, "Neither WUD nor Freshdock present")
    path = ROOT / "selected.json"
    require(path.is_file() and not path.is_symlink() and
            path.stat().st_uid == 0 and (path.stat().st_mode & 0o777) == 0o600,
            "Selected names file missing or insecure")
    selection = json.loads(path.read_text())
    require(selection.get("source") == "live-wud-9.4.1" and
            selection.get("cron") == "45 2 * * *",
            "Unknown selection provenance")
    return set(selection["container_names"])

def source_group(container):
    lbl = container["Config"].get("Labels") or {}
    project = lbl.get("com.docker.compose.project")
    service = lbl.get("com.docker.compose.service")
    directory = lbl.get("com.docker.compose.project.working_dir")
    raw = lbl.get("com.docker.compose.project.config_files")
    require(all((project, service, directory, raw)), "Missing Compose ownership labels")
    require(directory.startswith("/docker/"), "Unexpected Compose source directory")
    files = tuple(Path(x.strip()) for x in raw.split(","))
    if not all(f.is_file() for f in files):
        if project == "rustdesk" and Path("/docker/rustdesk/compose.yml").is_file():
            files = (Path("/docker/rustdesk/compose.yml"),)
        else:
            raise Stop("Missing original Compose source files")
    return (project, directory, files), service

def project_config(project, directory, files):
    base = ["docker", "compose", "-p", project, "--project-directory", directory]
    for file in files:
        base.extend(["-f", str(file)])
    p = cmd(base + ["config", "--hash=*"])
    if p is None or p.returncode:
        raise Stop("Compose hash query rejected")
    hashes = {}
    for line in p.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2 and re.fullmatch("[a-fA-F0-9]{64}", fields[1]):
            hashes[fields[0].rstrip(":")] = fields[1].lower()
    p = cmd(base + ["config", "--format", "json"])
    if p is None or p.returncode:
        raise Stop("Compose config parse rejected")
    return hashes, json.loads(p.stdout)

def safe_diffs(container, spec, fullc, project):
    """Compare only safety-critical effective settings, never disclose values."""
    problems = []
    image = spec.get("image")
    if image and image != container["Config"].get("Image"):
        problems.append("source image reference differs from live")
    host_env = dict(x.split("=", 1) for x in container["Config"].get("Env", []) if "=" in x)
    service_env = spec.get("environment") or {}
    if isinstance(service_env, list):
        service_env = dict(x.split("=", 1) for x in service_env if "=" in x)
    mismatched_env = sum(str(v) != host_env.get(k) for k,v in service_env.items())
    if mismatched_env:
        problems.append(f"{mismatched_env} configured environment values differ")
    want_restart = str(spec.get("restart", "no"))
    got_restart = container["HostConfig"].get("RestartPolicy", {}).get("Name", "no")
    if want_restart != got_restart:
        problems.append("restart policy differs")
    mode = str(spec.get("network_mode") or "")
    actual_mode = str(container["HostConfig"].get("NetworkMode", ""))
    if mode.startswith("service:"):
        parent = mode.partition(":")[2]
        matches = [c for c in fullc.values() if
                   (c["Config"].get("Labels") or {}).get("com.docker.compose.project") == project and
                   (c["Config"].get("Labels") or {}).get("com.docker.compose.service") == parent]
        if len(matches) != 1 or actual_mode != "container:" + matches[0]["Id"]:
            problems.append("shared-network parent ID differs")
    elif mode in ("host", "none", "bridge") and mode != actual_mode:
        problems.append("network mode differs")
    expected_mounts = set()
    for m in spec.get("volumes", []):
        if not isinstance(m, dict):
            continue
        expected_mounts.add((m.get("type"),str(m.get("source")),m.get("target")))
    current_mounts = {(m.get("Type"),str(m.get("Source")),m.get("Destination"))
                      for m in container.get("Mounts", [])}
    if expected_mounts - current_mounts:
        problems.append("expected mounts differ/missing")
    if current_mounts - expected_mounts:
        problems.append("extra live mounts not in Compose source")
    return problems

def main():
    require(socket.gethostname() == "openmediavault", "Wrong host")
    allc = get_all()
    selected = source_names(allc)
    require(len(selected) == 26 and SKIP <= selected, "Selected scope differs from prior verified state")
    groups = defaultdict(dict)
    failed = []
    for name in sorted(selected - SKIP):
        try:
            key, service = source_group(allc[name])
            groups[key][service] = name
        except (KeyError, Stop) as e:
            failed.append((name, str(e)))
    counts = {"match": 0, "mismatch": 0, "missing": 0}
    print("===== COMPLETE COMPOSE HASH/SOURCE AUDIT =====")
    print("Existing WUD-selected:", len(selected),
          "Protected exclusions:", len(SKIP),
          "Candidates:", len(selected-SKIP))
    print("No Docker/Compose mutations; no SMTP, environment or mount values printed.")
    for (project, directory, files), services in sorted(groups.items()):
        print("\nProject:", project, "sources:", len(files))
        try:
            hashes, config = project_config(project, directory, files)
        except Stop as e:
            for _, name in sorted(services.items()):
                failed.append((name, str(e)))
                print(" ", name, "ERROR:", str(e))
            continue
        print(" Parsed service hashes:", len(hashes), "/",
              len(config.get("services", {})))
        for service, name in sorted(services.items()):
            c = allc[name]
            recorded = (c["Config"].get("Labels") or {}).get("com.docker.compose.config-hash")
            computed = hashes.get(service)
            status = ("MATCH" if recorded and recorded == computed else
                      "MISMATCH" if recorded and computed else "MISSING")
            counts[status.lower()] += 1
            spec = config.get("services", {}).get(service)
            if not isinstance(spec, dict):
                failed.append((name, "Current Compose source has no service definition"))
                print(" ", name, status, "SERVICE MISSING")
                continue
            drift = safe_diffs(c, spec, allc, project)
            img = docker("image", "inspect", c["Config"]["Image"], "--format", "{{.Id}}")
            image_ok = bool(img is not None and img.returncode == 0 and
                            img.stdout.strip() == c["Image"])
            print(" ", name, status,
                  "| image unchanged if recreated:", "yes" if image_ok else "NO",
                  "| other differences:", ", ".join(drift) or "none detected")
            if drift:
                failed.append((name, "; ".join(drift)))
    for name, reason in failed:
        print("\nREVIEW:", name, reason)
    print("\n===== AUDIT TOTAL =====")
    print("Recorded vs current Compose hash:",
          f"MATCH={counts['match']}",
          f"MISMATCH={counts['mismatch']}",
          f"MISSING={counts['missing']}",
          f"ERRORS={len(failed)}")
    print("No services restarted, WUD/Freshdock state unchanged.")
    if failed:
        print("Do not run bulk enrollment until mismatches are resolved.")
    else:
        print("Runtime comparison did not detect the listed critical differences.")
        print("Hash mismatches still require explicit migration-policy review.")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Stop, OSError, ValueError, KeyError) as e:
        print("STOP:", e, file=sys.stderr)
        sys.exit(1)
