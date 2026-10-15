#!/usr/bin/env python3
"""Merge live-restore into an existing Docker daemon.json without erasing keys."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

CONFIG = Path("/etc/docker/daemon.json")


def enable():
    if CONFIG.is_symlink() or (CONFIG.exists() and not CONFIG.is_file()):
        raise RuntimeError(f"Refusing unsupported Docker config path: {CONFIG}")
    original = CONFIG.read_bytes() if CONFIG.exists() else None
    data = json.loads(original) if original else {}
    if not isinstance(data, dict):
        raise ValueError("daemon.json must contain a JSON object")
    if data.get("live-restore") is True:
        print("Docker live-restore is already enabled")
        return
    data["live-restore"] = True
    payload = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=CONFIG.parent, prefix=".daemon-restore-", suffix=".json")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        validation = subprocess.run(
            ["dockerd", "--validate", "--config-file", temp],
            capture_output=True, text=True,
        )
        if validation.returncode:
            raise RuntimeError("Docker rejected daemon config: " + validation.stderr.strip())
        if original is not None:
            backup = CONFIG.with_name(f"daemon.json.before-omv-recovery-{int(time.time())}")
            if backup.exists():
                raise RuntimeError("Refusing to overwrite existing Docker config backup")
            shutil.copy2(CONFIG, backup)
            os.chmod(backup, 0o600)
            os.chmod(temp, CONFIG.stat().st_mode & 0o777)
            print(f"Original Docker config backup: {backup}")
        else:
            os.chmod(temp, 0o644)
        os.replace(temp, CONFIG)
        # The documented reload avoids unnecessarily restarting containers.
        reload_result = subprocess.run(["systemctl", "reload", "docker"],
                                       capture_output=True, text=True)
        if reload_result.returncode:
            raise RuntimeError("Docker reload failed; check daemon.json and service logs: " +
                               reload_result.stderr.strip())
        print("Docker live-restore enabled via daemon reload; containers not intentionally restarted")
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.parse_args()
    if os.geteuid() != 0:
        parser.error("requires root")
    enable()
