#!/usr/bin/env bash
# Stage WUD beside the live Watchtower. Does NOT stop or recreate Watchtower,
# Pi-hole, dnsproxy, Tailscale, or any monitored application.
set -euo pipefail

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || fail "Run as root on OMV"
[[ "$(hostname)" == openmediavault ]] || fail "Wrong host"
[[ -f /docker/watchtower/compose.yml ]] || fail "Missing live Watchtower Compose"
command -v docker >/dev/null || fail "Docker not installed"
command -v curl >/dev/null || fail "curl not installed"
command -v python3 >/dev/null || fail "Python 3 not installed"
docker compose version >/dev/null || fail "Docker Compose plugin unavailable"

[[ "$(docker inspect -f '{{.State.Running}}' watchtower)" == true ]] ||
  fail "Watchtower is not running"
for dns in pihole dnsproxy-quad9 nginx-pihole; do
  [[ "$(docker inspect -f '{{.State.Running}}' "$dns")" == true ]] ||
    fail "DNS service $dns is not running; refusing to continue"
done
if docker container inspect wud >/dev/null 2>&1; then
  fail "A container named wud already exists"
fi
if [[ -e /docker/wud/compose.yml || -e /docker/wud/.env ]]; then
  fail "Existing WUD configuration detected: refusing to overwrite"
fi

# Inspect the actual running Watchtower, not just a repository example.
python3 - <<'PY'
import json, subprocess, sys
w = json.loads(subprocess.check_output(["docker", "inspect", "watchtower"]))[0]
labels = w["Config"].get("Labels") or {}
project = labels.get("com.docker.compose.project")
service = labels.get("com.docker.compose.service")
directory = labels.get("com.docker.compose.project.working_dir")
if service != "watchtower" or directory != "/docker/watchtower":
    sys.exit("ERROR: Live Compose identity/path differs; refusing migration")
cmd = w["Config"]["Cmd"] or []
expected = "brave tailscale-brave app-flame tailscale-flame mumble-web nginx-mumbleweb freshrss tailscale-freshrss app-ntfy tailscale-ntfy hbbs hbbr vaultwarden nginx-vaultwarden jellyfin tailscale-jellyfin navidrome tailscale-navidrome jellyseerr mariadb_jellyseerr tailscale-jellyseerr gluetun transmission mullvad-browser audiobookshelf tailscale-audiobookshelf app-dockge tailscale-dockge".split()
if cmd[:3] != ["--schedule", "0 45 2 * * *", "watchtower"] or cmd[3:] != expected:
    sys.exit("ERROR: Running Watchtower arguments differ from reviewed allowlist; refusing migration")
if not project:
    sys.exit("ERROR: Missing Watchtower Compose project label")
print(f"Verified: host={subprocess.check_output(['hostname'], text=True).strip()}, project={project}, service={service}")
print(f"Verified: {len(expected)} monitored applications, cron=02:45 daily, DNS excluded")
PY

ref="${WUD_SOURCE_REF:-feat/wud-watchtower-migration}"
base="https://raw.githubusercontent.com/dillacorn/omv-remote-dots/${ref}/docker/wud"
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
curl -fLsS --retry 2 "$base/compose_example.yml" -o "$tmp/compose.yml"
curl -fLsS --retry 2 "$base/compose.updates.yml" -o "$tmp/compose.updates.yml"
[[ -s "$tmp/compose.yml" && -s "$tmp/compose.updates.yml" ]] ||
  fail "Failed downloading WUD files"

umask 077
install -d -m 0700 /docker/wud
install -d -m 0700 /docker/wud/store
install -m 0644 "$tmp/compose.yml" /docker/wud/compose.yml
install -m 0644 "$tmp/compose.updates.yml" /docker/wud/compose.updates.yml

# Extract the pre-existing private SMTP credentials without printing them.
# Python standard library only: the user's legacy Compose uses list-style
# KEY=value entries, so there is no dependency on PyYAML on the server.
python3 - <<'PY'
from pathlib import Path
import json, re, subprocess, sys

source = Path("/docker/watchtower/compose.yml").read_text()
values = {}
for line in source.splitlines():
    m = re.match(r"^\s*-\s*(WATCHTOWER_NOTIFICATION_EMAIL_[A-Z_]+)=(.*)\s*$", line)
    if m:
        values[m.group(1)] = m.group(2).strip().strip('"')
names = {
    "WUD_SMTP_FROM": "WATCHTOWER_NOTIFICATION_EMAIL_FROM",
    "WUD_SMTP_TO": "WATCHTOWER_NOTIFICATION_EMAIL_TO",
    "WUD_SMTP_HOST": "WATCHTOWER_NOTIFICATION_EMAIL_SERVER",
    "WUD_SMTP_PORT": "WATCHTOWER_NOTIFICATION_EMAIL_SERVER_PORT",
    "WUD_SMTP_USER": "WATCHTOWER_NOTIFICATION_EMAIL_SERVER_USER",
    "WUD_SMTP_PASS": "WATCHTOWER_NOTIFICATION_EMAIL_SERVER_PASSWORD",
}
for value_key, source_key in names.items():
    value = values.get(source_key, "")
    if not value or any(c in value for c in "'\r\n\\"):
        sys.exit(f"ERROR: Missing or unsupported legacy SMTP value: {source_key}")

w = json.loads(subprocess.check_output(["docker", "inspect", "watchtower"]))[0]
cmd = w["Config"]["Cmd"]
names_list = cmd[3:]
if any(not re.fullmatch(r"[A-Za-z0-9_-]+", x) for x in names_list):
    sys.exit("ERROR: Unexpected container name in Watchtower list")
pattern = "^(?:" + "|".join(re.escape(x) for x in names_list) + ")$"
if any(re.fullmatch(pattern, x) for x in ("pihole", "dnsproxy-quad9", "nginx-pihole", "watchtower", "wud")):
    sys.exit("ERROR: DNS/update infrastructure appears in WUD allowlist")
lines = ["COMPOSE_FILE='compose.yml'",
         "WUD_WATCHER_LOCAL_INCLUDE='" + pattern + "'"]
for target, source in names.items():
    lines.append(target + "='" + values[source] + "'")
path = Path("/docker/wud/.env")
with path.open("x") as stream:
    stream.write("\n".join(lines) + "\n")
path.chmod(0o600)
print("Created root-only local WUD .env (SMTP credentials not displayed)")
PY

(
  cd /docker/wud
  docker compose -f compose.yml config --quiet
  docker compose -f compose.yml up -d --no-deps wud
)

[[ "$(docker inspect -f '{{.State.Running}}' wud)" == true ]] ||
  fail "WUD did not start; Watchtower remains untouched"

printf '\n===== WUD STAGED (NO AUTO UPDATES) =====\n'
docker ps --filter 'name=^(wud|watchtower|pihole|dnsproxy-quad9)$' \
  --format 'table {{.Names}}\t{{.Status}}'
printf '\nCompose project: '
docker inspect wud --format '{{index .Config.Labels "com.docker.compose.project"}}'
printf 'Active WUD update trigger: absent\n'
printf 'Watchtower still active: true\n'
printf '\n===== WUD LOG (last 40 lines) =====\n'
docker logs --tail 40 wud 2>&1 |
  sed -E 's/(password|pass|token|secret)=[^[:space:]]+/\1=[REDACTED]/Ig'
printf '\nStage complete. DO NOT enable compose.updates.yml until review.\n'
