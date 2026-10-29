#!/usr/bin/env python3
"""Guarded 24-to-28 Watchtower enrollment on the inspected OMV host.

--check is strictly read-only; --apply changes only Watchtower and its
private Compose/manifest/verifier files. No application restarts or pulls.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
from datetime import datetime, timezone

import watchtower_verify as verify

HOST = "openmediavault"
ROOT = Path("/docker/watchtower-fork")
BACKUP = Path("/root/awtserver-watchtower-enrollment")
COMPOSE = ROOT / "compose.yml"
MANIFEST = ROOT / "targets.json"
VERIFIER = ROOT / "watchtower_verify.py"
SERVICE = "watchtower-fork-verify.service"
TIMER = "watchtower-fork-verify.timer"


class Stop(Exception):
    pass


def need(value, why):
    if not value:
        raise Stop(why)


def run(*args, input_text=None, timeout=90, check=True):
    try:
        proc = subprocess.run(
            args, input=input_text, text=True, capture_output=True,
            timeout=timeout, cwd=ROOT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stop(f"Command unavailable or timed out: {args[0]}") from exc
    if check and proc.returncode:
        raise Stop(f"Command failed: {args[0]} (exit {proc.returncode}; output suppressed)")
    return proc


def compose_cmd(*extra):
    return (
        "docker", "compose", "-p", "watchtower-fork",
        "--project-directory", str(ROOT), "-f", str(COMPOSE), *extra,
    )


def private_file(path, expected_uid=0):
    need(path.is_file() and not path.is_symlink(),
         f"Expected private file unavailable: {path}")
    info = path.stat()
    need(info.st_uid == expected_uid and stat.S_IMODE(info.st_mode) & 0o077 == 0,
         f"Private file ownership/mode unexpected: {path}")
    return path.read_bytes()


def parse_doc(raw, name):
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise Stop(f"{name} is not JSON; manual Compose review required") from exc
    need(isinstance(value, dict), f"{name} must be a JSON object")
    return value


def expected_cmd(names):
    return ["--schedule", verify.SCHEDULE, "--no-startup-message", *names]


def candidates(compose_doc, manifest_doc, names):
    new_names = list(names) + sorted(verify.ADDITIONAL)
    need(len(new_names) == 28 and set(new_names) == verify.EXPANDED,
         "Expanded policy does not match the approved 28 names")
    new_compose = copy.deepcopy(compose_doc)
    new_compose["services"]["watchtower"]["command"] = expected_cmd(new_names)
    new_manifest = copy.deepcopy(manifest_doc)
    new_manifest["container_names"] = new_names
    return new_names, new_compose, new_manifest


def preflight():
    need(os.geteuid() == 0 and socket.gethostname() == HOST,
         "Root on openmediavault is required")
    need(ROOT.is_dir() and not ROOT.is_symlink() and ROOT.stat().st_uid == 0,
         "Unexpected Watchtower directory")
    new_source = Path(verify.__file__).resolve()
    need(new_source.parent.is_dir() and
         new_source.name == "watchtower_verify.py" and
         new_source != VERIFIER.resolve(),
         "Run from a separate staged copy alongside the reviewed verifier")
    need(len(verify.EXPECTED) == 24 and len(verify.EXPANDED) == 28 and
         verify.ADDITIONAL == frozenset({
             "amutorrent", "prowlarr", "trawl", "tailscale-amutorrent"
         }), "Unexpected reviewed verifier policy")

    old_bytes = {
        COMPOSE: private_file(COMPOSE),
        MANIFEST: private_file(MANIFEST),
        VERIFIER: private_file(VERIFIER),
    }
    private_file(ROOT / "notification_url")
    verify.read_smtp(ROOT)
    private_file(new_source)
    need(ROOT.stat().st_mode & stat.S_IWOTH == 0,
         "Watchtower directory is world-writable")
    doc = parse_doc(old_bytes[COMPOSE], "Private Watchtower Compose")
    manifest = parse_doc(old_bytes[MANIFEST], "Private Watchtower manifest")
    need(set(doc.get("services", {})) == {"watchtower"},
         "Unexpected services in Watchtower Compose")
    service_doc = doc["services"]["watchtower"]
    names = manifest.get("container_names")
    need(isinstance(names, list) and len(names) == 24 and
         set(names) == verify.EXPECTED and len(set(names)) == 24,
         "Expected exact original 24-target manifest")
    need(manifest.get("schedule") == verify.SCHEDULE,
         "Original Watchtower schedule changed")
    need(service_doc.get("command") == expected_cmd(names),
         "Private Compose command does not match manifest")
    need(service_doc.get("image") == "nickfedor/watchtower:1.23.1" and
         service_doc.get("container_name") == "watchtower",
         "Watchtower image or container identity changed")
    need(service_doc.get("restart") == "unless-stopped",
         "Unexpected Watchtower restart policy")
    need(service_doc.get("labels", {}).get(
         "com.centurylinklabs.watchtower.enable") == "false",
         "Watchtower self-update exclusion changed")

    inventory = verify.docker_inventory()
    current = inventory.get("watchtower")
    need(current is not None and verify.state(current) == "running",
         "Watchtower is not running")
    need(current["Config"].get("Cmd") == expected_cmd(names),
         "Running Watchtower target list diverges from private files")
    need(current["Config"].get("Image") == service_doc["image"],
         "Watchtower image differs from private Compose")
    labels = verify.labels(current)
    need(labels.get("com.docker.compose.project") == "watchtower-fork" and
         labels.get("com.docker.compose.service") == "watchtower" and
         labels.get("com.docker.compose.project.config_files") == str(COMPOSE) and
         labels.get("com.docker.compose.project.working_dir") == str(ROOT),
         "Watchtower Compose project/provenance unexpectedly changed")
    need(not any(n in inventory for n in (
        "transmission-brother", "tailscale-transmission-brother"
    )), "Second Transmission is explicitly not approved")
    need(run("systemctl", "is-active", "--quiet", TIMER, check=False).returncode == 0,
         "Independent verifier timer not active")
    unit = run("systemctl", "cat", SERVICE).stdout
    need("ExecStart=/usr/bin/python3 /docker/watchtower-fork/watchtower_verify.py --verify --notify-on-failure" in unit,
         "Verification service does not use the expected independent script")

    # Ensure we never enable an incompatible policy even temporarily.
    new_names, next_compose, next_manifest = candidates(doc, manifest, names)
    synthetic = copy.deepcopy(inventory)
    synthetic["watchtower"]["Config"]["Cmd"] = expected_cmd(new_names)
    verify.verify_runtime(synthetic, new_names)
    config = json.dumps(next_compose, indent=2) + "\n"
    result = run("docker", "compose", "-p", "watchtower-fork",
                 "--project-directory", str(ROOT), "-f", "-",
                 "config", "--quiet", input_text=config)
    need(result.returncode == 0, "Candidate Compose configuration invalid")

    # Parse the real base too, rather than relying only on the JSON edit.
    run(*compose_cmd("config", "--quiet"))
    saved_nonwatchtower = {
        name: (item["Id"], item["State"]["Status"])
        for name, item in inventory.items() if name != "watchtower"
    }
    print("PASS: Existing Watchtower command and 24-target manifest match")
    print("PASS: 28-target policy fits the live fleet; VPN dependency checks passed")
    print("PASS: Candidate Compose validates; 05:00 verification timer is active")
    print("PASS: One existing Transmission; no application restart planned")
    return old_bytes, next_compose, next_manifest, saved_nonwatchtower


def write_atomic(path, data, mode=0o600):
    staged = ROOT / ("." + path.name + ".enrollment-" + str(os.getpid()))
    need(not staged.exists() and not staged.is_symlink(),
         "Unexpected staged file already exists")
    try:
        fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(staged, mode)
        os.replace(staged, path)
    finally:
        if staged.exists():
            staged.unlink()


def backup(original):
    need(not BACKUP.is_symlink(), "Unsafe backup directory symlink")
    BACKUP.mkdir(mode=0o700, exist_ok=True)
    info = BACKUP.stat()
    need(info.st_uid == 0 and info.st_mode & 0o077 == 0,
         "Backup directory access too broad")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = BACKUP / stamp
    destination.mkdir(mode=0o700)
    for path, content in original.items():
        dest = destination / path.name
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as writer:
            writer.write(content)
            writer.flush()
            os.fsync(writer.fileno())
    return destination


def unchanged_apps(before):
    now = verify.docker_inventory()
    changed = [name for name, (identity, status) in before.items()
               if name not in now or (now[name]["Id"], now[name]["State"]["Status"])
               != (identity, status)]
    need(not changed, "Unrelated container identity/state changed: " + ",".join(changed))


def apply(original, next_compose, next_manifest, before):
    target_files = {
        COMPOSE: (json.dumps(next_compose, indent=2) + "\n").encode(),
        MANIFEST: (json.dumps(next_manifest, indent=2) + "\n").encode(),
        VERIFIER: Path(verify.__file__).read_bytes(),
    }
    destination = backup(original)
    print("Root-only rollback backup:", destination, flush=True)
    modified = False
    try:
        # Fail closed if any current live artifact has changed after preflight.
        for path, contents in original.items():
            need(private_file(path) == contents,
                 f"Live file changed during preflight: {path}")
        unchanged_apps(before)
        modified = True
        for path, content in target_files.items():
            write_atomic(path, content)
        run(*compose_cmd("up", "-d", "--no-deps", "--no-build",
                         "--pull", "never", "watchtower"), timeout=120)
        unchanged_apps(before)
        result = run("python3", str(VERIFIER), "--verify", timeout=100)
        print(result.stdout.strip(), flush=True)
        need("28 healthy targets" in result.stdout,
             "Updated verifier did not confirm exact 28-target policy")
        print("PASS: Watchtower-only 28-target enrollment complete")
        print("PASS: Existing application container IDs/states unchanged")
        print("PASS: 05:00 verification unit and SMTP settings untouched")
    except Exception:
        if modified:
            print("FAIL: Enrollment; attempting private file and Watchtower rollback",
                  file=sys.stderr)
            for path, content in original.items():
                try:
                    write_atomic(path, content)
                except Exception as exc:
                    print(f"WARNING: Failed to restore {path}: {type(exc).__name__}",
                          file=sys.stderr)
            try:
                run(*compose_cmd("up", "-d", "--no-deps", "--no-build",
                                 "--pull", "never", "watchtower"), timeout=120)
                print("Restored original 24-target Watchtower command",
                      file=sys.stderr)
            except Exception:
                print("WARNING: Watchtower rollback could not be verified; inspect backup",
                      file=sys.stderr)
            print("NOTE: Original 24-target verifier still has the existing exclusion failure",
                  file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--check", action="store_true", help="Read-only (default)")
    options.add_argument("--apply", action="store_true", help="Enroll 28 existing apps")
    args = parser.parse_args()
    try:
        previous, compose, manifest, before = preflight()
        if not args.apply:
            print("READ-ONLY: No files or containers modified")
            return 0
        apply(previous, compose, manifest, before)
        return 0
    except (Stop, verify.Stop, OSError, KeyError, ValueError, TypeError,
            subprocess.SubprocessError) as exc:
        print("STOP: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
