#!/usr/bin/env python3
"""Read-only WUD-to-Freshdock migration audit for the actual OMV Docker host.

Never reads or prints private .env/Compose contents, passwords, email addresses,
tokens, container environment values, or Docker mount host paths.
"""
import json
import re
import socket
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HOST = "openmediavault"
WUD = "wud"
SMTP_FIELDS = (
    "WUD_TRIGGER_SMTP_LEGACY_HOST",
    "WUD_TRIGGER_SMTP_LEGACY_PORT",
    "WUD_TRIGGER_SMTP_LEGACY_USER",
    "WUD_TRIGGER_SMTP_LEGACY_PASS",
    "WUD_TRIGGER_SMTP_LEGACY_FROM_ADDRESS",
    "WUD_TRIGGER_SMTP_LEGACY_TO",
)
UPDATER_LABELS = (
    "freshdock.enable", "freshdock.mode", "freshdock.schedule",
    "freshdock.notify", "com.centurylinklabs.watchtower.enable",
    "com.centurylinklabs.watchtower.monitor-only",
)


class Stop(Exception):
    pass


def run(*args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=35)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise Stop(f"{args[0]} unavailable or timed out ({type(exc).__name__})") from None
    if p.returncode:
        raise Stop(f"{args[0]} {args[1] if len(args) > 1 else ''} failed ({p.returncode})")
    return p.stdout


def getcontainers():
    ids = run("docker", "ps", "-aq").split()
    return json.loads(run("docker", "inspect", *ids)) if ids else []


def short(x):
    return str(x or "-").replace("\n", " ").replace("\r", " ")[:140]


def bool_label(labels, key):
    value = str(labels.get(key, "")).strip().lower()
    return value == "true"


def matching_name(name, regex):
    try:
        return bool(re.fullmatch(regex, name))
    except re.error:
        raise Stop("Invalid WUD watcher regex") from None


def main():
    if socket.gethostname() != HOST:
        raise Stop(f"Wrong host: {socket.gethostname()}")
    rows = getcontainers()
    by_name = {o.get("Name", "").removeprefix("/"): o for o in rows}
    wud = by_name.get(WUD)
    if wud is None:
        raise Stop("WUD container missing: cannot inspect actual watcher scope")
    labels = wud.get("Config", {}).get("Labels") or {}
    if (labels.get("com.docker.compose.project") != "wud" or
        labels.get("com.docker.compose.service") != "wud" or
        labels.get("com.docker.compose.project.working_dir") != "/docker/wud"):
        raise Stop("WUD Compose project/service/location mismatch")
    env = dict(x.split("=", 1) for x in wud["Config"].get("Env", []) if "=" in x)
    include = env.get("WUD_WATCHER_LOCAL_INCLUDE", "")
    exclude = env.get("WUD_WATCHER_LOCAL_EXCLUDE", "")
    if not (include.startswith("^") and include.endswith("$") and
            env.get("WUD_WATCHER_LOCAL_WATCHBYDEFAULT") == "false"):
        raise Stop("WUD does not have the expected anchored opt-in selection")
    try:
        re.compile(include)
        if exclude:
            re.compile(exclude)
    except re.error:
        raise Stop("Invalid WUD watcher include/exclude regex") from None

    expected = [n for n in by_name if matching_name(n, include)]
    selected = []
    opt_ins_outside = []
    explicit_wud_excludes = []
    other_freshdock_opts = []
    for name, obj in sorted(by_name.items()):
        lbl = obj.get("Config", {}).get("Labels") or {}
        opted_in = bool_label(lbl, "wud.watch")
        wud_false = str(lbl.get("wud.watch", "")).lower() == "false"
        included = matching_name(name, include)
        excluded = bool(exclude and re.search(exclude, name))
        if opted_in and (not included or excluded):
            opt_ins_outside.append(name)
        if included and wud_false:
            explicit_wud_excludes.append(name)
        if (included and not excluded and not wud_false) or opted_in:
            selected.append((name, obj))
        if any(k in lbl for k in UPDATER_LABELS):
            other_freshdock_opts.append(name)

    projects = defaultdict(list)
    missing_compose = []
    files = defaultdict(set)
    missing_files = []
    dependency_notes = []
    for name, obj in selected:
        l = obj.get("Config", {}).get("Labels") or {}
        project = l.get("com.docker.compose.project")
        service = l.get("com.docker.compose.service")
        config_paths = l.get("com.docker.compose.project.config_files") or ""
        workdir = l.get("com.docker.compose.project.working_dir")
        if not (project and service and workdir and config_paths):
            missing_compose.append(name)
            project, service = project or "-", service or "-"
        projects[(project, workdir or "-")].append((service, name, obj))
        for f in config_paths.split(","):
            if f.strip():
                files[project].add(f.strip())
                if not Path(f.strip()).is_file():
                    missing_files.append((name, f.strip()))
        deps = l.get("com.docker.compose.depends_on", "")
        if "service_completed_successfully" in deps:
            dependency_notes.append((name, deps))

    gluetun = by_name.get("gluetun")
    transmission = by_name.get("transmission")
    mullvad = by_name.get("mullvad-browser")
    print("===== ACTUAL HOST AND WUD =====")
    print("Host:", socket.gethostname())
    print("Docker Engine:", short(run("docker", "version", "--format",
                                      "{{.Server.Version}}").strip()))
    print("WUD image:", short(wud["Config"]["Image"]))
    print("WUD state:", short(wud["State"]["Status"]))
    for k in ("WUD_WATCHER_LOCAL_CRON", "WUD_WATCHER_LOCAL_WATCHATSTART",
              "WUD_WATCHER_LOCAL_WATCHEVENTS", "WUD_TRIGGER_DOCKER_UPDATES_AUTO",
              "WUD_TRIGGER_SMTP_LEGACY_AUTO", "WUD_TRIGGER_SMTP_LEGACY_EVENTS",
              "WUD_TRIGGER_SMTP_LEGACY_TLS_ENABLED",
              "WUD_TRIGGER_SMTP_LEGACY_TLS_VERIFY"):
        print(k, "=", short(env.get(k, "unset")))
    print("SMTP required fields present:", sum(bool(env.get(k)) for k in SMTP_FIELDS),
          "/", len(SMTP_FIELDS), "(values kept private)")
    print("WUD include entries (running/stopped container matches):", len(expected))
    print("WUD effective candidate count:", len(selected))
    print("Unintended wud.watch=true label overrides:", len(opt_ins_outside),
          ", ".join(opt_ins_outside) if opt_ins_outside else "none")
    print("Allowlisted wud.watch=false exclusions:", len(explicit_wud_excludes),
          ", ".join(explicit_wud_excludes) if explicit_wud_excludes else "none")
    print("Already carrying Freshdock/Watchtower policy labels:",
          len(other_freshdock_opts),
          ", ".join(other_freshdock_opts) if other_freshdock_opts else "none")

    print("\n===== WUD SELECTED COMPOSE SERVICES =====")
    for (project, workdir), members in sorted(projects.items()):
        print(f"\nProject={short(project)} directory={short(workdir)}")
        for service, name, obj in sorted(members):
            label = obj.get("Config", {}).get("Labels") or {}
            policy = (f"freshdock.enable={label.get('freshdock.enable', 'unset')}, "
                      f"freshdock.mode={label.get('freshdock.mode', 'unset')}, "
                      f"freshdock.notify={label.get('freshdock.notify', 'unset')}")
            print(f"  {short(name)} | service={short(service)} | "
                  f"state={short(obj['State']['Status'])} | "
                  f"net={short(obj['HostConfig']['NetworkMode'])} | {policy}")
        print("  Source Compose files:")
        for f in sorted(files[project]):
            print("   ", short(f))

    print("\n===== PRIVACY DEPENDENCY =====")
    if gluetun:
        gid = gluetun["Id"]
        print("Gluetun state:", gluetun["State"]["Status"],
              "health:", (gluetun["State"].get("Health") or {}).get("Status", "none"),
              "id:", gid[:16])
        for name, obj in (("transmission", transmission),
                          ("mullvad-browser", mullvad)):
            if obj:
                print(name, "state:", obj["State"]["Status"],
                      "attached to CURRENT Gluetun:",
                      obj["HostConfig"]["NetworkMode"] == "container:" + gid)
    else:
        print("Gluetun missing")

    print("\n===== MIGRATION LIMITS / RISKS =====")
    print("Freshdock has no WUD-style name allowlist. Its automatic update scope",
          "must be created with per-service Compose labels.")
    print("Required labels for approved services: freshdock.enable=true,",
          "freshdock.mode=nightly, freshdock.schedule='45 2 * * *',",
          "freshdock.notify=true")
    print("Keep FRESHDOCK_WATCH_ALL=false; never enable fleet-wide auto updates.")
    print("Missing/mismatched selected Compose identities:",
          ", ".join(missing_compose) if missing_compose else "none")
    print("Selected Compose paths not present:",
          len(missing_files))
    for name, f in missing_files[:10]:
        print(" ", short(name), short(f))
    print("Selected services with one-shot dependencies:", len(dependency_notes))
    for name, deps in dependency_notes[:10]:
        print(" ", short(name), short(deps))
    print("Existing updater identities: WUD=",
          "present" if "wud" in by_name else "missing",
          "Freshdock=", "present" if "freshdock" in by_name else "absent",
          "Watchtower=", "present" if "watchtower" in by_name else "absent")
    print("Audit is READ ONLY: no services restarted, paused, modified or deployed.")


if __name__ == "__main__":
    try:
        main()
    except (Stop, OSError, KeyError, ValueError) as exc:
        print("STOP:", str(exc), file=sys.stderr)
        sys.exit(1)
