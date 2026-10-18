#!/usr/bin/env python3
"""Opt-in Freshdock enrollment after a complete read-only live-state comparison.

Default: plan only. --apply recreates each *complete*, reviewed Compose project
with label-only overlays and source-image pinning for two known drift cases.
Stop on unknown changes and preserve private rollback evidence. Never touch
Gluetun/VPN, paused Transmission or legacy Vaultwarden services.
"""
import argparse
import copy
import io
import subprocess
import tarfile
from datetime import datetime
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
from collections import defaultdict

import audit_enrollment as audit
import enroll_services as base

ROOT = Path("/docker/freshdock")
CRON = "45 2 * * *"
PROTECTED = frozenset(base.SKIP)
# EXACT mismatches seen in the 2026-10-18 complete read-only report.
# Any new mismatch invalidates the audited snapshot and aborts before mutation.
KNOWN_HASH_DRIFT = frozenset({
    "audiobookshelf", "brave", "app-dockge", "app-flame", "freshrss",
    "jellyfin", "jellyseerr", "mariadb_jellyseerr", "navidrome",
    "app-ntfy", "hbbr", "hbbs",
})
KNOWN_IMAGE_DRIFT = frozenset({"mariadb_jellyseerr", "app-ntfy"})
ALLOWED_LABELS = ("freshdock.enable", "freshdock.mode",
                  "freshdock.schedule", "freshdock.notify")


class Refused(RuntimeError):
    pass


def need(ok, reason):
    if not ok:
        raise Refused(reason)


def docker(*args, check=True, timeout=60):
    return base.docker(*args, check=check, timeout=timeout)


def live():
    return {c["Name"].removeprefix("/"): c for c in base.all_containers()}


def inspect_policy(c):
    return c.get("Config", {}).get("Labels") or {}


def normalized_caps(values):
    # Docker accepts CAP_NET_ADMIN and NET_ADMIN as equivalent capabilities.
    # Compare canonical names rather than Docker Engine/Compose formatting.
    return {str(cap).upper().removeprefix("CAP_") for cap in (values or [])}


def live_tailscale_cert_domain(container):
    """Retrieve the owning Tailscale node's certified DNS hostname read-only.

    Never accept an arbitrary runtime Web key as its own verification: the
    canonical hostname must originate in the running tailscaled identity.
    """
    try:
        result = subprocess.run(
            ["docker", "exec", container["Name"].removeprefix("/"),
             "tailscale", "status", "--json"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=25, check=False)
        if result.returncode != 0 or len(result.stdout) > 4 * 1024 * 1024:
            return None
        status = json.loads(result.stdout)
        fqdn = status.get("Self", {}).get("DNSName")
        if not isinstance(fqdn, str):
            return None
        fqdn = fqdn.rstrip(".").lower()
        # No newline, path, extra port, wildcard, or empty DNS label can be
        # interpolated into a new service endpoint.
        if (len(fqdn) > 253 or "." not in fqdn or
                not re.fullmatch(
                    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
                    r"(?:\\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+",
                    fqdn)):
            return None
        return fqdn
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        return None


def verify_compose_configs(container, spec, compose_tree):
    """Confirm actual mounted config content matches the resolved Compose source.

    Docker Compose injects config resources as files in the container. Compare
    the exact bytes through read-only 'docker cp' without printing file content.
    Reject any non-inline config source rather than assuming it is equivalent.
    """
    issues = []
    declared = spec.get("configs") or []
    catalog = (compose_tree or {}).get("configs") or {}
    for item in declared:
        if not isinstance(item, dict) or not item.get("source"):
            issues.append("config declaration format unverified")
            continue
        name = item["source"]
        target = item.get("target") or "/" + name
        definition = catalog.get(name)
        if (not isinstance(definition, dict) or
                not isinstance(definition.get("content"), str)):
            issues.append("config source cannot be verified byte-for-byte")
            continue
        expected = definition["content"].encode("utf-8")
        if len(expected) > 1024 * 1024 or not str(target).startswith("/"):
            issues.append("config size/path outside verification scope")
            continue
        try:
            result = subprocess.run(
                ["docker", "cp",
                 container["Name"].removeprefix("/") + ":" + target, "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=20, check=False)
            if result.returncode or len(result.stdout) > 2 * 1024 * 1024:
                issues.append("running config file inaccessible")
                continue
            with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:*") as tf:
                entries = [x for x in tf.getmembers() if x.isfile()]
                if len(entries) != 1:
                    issues.append("running config is not one regular file")
                    continue
                source = tf.extractfile(entries[0])
                actual = source.read(1024 * 1024 + 1) if source else b""
                if actual != expected:
                    try:
                        live_json = json.loads(actual)
                        source_json = json.loads(expected)
                    except (UnicodeError, ValueError):
                        issues.append("running config differs; one or both are not valid JSON")
                        continue
                    if live_json == source_json:
                        # JSON indentation, member order and trailing whitespace
                        # have no semantic effect. Never ignore altered values.
                        continue
                    # Tailscale containerboot substitutes ${TS_CERT_DOMAIN}
                    # from its OWN authenticated node identity when applying
                    # TS_SERVE_CONFIG; current Compose may still hold a template.
                    # Require whole-object equivalence after substitution.
                    if "${TS_CERT_DOMAIN}" in definition["content"]:
                        domain = live_tailscale_cert_domain(container)
                        if domain is None:
                            issues.append("Tailscale DNS identity unavailable")
                            continue
                        rendered = definition["content"].replace(
                            "${TS_CERT_DOMAIN}", domain)
                        try:
                            if json.loads(rendered) == live_json:
                                continue
                        except (UnicodeError, ValueError):
                            issues.append("rendered Tailscale config is not valid JSON")
                            continue
                        issues.append("Tailscale config differs after verified hostname substitution")
                        continue
                    if (isinstance(live_json, dict) and
                            isinstance(source_json, dict) and
                            set(live_json) != set(source_json)):
                        issues.append("running config JSON top-level keys differ")
                    elif (isinstance(live_json, dict) and
                          isinstance(source_json, dict) and
                          "Web" in live_json and "Web" in source_json and
                          isinstance(live_json["Web"], dict) and
                          isinstance(source_json["Web"], dict) and
                          set(live_json["Web"]) != set(source_json["Web"])):
                        issues.append("running config JSON Web hostname keys differ")
                    else:
                        issues.append("running config JSON values differ")
        except (OSError, subprocess.TimeoutExpired, tarfile.TarError, EOFError):
            issues.append("running config cannot be safely compared")
    return issues


def validate_runtime(container, spec, allc, project, compose_tree=None):
    name = container["Name"].removeprefix("/")
    drift = audit.safe_diffs(container, spec, allc, project)
    # The two reviewed source-image differences are restored to their EXACT
    # running references by our overlay before Compose touches anything.
    if name in KNOWN_IMAGE_DRIFT:
        drift = [item for item in drift
                 if item != "source image reference differs from live"]
    # Verify explicit security-sensitive fields; don't print values.
    config = container["Config"]
    host = container["HostConfig"]
    expected = [
        ("user", config.get("User") or ""),
        ("working_dir", config.get("WorkingDir") or ""),
    ]
    for key, actual in expected:
        if key in spec and str(spec[key] or "") != str(actual):
            drift.append(f"{key} differs")
    for key, live_key in (("privileged", "Privileged"),
                          ("read_only", "ReadonlyRootfs"),
                          ("init", "Init")):
        if key in spec and bool(spec[key]) != bool(host.get(live_key)):
            drift.append(f"{key} differs")
    for key, live_key in (("cap_add", "CapAdd"), ("cap_drop", "CapDrop")):
        if key in spec and normalized_caps(spec[key]) != normalized_caps(host.get(live_key)):
            drift.append(f"{key} differs")
    if "security_opt" in spec and sorted(spec["security_opt"] or []) != sorted(
            host.get("SecurityOpt") or []):
        drift.append("security_opt differs")
    if "command" in spec:
        desired = spec.get("command")
        actual = config.get("Cmd")
        if isinstance(desired, list):
            if desired != (actual or []):
                drift.append("command differs")
        elif desired and str(desired) != " ".join(actual or []):
            drift.append("command differs")
    if "entrypoint" in spec:
        desired = spec.get("entrypoint")
        actual = config.get("Entrypoint")
        if isinstance(desired, list):
            if desired != (actual or []):
                drift.append("entrypoint differs")
        elif desired and str(desired) != " ".join(actual or []):
            drift.append("entrypoint differs")
    if "ports" in spec and spec.get("ports"):
        expected_ports = {
            (str(x.get("target")), str(x.get("published")),
             str(x.get("protocol", "tcp")), str(x.get("host_ip", "")))
            for x in spec["ports"] if isinstance(x, dict)
        }
        existing = set()
        for port, host_binds in (host.get("PortBindings") or {}).items():
            portnum, _, proto = port.partition("/")
            for b in host_binds or []:
                existing.add((portnum, str(b.get("HostPort") or ""),
                              proto or "tcp", str(b.get("HostIp") or "")))
        # Wildcard 0.0.0.0 and blank host IP are equivalent on Docker.
        def canonical(x):
            return (x[0], x[1], x[2],
                    "" if x[3] in ("", "0.0.0.0") else x[3])
        if {canonical(x) for x in existing} != {
                canonical(x) for x in expected_ports}:
            drift.append("published ports differ")
    if "devices" in spec:
        expected = {
            (str(x.get("source")), str(x.get("target")))
            for x in spec.get("devices", []) if isinstance(x, dict)
        }
        actual = {(str(x.get("PathOnHost")), str(x.get("PathInContainer")))
                  for x in host.get("Devices", [])}
        if actual != expected:
            drift.append("devices differ")
    label_spec = spec.get("labels") or {}
    runtime_labels = inspect_policy(container)
    for key, value in label_spec.items():
        if key not in ALLOWED_LABELS and str(runtime_labels.get(key)) != str(value):
            drift.append("non-Freshdock service label differs")
            break
    # Exposed settings which the audit cannot safely/reliably compare are
    # blocked rather than considered equivalent.
    for key in ("secrets", "develop", "credential_spec"):
        if spec.get(key):
            drift.append(f"{key} requires separate review")
    if spec.get("configs"):
        if compose_tree is None:
            drift.append("config source tree unavailable")
        else:
            drift.extend(verify_compose_configs(container, spec, compose_tree))
    if name in KNOWN_IMAGE_DRIFT:
        # A separate image override restores the old running image reference.
        need(spec.get("image") != config.get("Image"),
             f"{name}: expected image reference drift disappeared; refresh audit")
    else:
        need(spec.get("image") == config.get("Image"),
             f"{name}: unexpected source image reference drift")
    return sorted(set(drift))


def overlay(services):
    lines = ["# Generated Freshdock labels, preserve as LAST Compose -f overlay.",
             "services:"]
    for service, (name, image_override) in sorted(services.items()):
        need(re.fullmatch(r"[A-Za-z0-9_.-]+", service),
             f"{name}: unsupported Compose service name")
        lines.extend([f"  {service}:", "    labels:",
                      '      freshdock.enable: "true"',
                      '      freshdock.mode: "nightly"',
                      f'      freshdock.schedule: "{CRON}"',
                      '      freshdock.notify: "true"'])
        if image_override is not None:
            lines.extend(["    image: " + json.dumps(image_override)])
    return "\n".join(lines) + "\n"


def plan():
    need(os.geteuid() == 0 and socket.gethostname() == "openmediavault",
         "Root on openmediavault required")
    hhmm = datetime.now().strftime("%H%M")
    need(not ("0215" <= hhmm <= "0445"),
         "Updater scheduled interval; do not recreate now")
    allc = live()
    need("wud" not in allc, "WUD container exists; stop migration")
    fresh = allc.get("freshdock")
    need(fresh and fresh["State"]["Status"] == "running" and
         fresh["Config"]["Image"] == "ghcr.io/turbootzz/freshdock:1.7.1",
         "Expected running Freshdock 1.7.1 missing")
    need(not any(inspect_policy(c).get("freshdock.enable") == "true"
                 for c in allc.values()), "Some containers already enrolled; audit partial state")
    selected = audit.source_names(allc)
    need(len(selected) == 26 and PROTECTED <= selected,
         "Original WUD selection changed")
    expected = selected - PROTECTED
    need(len(expected) == 21, "Expected service count changed")
    projects = defaultdict(dict)
    problems = []
    snapshots = {}
    for name in sorted(expected):
        c = allc.get(name)
        need(c is not None and c["State"]["Status"] == "running",
             f"{name}: selected container not running")
        try:
            key, service = audit.source_group(c)
            projects[key][service] = name
        except audit.Stop:
            problems.append(f"{name}: source Compose files missing")
    for (project, directory, files), members in sorted(projects.items()):
        hashes, source = audit.project_config(project, directory, files)
        require_members = {
            k.get("Config", {}).get("Labels", {}).get("com.docker.compose.service")
            for k in allc.values()
            if (k["Config"].get("Labels") or {}).get("com.docker.compose.project") == project
            and k["State"]["Status"] in ("running", "paused")
        }
        # Atomic rollout only if every live project service is in the snapshot.
        if require_members != set(members):
            problems.append(f"{project}: not all live project members are selected")
        if set(source["services"]) != set(members):
            problems.append(f"{project}: source Compose service set differs from live")
        snapshots[(project, directory, files)] = source
        for svc, name in sorted(members.items()):
            c = allc[name]
            spec = source.get("services", {}).get(svc)
            if not isinstance(spec, dict):
                problems.append(f"{name}: missing Compose service definition")
                continue
            recorded_hash = inspect_policy(c).get("com.docker.compose.config-hash")
            calculated_hash = hashes.get(svc)
            if name in KNOWN_HASH_DRIFT:
                if not recorded_hash or recorded_hash == calculated_hash:
                    problems.append(f"{name}: expected hash drift changed; refresh audit")
            else:
                if not recorded_hash or recorded_hash != calculated_hash:
                    problems.append(f"{name}: unexpected Compose hash drift")
            unexpected = validate_runtime(c, spec, allc, project, source)
            if unexpected:
                problems.append(f"{name}: " + ", ".join(unexpected))
            image = docker("image", "inspect", c["Config"]["Image"],
                           "--format", "{{.Id}}", check=False)
            if image.returncode != 0 or image.stdout.strip() != c["Image"]:
                problems.append(f"{name}: local image ID differs from currently running image")
            # Network parent must be explicitly selected in the same project
            mode = spec.get("network_mode") or ""
            if str(mode).startswith("service:"):
                parent = mode.partition(":")[2]
                if parent not in members:
                    problems.append(f"{name}: network parent is not selected in project")
        dst = Path(directory) / "compose.freshdock.yml"
        if dst.exists() or dst.is_symlink():
            problems.append(f"{project}: an enrollment overlay already exists")
    need(len(projects) > 0, "No eligible Compose projects")
    # Affected live namespace dependencies must be selected together.
    for name, c in allc.items():
        net = c["HostConfig"].get("NetworkMode") or ""
        if not net.startswith("container:"):
            continue
        parent_id = net.removeprefix("container:")
        parent_names = {k for k, v in allc.items() if v["Id"] == parent_id}
        if parent_names & expected and name not in expected:
            problems.append(f"{name}: unselected child would be stranded")
    return allc, projects, snapshots, problems


def apply(allc, projects, source, problems):
    need(not problems, "Refusing changes: unresolved runtime/Compose differences")
    staged = []
    private = ROOT / "snapshots"
    need(not private.exists(), "Private snapshot directory already exists; no overwrites")
    private.mkdir(mode=0o700)
    finished = False
    try:
        # Save private inspect records for manual recovery. Never print them or
        # upload them. Contains secrets.
        with (private / "before-enrollment.json").open("x") as fh:
            json.dump(allc, fh)
        (private / "before-enrollment.json").chmod(0o600)
        for key, services in sorted(projects.items()):
            project, directory, files = key
            overlay_path = Path(directory) / "compose.freshdock.yml"
            entries = {
                svc: (name, allc[name]["Config"]["Image"] if
                      name in KNOWN_IMAGE_DRIFT else None)
                for svc, name in services.items()
            }
            overlay_path.write_text(overlay(entries))
            overlay_path.chmod(0o644)
            staged.append(overlay_path)
            cmd = base.compose_cmd(project, directory, (*files, overlay_path))
            new = base.effective(cmd)
            old = copy.deepcopy(source[key])
            # The overlay may only add Freshdock labels, plus restoring two
            # source image refs to the EXACT live refs already in use.
            reduced = base.without_freshdock(new, services)
            for svc, (name, image) in entries.items():
                if image is not None:
                    need(reduced["services"][svc]["image"] == image,
                         f"{name}: image override did not resolve")
                    reduced["services"][svc]["image"] = old["services"][svc]["image"]
            need(reduced == old,
                 f"{project}: overlay modified more than reviewed labels/image references")
        print("PASS: All project overlays staged and validated.", flush=True)
        # Recreate full projects atomically by passing every active service to
        # Compose together. Compose handles network_mode:service parent graph.
        for key, services in sorted(projects.items()):
            project, directory, files = key
            ovr = Path(directory) / "compose.freshdock.yml"
            selected_services = sorted(services)
            cmd = base.compose_cmd(project, directory, (*files, ovr))
            base.call(cmd + ["up", "-d", "--no-build", "--pull", "never",
                             "--force-recreate", *selected_services], timeout=240)
            now = live()
            for svc, name in services.items():
                old = allc[name]
                c = now.get(name)
                need(c is not None and c["State"]["Status"] == "running",
                     f"{name}: failed to restart")
                p = inspect_policy(c)
                need(p.get("freshdock.enable") == "true" and
                     p.get("freshdock.mode") == "nightly" and
                     p.get("freshdock.schedule") == CRON and
                     p.get("freshdock.notify") == "true",
                     f"{name}: labels missing")
                need(c["Image"] == old["Image"],
                     f"{name}: image ID changed during label enrollment")
            base.verify_network(project, services, source[key], now)
            for name, old in allc.items():
                if name in {n for group in projects.values() for n in group.values()}:
                    continue
                c = now.get(name)
                need(c and c["Id"] == old["Id"] and
                     c["State"]["Status"] == old["State"]["Status"],
                     f"{name}: unselected container unexpectedly changed")
            print(f"PASS: {project}: {len(services)} containers enrolled.", flush=True)
        now = live()
        actual = {n for n, c in now.items() if inspect_policy(c).get("freshdock.enable") == "true"}
        expected = {n for group in projects.values() for n in group.values()}
        need(actual == expected and len(actual) == 21,
             "Enabled policy scope does not equal reviewed set")
        finished = True
        print("RESULT: PASS. Freshdock now automatically updates 21 approved containers at 02:45.",
              flush=True)
        print("Five protected containers remain untouched and unenrolled.", flush=True)
    finally:
        if not finished:
            # No automatic updates during a partially completed cutover.
            docker("update", "--restart=no", "freshdock", check=False)
            docker("stop", "--time", "20", "freshdock", check=False)
            print("PARTIAL: Freshdock stopped. Private snapshots and overlay files retained for recovery.",
                  file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="recreate entire vetted Compose projects and enable updates")
    args = parser.parse_args()
    try:
        allc, projects, snapshots, problems = plan()
        print("===== FRESHDOCK ENROLLMENT CHECK =====")
        print("Projects:", len(projects), "services:", sum(map(len, projects.values())))
        for key, services in sorted(projects.items()):
            print(key[0] + ":", ", ".join(sorted(services.values())))
        if problems:
            print("Changes NOT allowed. Review these exact categories:")
            for problem in problems:
                print("  ", problem)
            return 1
        print("PASS: All project definitions, network ownership, image IDs and scoped"
              " runtime invariants pass.")
        if not args.apply:
            print("READ ONLY. Use --apply for one controlled, project-atomic enrollment.")
        else:
            apply(allc, projects, snapshots, problems)
        return 0
    except (Refused, audit.Stop, base.Stop, KeyError, ValueError, OSError) as exc:
        print("STOP:", str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
