#!/usr/bin/env python3
"""Enroll only the actual WUD-selected, verified Compose services in Freshdock.

Default: read-only strict preflight. --apply: stage label-only Compose overlays,
verify semantic equivalence, and recreate only selected safe services. The live
Vaultwarden legacy and Gluetun/Transmission/Mullvad Browser containers are always
excluded until separately repaired. Never run against a different host.
"""
import argparse
from collections import defaultdict
from datetime import datetime
import copy
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

ROOT = Path("/docker/freshdock")
SKIP = {"vaultwarden", "nginx-vaultwarden", "gluetun", "transmission",
        "mullvad-browser"}
CRON = "45 2 * * *"
OVERLAY = "compose.freshdock.yml"

class Stop(RuntimeError):
    pass

def require(ok, msg):
    if not ok:
        raise Stop(msg)

def call(args, *, timeout=60, check=True):
    try:
        p = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as e:
        raise Stop(f"{args[0]} timed out or unavailable ({type(e).__name__})") from None
    if check and p.returncode:
        raise Stop(f"{args[0]} failed (code {p.returncode}); sensitive details withheld")
    return p

def docker(*args, timeout=60, check=True):
    return call(["docker", *args], timeout=timeout, check=check)

def all_containers():
    ids = docker("ps", "-aq").stdout.split()
    return json.loads(docker("inspect", *ids, timeout=90).stdout) if ids else []

def labels(c):
    return c.get("Config", {}).get("Labels") or {}

def compose_cmd(project, directory, paths):
    cmd = ["docker", "compose", "-p", project, "--project-directory", str(directory)]
    for path in paths:
        cmd.extend(("-f", str(path)))
    return cmd

def effective(cmd):
    return json.loads(call(cmd + ["config", "--format", "json"], timeout=45).stdout)

def without_freshdock(tree, selected):
    tree = copy.deepcopy(tree)
    for svc in selected:
        value = tree.get("services", {}).get(svc, {})
        current = value.get("labels")
        if isinstance(current, dict):
            for key in ("freshdock.enable", "freshdock.mode",
                        "freshdock.schedule", "freshdock.notify"):
                current.pop(key, None)
            if not current:
                value.pop("labels", None)
    return tree

def hashes(cmd):
    output = call(cmd + ["config", "--hash=*"], timeout=45).stdout
    found = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) == 2 and re.fullmatch(r"[a-f0-9]{64}", fields[1]):
            found[fields[0].rstrip(":")] = fields[1]
    return found

def canary_labels(services):
    lines = ["# Freshdock labels for ONLY the reviewed WUD-selected containers.",
             "# Always include this as the LAST -f when recreating this Compose project.",
             "services:"]
    for svc in sorted(services):
        require(re.fullmatch(r"[A-Za-z0-9_.-]+", svc), "Unsafe Compose service name")
        lines.extend((f"  {svc}:", "    labels:",
                      '      freshdock.enable: "true"',
                      '      freshdock.mode: "nightly"',
                      f'      freshdock.schedule: "{CRON}"',
                      '      freshdock.notify: "true"'))
    return "\n".join(lines) + "\n"

def network_mode_parent(c):
    mode = c.get("HostConfig", {}).get("NetworkMode") or ""
    return mode.removeprefix("container:") if mode.startswith("container:") else None

def plan(precutover=False):
    require(os.geteuid() == 0, "Root required")
    require(socket.gethostname() == "openmediavault", "Not the confirmed OMV host")
    now = datetime.now().strftime("%H%M")
    require(not ("0215" <= now <= "0445"), "Updater/SnapRAID maintenance window")
    require(docker("compose", "version", check=False).returncode == 0, "Docker Compose unavailable")
    current = all_containers()
    by_name = {c["Name"].lstrip("/"): c for c in current}
    if precutover:
        require("freshdock" not in by_name and "wud" in by_name,
                "Precutover review requires WUD only")
        w = by_name["wud"]
        wl = labels(w)
        require(wl.get("com.docker.compose.project") == "wud" and
                wl.get("com.docker.compose.service") == "wud" and
                w["State"]["Status"] == "running",
                "WUD identity/state changed")
        env = dict(x.split("=", 1) for x in w["Config"]["Env"] if "=" in x)
        include = env.get("WUD_WATCHER_LOCAL_INCLUDE", "")
        require(include.startswith("^(?:") and include.endswith(")$") and
                env.get("WUD_WATCHER_LOCAL_WATCHBYDEFAULT") == "false",
                "WUD policy changed")
        try:
            reg = re.compile(include)
        except re.error:
            raise Stop("Malformed WUD include regex") from None
        chosen = sorted(n for n in by_name if reg.fullmatch(n) and
                        str(labels(by_name[n]).get("wud.watch", "")).lower() != "false")
    else:
        require("wud" not in by_name, "WUD still present. Run safe daemon switch first")
        fresh = by_name.get("freshdock")
        require(fresh is not None and fresh["State"]["Status"] == "running" and
                fresh["Config"]["Image"] == "ghcr.io/turbootzz/freshdock:1.7.1",
                "Expected Freshdock v1.7.1 missing")
        meta = ROOT / "selected.json"
        require(meta.is_file() and not meta.is_symlink() and
                meta.stat().st_uid == 0 and (meta.stat().st_mode & 0o777) == 0o600,
                "Verified private selected.json missing or unsafe")
        selection = json.loads(meta.read_text())
        require(selection.get("source") == "live-wud-9.4.1" and
                selection.get("cron") == CRON, "Unknown selection provenance")
        chosen = selection.get("container_names")
    require(isinstance(chosen, list) and len(chosen) == 26 and
            len(set(chosen)) == len(chosen), "WUD selection no longer matches expected count")
    require(set(chosen) <= set(by_name), "Some selected containers are now missing")
    require(SKIP <= set(chosen), "Protected service not in recorded WUD scope")
    require(not any(labels(c).get("freshdock.enable") == "true" for c in current),
            "Some services are already enrolled; check partial deployment first")
    # Mass application recreation must not coincide with storage instability.
    kernel = call(["journalctl", "-k", "--since", "30 minutes ago", "-o", "cat",
                   "--no-pager"], check=False, timeout=30)
    require(kernel.returncode == 0, "Cannot inspect recent disk kernel errors")
    require(not re.search(r"ata13(?:\.\d+)?:.*(?:failed|timeout|reset|frozen)|"
                          r"I/O error, dev sdb\b", kernel.stdout, re.I),
            "Recent SATA/SnapRAID disk I/O errors; refuse mass container recreation")
    allowed = set(chosen) - SKIP
    id_to_name = {c["Id"]: c["Name"].lstrip("/") for c in current}
    for c in current:
        dep = network_mode_parent(c)
        if dep and id_to_name.get(dep) in allowed and c["Name"].lstrip("/") not in allowed:
            raise Stop("Unselected dependency of recreated network parent: " +
                       c["Name"].lstrip("/"))
    groups = defaultdict(dict)
    for name in sorted(allowed):
        c = by_name[name]
        l = labels(c)
        proj, svc, directory, file_list = (l.get("com.docker.compose.project"),
            l.get("com.docker.compose.service"),
            l.get("com.docker.compose.project.working_dir"),
            l.get("com.docker.compose.project.config_files"))
        require(all((proj, svc, directory, file_list)),
                f"{name}: missing Compose ownership labels")
        require(directory.startswith("/docker/") and Path(directory).is_dir(),
                f"{name}: unexpected Compose project directory")
        files = tuple(Path(x.strip()) for x in file_list.split(","))
        if not all(x.is_file() for x in files):
            require(proj == "rustdesk" and
                    (Path("/docker/rustdesk/compose.yml")).is_file(),
                    f"{name}: original Compose files unavailable")
            files = (Path("/docker/rustdesk/compose.yml"),)
        require(all(x.is_file() and x.resolve().parent == Path(directory).resolve()
                    for x in files), f"{name}: invalid Compose file location")
        groups[(proj, directory, files)][svc] = name
        require(c["State"]["Status"] == "running", f"{name}: not running; do not recreate")
    prepared = []
    for (project, directory, files), services in sorted(groups.items()):
        base = compose_cmd(project, directory, files)
        orig = effective(base)
        config_hash = hashes(base)
        for svc, name in services.items():
            require(svc in orig.get("services", {}), f"{name}: missing from Compose source")
            stored = labels(by_name[name]).get("com.docker.compose.config-hash")
            require(stored and stored == config_hash.get(svc),
                    f"{name}: current Compose file hash differs from live container; review source")
        dst = Path(directory) / OVERLAY
        require(not dst.exists() and not dst.is_symlink(),
                f"{dst} already exists; no overwrites")
        prepared.append((project, Path(directory), files, services, orig, dst))
    require(len(allowed) == sum(len(p[3]) for p in prepared),
            "Duplicate or omitted Compose selected service")
    return prepared, allowed, by_name

def verify_network(project, services, config, by_name):
    for svc, name in services.items():
        net = (config["services"][svc].get("network_mode") or "")
        if not net.startswith("service:"):
            continue
        parent_service = net.partition(":")[2]
        parents = [c for c in by_name.values() if
                   labels(c).get("com.docker.compose.project") == project and
                   labels(c).get("com.docker.compose.service") == parent_service]
        require(len(parents) == 1, f"{name}: network parent missing or ambiguous")
        require(by_name[name]["HostConfig"]["NetworkMode"] == "container:" + parents[0]["Id"],
                f"{name}: stale network parent after Compose recreation")

def order_services(services, config):
    """Dependencies, including shared-network parents, before their dependents."""
    pending = set(services)
    done = []
    while pending:
        ready = []
        for svc in sorted(pending):
            spec = config["services"][svc]
            depends = set((spec.get("depends_on") or {}).keys())
            net = str(spec.get("network_mode") or "")
            if net.startswith("service:"):
                depends.add(net.partition(":")[2])
            if not (depends & pending):
                ready.append(svc)
        require(ready, "Compose dependency cycle or unresolvable service ordering")
        done.extend(ready)
        pending.difference_update(ready)
    return done

def apply(prepared, allowed, initial):
    staged = []
    safe = False
    try:
        # Stage ALL proposed overlay files and compare entire effective configs
        # first. No container changes until every selected group validates.
        for project, directory, files, services, orig, dst in prepared:
            dst.write_text(canary_labels(services))
            dst.chmod(0o644)
            staged.append(dst)
            current = effective(compose_cmd(project, directory, (*files, dst)))
            require(without_freshdock(current, services) == orig,
                    f"{project}: overlay changed non-label Compose configuration")
            for svc in services:
                l = current["services"][svc].get("labels") or {}
                require(l.get("freshdock.enable") == "true" and
                        l.get("freshdock.mode") == "nightly" and
                        l.get("freshdock.schedule") == CRON and
                        l.get("freshdock.notify") == "true",
                        f"{project}/{svc}: Freshdock label not applied")
        print("PASS: All Compose overlays staged and semantically validated.", flush=True)
        # WUD is already removed and Freshdock watch-all is false.
        for project, directory, files, services, orig, dst in prepared:
            cmd = compose_cmd(project, directory, (*files, dst))
            for svc in order_services(services, orig):
                call(cmd + ["up", "-d", "--no-deps", "--no-build",
                            "--pull", "never", "--force-recreate", svc],
                     timeout=180)
            current = {c["Name"].lstrip("/"): c for c in all_containers()}
            for svc, name in services.items():
                c = current.get(name)
                require(c is not None and c["State"]["Status"] == "running" and
                        labels(c).get("freshdock.enable") == "true",
                        f"{name}: Freshdock enrollment failed")
            verify_network(project, services, orig, current)
            for name, original in initial.items():
                if name not in allowed and (current[name]["Id"],
                    current[name]["State"]["Status"]) != (original["Id"],
                    original["State"]["Status"]):
                    raise Stop(f"Non-selected container changed: {name}")
            print(f"PASS: {project} enrolled {len(services)} services", flush=True)
        current = {c["Name"].lstrip("/"): c for c in all_containers()}
        enrolled = {n for n,c in current.items()
                    if labels(c).get("freshdock.enable") == "true"}
        require(enrolled == allowed, "Freshdock enrolled set does not match approved names")
        for name in SKIP:
            require((current[name]["Id"], current[name]["State"]["Status"]) ==
                    (initial[name]["Id"], initial[name]["State"]["Status"]),
                    f"Protected container changed: {name}")
        safe = True
        print("PASS: Enrolled", len(allowed), "services. Protected exclusions:", ", ".join(sorted(SKIP)))
        print("IMPORTANT: Future manual Compose recreation MUST use the matching",
              "compose.freshdock.yml as the last -f file.", flush=True)
    finally:
        if not safe:
            # If no running labels changed, remove generated overlays. Otherwise
            # KEEP overlays so live container source remains reproducible.
            current = {c["Name"].lstrip("/"): c for c in all_containers()}
            applied = any(labels(c).get("freshdock.enable") == "true"
                          for c in current.values())
            if not applied:
                for dst in staged:
                    dst.unlink(missing_ok=True)
            else:
                # Avoid unattended updates of a half-enrolled estate.
                docker("update", "--restart=no", "freshdock", check=False)
                docker("stop", "--time", "20", "freshdock", check=False)
                print("CRITICAL: Partial enrollment. Freshdock stopped. Keep overlays and inspect.",
                      file=sys.stderr)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true",
                       help="recreate vetted apps with Freshdock labels")
    group.add_argument("--precutover", action="store_true",
                       help="verify Compose hashes while WUD is still running")
    args = p.parse_args()
    try:
        prepared, selected, initial = plan(precutover=args.precutover)
        print("PASS: Read-only preflight", len(selected), "eligible services in",
              len(prepared), "Compose projects.")
        for project, _, _, services, _, _ in prepared:
            print("  ", project, ":", ", ".join(sorted(services)))
        print("PROTECTED:", ", ".join(sorted(SKIP)))
        if args.apply:
            apply(prepared, selected, initial)
        else:
            print("READ ONLY. Precutover checks require no Freshdock installation."
                  if args.precutover else
                  "READ ONLY. --apply performs a scheduled-downtime Compose enrollment.")
        return 0
    except (Stop, OSError, KeyError, ValueError) as e:
        print("STOP:", e, file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
