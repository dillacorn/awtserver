#!/usr/bin/env python3
"""Retire STOPPED Freshdock after Watchtower's standalone verifier is working.

Default is read-only. --apply migrates SMTP credentials to Watchtower's private
directory, replaces the 05:00 verifier service, tests its new TLS alert path,
then removes only the stopped Freshdock container, its isolated /docker/freshdock
tree, and its old image (if unused). No other container or volume is modified.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import tomllib

import watchtower_verify as verifier

HOST = "openmediavault"
ROOT = Path("/docker/watchtower-fork")
OLD = Path("/docker/freshdock")
UNITS = Path("/etc/systemd/system")
SERVICE = UNITS / "watchtower-fork-verify.service"
TIMER = "watchtower-fork-verify.timer"
OLD_EXEC = ("ExecStart=/usr/bin/python3 "
            "/docker/watchtower-fork/replace_freshdock.py "
            "--verify --notify-on-failure")
NEW_EXEC = ("ExecStart=/usr/bin/python3 "
            "/docker/watchtower-fork/watchtower_verify.py "
            "--verify --notify-on-failure")
IMAGE = "ghcr.io/turbootzz/freshdock:1.7.1"


def need(ok, message):
    verifier.need(ok, message)


def command(*args, check=True, timeout=45):
    try:
        p = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise verifier.Stop(f"{args[0]} unavailable or timed out") from None
    if check and p.returncode:
        raise verifier.Stop(f"{args[0]} operation failed (details suppressed)")
    return p


def has_prefix(path, root):
    try:
        Path(path).relative_to(root)
        return True
    except ValueError:
        return False


def load_old_mail():
    path = OLD / "freshdock.toml"
    need(path.is_file() and not path.is_symlink(),
         "Original private SMTP configuration not found")
    need(path.stat().st_mode & 0o077 == 0,
         "Original SMTP file permissions unsafe")
    with path.open("rb") as file:
        data = tomllib.load(file)
    mail = data.get("notifications", {}).get("email", {})
    need(mail.get("type") == "smtp", "Original SMTP config not recognized")
    credential = {name: mail[name] for name in
                  ("host", "port", "username", "password", "from", "to", "tls")}
    need(credential["tls"] in ("starttls", "implicit") and
         (credential["tls"], int(credential["port"])) in
         (("starttls", 587), ("implicit", 465)),
         "Unsupported SMTP encryption mode")
    credential["port"] = int(credential["port"])
    need(all(credential.get(x) for x in
             ("host", "username", "password", "from", "to")),
         "Original SMTP credentials incomplete")
    need(isinstance(credential["to"], list) and
         all(isinstance(x, str) and x for x in credential["to"]),
         "Invalid SMTP recipients")
    need(re.fullmatch(r"[A-Za-z0-9.-]+", credential["host"]),
         "Invalid SMTP hostname")
    return credential


def ensure_retirement_safe():
    need(os.geteuid() == 0 and socket.gethostname() == HOST,
         "Must run as root on openmediavault")
    need(not ("0215" <= datetime.now().strftime("%H%M") <= "0445"),
         "Do not retire the updater during nightly maintenance")
    need(command("pgrep", "-x", "snapraid", check=False).returncode != 0,
         "SnapRAID is currently running")
    need(ROOT.is_dir() and not ROOT.is_symlink() and
         ROOT.resolve() == Path("/docker/watchtower-fork"),
         "Installed Watchtower directory invalid")
    need(OLD.is_dir() and not OLD.is_symlink() and
         OLD.resolve() == Path("/docker/freshdock"),
         "Expected Freshdock directory absent or redirected")
    for name in ("compose.yml", "notification_url", "targets.json",
                 "replace_freshdock.py"):
        path = ROOT / name
        need(path.is_file() and not path.is_symlink(),
             f"Installed Watchtower file missing: {name}")
    need(not (ROOT / "watchtower_verify.py").exists() and
         not (ROOT / "alert_smtp.json").exists(),
         "Stand-alone verifier already staged; refusing ambiguous retry")
    source = Path(__file__).with_name("watchtower_verify.py")
    need(source.is_file() and not source.is_symlink(),
         "Reviewed stand-alone verifier must be adjacent to this script")
    need(SERVICE.is_file() and not SERVICE.is_symlink() and
         SERVICE.stat().st_uid == 0,
         "Expected verifier service unit unavailable")
    old_service = SERVICE.read_text()
    need(old_service.count(OLD_EXEC) == 1 and NEW_EXEC not in old_service,
         "Existing verifier service does not match reviewed configuration")
    need(command("systemctl", "is-active", "--quiet", TIMER,
                 check=False).returncode == 0 and
         command("systemctl", "is-enabled", "--quiet", TIMER,
                 check=False).returncode == 0,
         "Watchtower verification timer must be enabled and active")
    # Do not remove a directory hosting bind mounts, custom Compose sources
    # or a network parent for any current/non-Freshdock container.
    mounts = command("findmnt", "-rn", "-o", "TARGET", timeout=30).stdout.splitlines()
    need(not any(has_prefix(target, OLD) for target in mounts),
         "Freshdock directory contains a mount point")
    fleet = verifier.docker_inventory()
    original = fleet.get("freshdock")
    need(original and original["Config"].get("Image") == IMAGE and
         original["State"]["Status"] != "running" and
         original["HostConfig"]["RestartPolicy"]["Name"] == "no",
         "Expected stopped, restart-disabled Freshdock container not found")
    names = verifier.read_targets(ROOT)
    verifier.verify_runtime(fleet, names)
    old_id = original["Id"]
    for name, c in fleet.items():
        if name == "freshdock":
            continue
        need(c["Config"].get("Image") != IMAGE,
             f"{name}: another container still uses Freshdock image")
        need(c["HostConfig"].get("NetworkMode") not in
             ("container:" + old_id, "container:freshdock"),
             f"{name}: uses Freshdock network namespace")
        for m in c.get("Mounts", []):
            need(not has_prefix(m.get("Source", ""), OLD),
                 f"{name}: mounts the Freshdock directory")
        meta = verifier.labels(c)
        for key in ("com.docker.compose.project.working_dir",
                    "com.docker.compose.project.config_files"):
            for part in meta.get(key, "").split(","):
                need(not has_prefix(part.strip(), OLD),
                     f"{name}: original Compose source under Freshdock")
    return fleet, old_service, load_old_mail(), source


def write_new(path, data, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    os.chmod(path, mode)


def replace_service(content):
    fd, temporary = tempfile.mkstemp(prefix=".watchtower-verify-", dir=UNITS)
    try:
        with os.fdopen(fd, "w") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, SERVICE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply(old_service, credentials, source):
    new_script = ROOT / "watchtower_verify.py"
    new_mail = ROOT / "alert_smtp.json"
    old_script = ROOT / "replace_freshdock.py"
    installed_new_service = False
    deletion_started = False
    try:
        write_new(new_script, source.read_bytes(), 0o600)
        write_new(new_mail,
                  (json.dumps(credentials, sort_keys=True) + "\n").encode(), 0o600)
        # Independently test the copied credentials and private-file reader.
        verified = verifier.read_smtp(ROOT)
        need(verified == credentials, "Transferred SMTP settings differ")
        # Actual encrypted SMTP call, before any irreversible deletion.
        verifier.send_tls(
            verified, "OMV Watchtower: standalone alert verification",
            "The Watchtower health check is independent of the retired updater.\n")
        replace_service(old_service.replace(OLD_EXEC, NEW_EXEC))
        installed_new_service = True
        command("systemctl", "daemon-reload")
        # The new script checks all current services while Freshdock still
        # exists. Real systemd integration must pass, not only Python mocks.
        command("systemctl", "start", "watchtower-fork-verify.service")
        need(command("systemctl", "is-active", "--quiet", TIMER,
                     check=False).returncode == 0,
             "Verifier timer no longer active")
        verifier.verify_runtime(verifier.docker_inventory(),
                                verifier.read_targets(ROOT))
        print("PASS: standalone verifier and real encrypted SMTP alert tested",
              flush=True)
        # Only now is deletion allowed. No Docker volumes are deleted.
        deletion_started = True
        command("docker", "rm", "freshdock", timeout=60)
        shutil.rmtree(OLD)
        # Remove only the old, unreferenced verifier entry point.
        old_script.unlink()
        image = command("docker", "image", "rm", IMAGE, check=False, timeout=90)
        if image.returncode:
            print("NOTE: Old Freshdock image could not be removed; "
                  "no force/prune performed", flush=True)
        need("freshdock" not in verifier.docker_inventory(),
             "Retired container still exists")
        need(not OLD.exists(), "Retired Freshdock directory still exists")
        verifier.verify_runtime(verifier.docker_inventory(),
                                verifier.read_targets(ROOT))
        print("PASS: Freshdock container/directory removed; "
              "24 Watchtower targets unchanged and independent verifier healthy",
              flush=True)
    except Exception:
        if not deletion_started:
            if installed_new_service:
                replace_service(old_service)
                command("systemctl", "daemon-reload", check=False)
            new_script.unlink(missing_ok=True)
            new_mail.unlink(missing_ok=True)
        raise


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--apply", action="store_true",
                      help="perform guarded SMTP/verifier handoff and old updater removal")
    chosen = args.parse_args()
    try:
        _, old_service, credentials, source = ensure_retirement_safe()
        print("PASS: openmediavault; Watchtower and 24 applications healthy", flush=True)
        print("PASS: standalone verifier source, timer and old SMTP available",
              flush=True)
        print("PASS: no other container or mount depends on old updater directory",
              flush=True)
        if chosen.apply:
            apply(old_service, credentials, source)
        else:
            print("READ-ONLY PASS: no changes; rerun with --apply", flush=True)
        return 0
    except (verifier.Stop, OSError, KeyError, ValueError, TypeError) as err:
        print(f"STOP: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
