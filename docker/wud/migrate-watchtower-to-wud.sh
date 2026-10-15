#!/usr/bin/env bash
# Replace Watchtower with WUD without touching application, DNS, or Tailscale containers.
set -euo pipefail
printf '\n[WUD 1/6] Checking host, Docker, Watchtower, and DNS...\n'
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ ${EUID} == 0 ]] || fail "Run as root"
[[ "$(hostname)" == openmediavault ]] || fail "Not the expected OMV host"
[[ -f /docker/watchtower/compose.yml ]] || fail "Missing Watchtower Compose"
command -v docker >/dev/null || fail "Docker is missing"
command -v curl >/dev/null || fail "curl is missing"
command -v python3 >/dev/null || fail "Python 3 is missing"
docker compose version >/dev/null || fail "Docker Compose plugin is missing"
[[ "$(docker inspect -f '{{.State.Running}}' watchtower)" == true ]] || fail "Watchtower is not running"
for name in pihole dnsproxy-quad9 nginx-pihole; do
  [[ "$(docker inspect -f '{{.State.Running}}' "$name")" == true ]] ||
    fail "Critical DNS container $name is not running"
done
if docker container inspect wud >/dev/null 2>&1; then
  fail "Existing WUD container detected; aborting rather than overwriting"
fi
[[ ! -e /docker/wud/compose.yml && ! -e /docker/wud/.env ]] ||
  fail "Existing WUD files detected; inspect /docker/wud before migration"
now="$(date '+%H%M')"
if [[ "$now" > 0234 && "$now" < 0310 ]]; then
  fail "Do not migrate within Watchtower's scheduled update window"
fi

# Inspects actual running Watchtower identity, arguments, and competing wud.watch labels.
python3 - <<'PY'
import json, subprocess, sys
w = json.loads(subprocess.check_output(["docker", "inspect", "watchtower"]))[0]
labels = w["Config"].get("Labels") or {}
if labels.get("com.docker.compose.service") != "watchtower" or labels.get("com.docker.compose.project.working_dir") != "/docker/watchtower":
    sys.exit("ERROR: Live Watchtower Compose identity/path does not match")
cmd = w["Config"].get("Cmd") or []
expected = "brave tailscale-brave app-flame tailscale-flame mumble-web nginx-mumbleweb freshrss tailscale-freshrss app-ntfy tailscale-ntfy hbbs hbbr vaultwarden nginx-vaultwarden jellyfin tailscale-jellyfin navidrome tailscale-navidrome jellyseerr mariadb_jellyseerr tailscale-jellyseerr gluetun transmission mullvad-browser audiobookshelf tailscale-audiobookshelf app-dockge tailscale-dockge".split()
if cmd[:3] != ["--schedule", "0 45 2 * * *", "watchtower"] or cmd[3:] != expected:
    sys.exit("ERROR: Live Watchtower command does not match reviewed 28-container allowlist")
ids = subprocess.check_output(["docker", "ps", "-aq"], text=True).split()
if ids:
    for item in json.loads(subprocess.check_output(["docker", "inspect", *ids])):
        other_name = (item.get("Name") or "").lstrip("/")
        other_labels = item.get("Config", {}).get("Labels") or {}
        if other_labels.get("wud.watch", "").lower() == "true" and other_name not in expected:
            sys.exit(f"ERROR: {other_name} has wud.watch=true overriding the safe allowlist")
print(f"Verified Watchtower project {labels.get('com.docker.compose.project')}: {len(expected)} allowed application names")
PY

printf '[WUD 2/6] Downloading replacement Compose over IPv4 (35-second deadline)...\n'
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
ref="${WUD_SOURCE_REF:-main}"
curl -4 -fLSs --connect-timeout 8 --max-time 35 --retry 1 --retry-delay 1 \
  --resolve raw.githubusercontent.com:443:185.199.108.133 \
  "https://raw.githubusercontent.com/dillacorn/omv-remote-dots/${ref}/docker/wud/compose_example.yml" \
  -o "$tmp/compose.yml"
[[ -s "$tmp/compose.yml" ]] || fail "Unable to download WUD Compose"

printf '[WUD 3/6] Preparing private configuration and SMTP import...\n'
umask 077
install -d -m 0700 /docker/wud /docker/wud/store
install -m 0644 "$tmp/compose.yml" /docker/wud/compose.yml

# Read only from the *running* container environment. Never print SMTP secrets.
python3 - <<'PY'
from pathlib import Path
import json, re, subprocess, sys
w = json.loads(subprocess.check_output(["docker", "inspect", "watchtower"]))[0]
env = dict(item.split("=", 1) for item in w["Config"]["Env"] if "=" in item)
mapping = {
    "WUD_SMTP_FROM": "WATCHTOWER_NOTIFICATION_EMAIL_FROM",
    "WUD_SMTP_TO": "WATCHTOWER_NOTIFICATION_EMAIL_TO",
    "WUD_SMTP_HOST": "WATCHTOWER_NOTIFICATION_EMAIL_SERVER",
    "WUD_SMTP_PORT": "WATCHTOWER_NOTIFICATION_EMAIL_SERVER_PORT",
    "WUD_SMTP_USER": "WATCHTOWER_NOTIFICATION_EMAIL_SERVER_USER",
    "WUD_SMTP_PASS": "WATCHTOWER_NOTIFICATION_EMAIL_SERVER_PASSWORD",
}
for src in mapping.values():
    val = env.get(src, "")
    if not val or any(c in val for c in "'\r\n\\"):
        sys.exit(f"ERROR: Missing/unsupported existing Watchtower SMTP field: {src}")
allowed = w["Config"]["Cmd"][3:]
if any(not re.fullmatch(r"[A-Za-z0-9_-]+", n) for n in allowed):
    sys.exit("ERROR: Unexpected target name")
pattern = "^(?:" + "|".join(re.escape(n) for n in allowed) + ")$"
if any(re.fullmatch(pattern, n) for n in ("pihole","dnsproxy-quad9","nginx-pihole","watchtower","wud")):
    sys.exit("ERROR: DNS/update infrastructure selected")
lines = ["COMPOSE_FILE='compose.yml'", "WUD_WATCHER_LOCAL_INCLUDE='" + pattern + "'"]
lines += [key + "='" + env[src] + "'" for key, src in mapping.items()]
path = Path("/docker/wud/.env")
with path.open("x") as fh:
    fh.write("\n".join(lines) + "\n")
path.chmod(0o600)
print("Private SMTP settings imported to /docker/wud/.env without displaying secrets")
PY

# Validate/pull WUD while Watchtower is still alive.
printf '[WUD 4/6] Validating Compose and downloading WUD image; Docker pull progress will appear...\n'
(cd /docker/wud && docker compose config --quiet && docker compose pull wud)

stamp="$(date '+%Y%m%d-%H%M%S')"
backup="/docker/watchtower/compose.yml.before-wud-${stamp}"
install -m 0600 /docker/watchtower/compose.yml "$backup"
dns_before="$(docker inspect -f '{{.Id}} {{.State.Running}}' pihole dnsproxy-quad9 nginx-pihole)"
switch_started=0
switch_ok=0
recover() {
  code=$?
  trap - EXIT
  if [[ "$switch_started" == 1 && "$switch_ok" == 0 ]]; then
    echo "Cutover failed. Attempting to restore Watchtower..." >&2
    if docker container inspect wud >/dev/null 2>&1; then
      docker rm -f wud >/dev/null 2>&1 || true
    fi
    (cd /docker/watchtower && docker compose -f compose.yml up -d --no-deps watchtower) ||
      printf 'CRITICAL: Restore Watchtower manually from %s\n' "$backup" >&2
  fi
  exit "$code"
}
trap recover EXIT

printf '[WUD 5/6] Switching Watchtower to WUD (rollback armed)...\n'
switch_started=1
docker update --restart=no watchtower >/dev/null
docker stop --time 30 watchtower >/dev/null
docker rm watchtower >/dev/null
(cd /docker/wud && docker compose up -d --no-deps wud)
sleep 8
[[ "$(docker inspect -f '{{.State.Running}}' wud)" == true ]] || fail "WUD did not remain running"
if docker container inspect watchtower >/dev/null 2>&1; then
  fail "Watchtower still exists after cutover"
fi

python3 - <<'PY'
import json, subprocess, sys
w = json.loads(subprocess.check_output(["docker", "inspect", "wud"]))[0]
env = dict(item.split("=", 1) for item in w["Config"]["Env"] if "=" in item)
expected = {
    "WUD_SERVER_ENABLED": "false",
    "WUD_WATCHER_LOCAL_CRON": "45 2 * * *",
    "WUD_WATCHER_LOCAL_WATCHATSTART": "false",
    "WUD_WATCHER_LOCAL_WATCHEVENTS": "false",
    "WUD_TRIGGER_DOCKER_UPDATES_AUTO": "true",
    "WUD_TRIGGER_DOCKER_UPDATES_ROLLBACK": "true",
    "WUD_TRIGGER_DOCKER_UPDATES_SELFUPDATE": "false",
    "WUD_TRIGGER_SMTP_LEGACY_AUTO": "true",
}
for key, value in expected.items():
    if env.get(key, "").lower() != value.lower():
        sys.exit(f"ERROR: Running WUD config mismatch: {key}")
if not env.get("WUD_TRIGGER_SMTP_LEGACY_PASS") or not env.get("WUD_WATCHER_LOCAL_INCLUDE"):
    sys.exit("ERROR: Missing private SMTP password or update allowlist")
print("WUD settings verified: 02:45 schedule, automatic updates, rollback, SMTP, HTTP disabled")
PY

[[ "$dns_before" == "$(docker inspect -f '{{.Id}} {{.State.Running}}' pihole dnsproxy-quad9 nginx-pihole)" ]] ||
  fail "DNS container state changed unexpectedly"
printf '[WUD 6/6] WUD is running; DNS identities verified.\n'
switch_ok=1
trap - EXIT

printf '\n===== MIGRATION SUCCEEDED =====\n'
docker ps --filter name=wud --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
printf 'Watchtower: stopped and container removed\nDNS containers: unchanged\n'
printf 'Automatic WUD updates: 02:45 America/New_York\n'
printf 'Email: configured, delivery not yet tested\n'
printf 'Previous Compose saved privately: %s\n' "$backup"
printf '\n===== WUD STARTUP LOGS =====\n'
docker logs --tail 40 wud 2>&1 |
  sed -E 's/(password|pass|token|secret)=[^[:space:]]+/\1=[REDACTED]/Ig'
