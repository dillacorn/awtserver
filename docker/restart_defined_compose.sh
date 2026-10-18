#!/usr/bin/env bash
# restart_defined_compose.sh
# User-maintained list of directories containing Compose projects to restart.

set -euo pipefail

# Add one directory per Compose application you want to restart.
# Each directory should contain either docker-compose.yml or compose.yml.
COMPOSE_DIRS=(
  "/docker/jellyfin"
  "/docker/immich"
  "@active-seerr"
  "/docker/ntfy"
  "/docker/brave"
  "/docker/freshrss"
  "/docker/flame"
  "/docker/diun"
  "/docker/freshdock"
  "/docker/calibre"
  "/docker/karakeep"
  "/docker/privacy"
  "/docker/vaultwarden"
  "/docker/mumble"
  "/docker/homeassistant"
  # "/docker/app_name"
)

# The Seerr migration intentionally keeps the original Compose directory.
# Resolve the running service rather than assuming a new clean-install path.
restart_active_seerr() {
  local name image project dir paths file
  local -a found=() files=() cmd=()
  for name in seerr jellyseerr; do
    if docker inspect "$name" >/dev/null 2>&1; then
      image="$(docker inspect "$name" --format '{{.Config.Image}}')"
      if [[ "$(docker inspect "$name" --format '{{.State.Running}}')" == true &&
            "$image" == ghcr.io/seerr-team/seerr:* ]]; then
        found+=("$name")
      fi
    fi
  done
  if (("${#found[@]}" == 0)); then
    echo "Skipping Seerr: no running Seerr container."
    return 0
  fi
  if (("${#found[@]}" != 1)); then
    echo "Skipping Seerr: multiple running candidates." >&2
    return 1
  fi
  name=${found[0]}
  project="$(docker inspect "$name" --format '{{index .Config.Labels "com.docker.compose.project"}}')"
  dir="$(docker inspect "$name" --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}')"
  paths="$(docker inspect "$name" --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}')"
  if [[ -z "$project" || -z "$paths" || "$project" == '<no value>' || "$paths" == '<no value>' ]]; then
    echo "Skipping Seerr: missing Compose labels." >&2
    return 1
  fi
  if [[ "$dir" != /docker/seerr && "$dir" != /docker/jellyseerr ]]; then
    echo "Skipping Seerr: unexpected Compose working directory: $dir" >&2
    return 1
  fi
  IFS=, read -r -a files <<< "$paths"
  cmd=(docker compose --project-directory "$dir" -p "$project")
  for file in "${files[@]}"; do
    if [[ ! -f "$file" || "$(realpath "$(dirname "$file")")" != "$dir" ]]; then
      echo "Skipping Seerr: missing or unexpected Compose file: $file" >&2
      return 1
    fi
    cmd+=(-f "$file")
  done
  printf 'Restarting Seerr project %s in %s with %s active Compose file(s)\n' "$project" "$dir" "${#files[@]}"
  "${cmd[@]}" restart
}

for dir in "${COMPOSE_DIRS[@]}"; do
  if [[ "$dir" == "@active-seerr" ]]; then
    restart_active_seerr
    continue
  fi
  if [ ! -d "$dir" ]; then
    echo "Skipping $dir. Directory does not exist."
    continue
  fi

  cd "$dir"

  if [ -f docker-compose.yml ]; then
    echo "Restarting Compose project in $dir (docker-compose.yml)"
    docker compose restart
  elif [ -f compose.yml ]; then
    echo "Restarting Compose project in $dir (compose.yml)"
    docker compose -f compose.yml restart
  else
    echo "Skipping $dir. No compose file found."
  fi
done