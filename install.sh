#!/usr/bin/env bash
# Install only the awtserver CLI. No packages, cron, Docker or disk edits.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
    printf 'Requires root; use: curl -fsSL https://raw.githubusercontent.com/dillacorn/awtserver/main/install.sh | sudo bash\n' >&2
    exit 1
fi

for tool in python3 curl mktemp; do
    command -v "$tool" >/dev/null || {
        printf 'Missing prerequisite: %s\n' "$tool" >&2
        exit 1
    }
done

workdir="$(mktemp -d /tmp/awtserver-bootstrap.XXXXXXXX)"
trap 'rm -rf -- "$workdir"' EXIT
chmod 700 "$workdir"

curl -fLsS --proto '=https' --tlsv1.2 \
    'https://api.github.com/repos/dillacorn/awtserver/commits/main' \
    -o "$workdir/commit.json"

revision="$(python3 - "$workdir/commit.json" <<'PY'
import json, re, sys
with open(sys.argv[1], encoding="utf-8") as f:
    value = json.load(f)["sha"]
if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
    raise SystemExit("Invalid GitHub revision")
print(value)
PY
)"

for file in awtserver.py awtserver_docs.py awtserver_installer.py; do
    curl -fLsS --proto '=https' --tlsv1.2 \
        "https://raw.githubusercontent.com/dillacorn/awtserver/${revision}/${file}" \
        -o "$workdir/$file"
done

python3 -B - "$workdir" <<'PY'
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, sys.argv[1])
import awtserver_installer

with tempfile.TemporaryDirectory(prefix="awtserver-checkout-") as temp:
    source, commit = awtserver_installer.fetch_main(Path(temp))
    awtserver_installer.install(source, revision=commit)
print("Installed awtserver command.")
print("Run: awtserver  |  sudo awtserver update  |  sudo awtserver uninstall")
PY
