# Jellyfin: show Transmission completed downloads

## Purpose and boundaries

Add a **read-only** Jellyfin media path to the existing Transmission **completed** directory on mergerfs. This makes new media visible without moving it, modifying Transmission's download location, or disrupting seeding. The separate Jellyfin library is named **Downloads**. This is **not** an automatic organizer: Jellyfin can index files but will not move them into Movies/Shows or rename releases.

This document describes the inspected `openmediavault` host on **2026-10-29**. Repository examples and the live NAS may diverge. Do not use these exact paths on another machine until you verify its mounts and Compose project.

## Confirmed host state

| Item | Inspected value |
| --- | --- |
| Host | `openmediavault` (Debian 12 / OMV) |
| Compose project and service | `jellyfin` / `jellyfin` |
| Live Jellyfin configuration files, in order | `/docker/jellyfin/compose.yml`, `compose.override.yml`, `compose.freshdock.yml` |
| `.env` `COMPOSE_FILE` | No explicit entry observed |
| Transmission bind mount | `/srv/mergerfs/data/root/downloads:/downloads` |
| Transmission completion setting | `/downloads/transmission/complete` (inside Transmission) |
| Actual completed-downloads directory | `/srv/mergerfs/data/root/downloads/transmission/complete` |
| Filesystem under downloads | `fuse.mergerfs` |
| Additional Jellyfin bind mount | `/srv/mergerfs/data/root/downloads/transmission/complete:/data/Incoming:ro` |
| Jellyfin library name | `Downloads` |
| Jellyfin library directory | `/data/Incoming` |

The source directory existed. The user applied the new bind mount to the **existing live `compose.override.yml`**; the configuration validator reported only the requested mount changed. The Jellyfin service was recreated and reported **Started**. Docker inspection confirmed `/data/Incoming` mapped to the correct source with `RW: false`. Original override backup:

`/docker/jellyfin/compose.override.yml.backup.20261029-112001`

The user reported creating the Jellyfin library and chose the shorter name **Downloads**. The Jellyfin library type and a completed metadata scan were **not separately verified**. Existing Jellyfin Movies/Shows/Music and other mounts were retained. Transmission and Gluetun were not changed by the Jellyfin-only recreation.

## Reproduce this configuration on a comparable server

**1. Verify actual host/project and source first.** Do not rely on source templates or the historical values above.

```bash
hostname
docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}} / {{index .Config.Labels "com.docker.compose.service"}}' jellyfin
docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' jellyfin
docker inspect -f '{{range .Mounts}}{{println .Source "->" .Destination "read/write:" .RW}}{{end}}' transmission jellyfin
findmnt -T /srv/mergerfs/data/root/downloads -o TARGET,SOURCE,FSTYPE
test -d /srv/mergerfs/data/root/downloads/transmission/complete
```

**2. Add the mount once.** On the inspected host, edit `/docker/jellyfin/compose.override.yml`. Create a dated backup first. Under the **existing** `services: → jellyfin: → volumes:` list, append this entry (do not replace any existing volumes):

```yaml
      - /srv/mergerfs/data/root/downloads/transmission/complete:/data/Incoming:ro
```

For a clean Compose deployment, the same mount is available in the optional [`compose.downloads.yml`](compose.downloads.yml). That **overlay is not active on the inspected OMV host**; do **not** append it to that host's Compose file list because the mount is already in `compose.override.yml`. Use either the existing override or the optional overlay, **not both**.

**3. Validate the entire live Compose configuration.** From `/docker/jellyfin`, the confirmed file order on the inspected host was:

```bash
docker compose -f compose.yml -f compose.override.yml -f compose.freshdock.yml config --quiet
docker compose -f compose.yml -f compose.override.yml -f compose.freshdock.yml config --format json |
  python3 -c '
import json, sys
for volume in json.load(sys.stdin)["services"]["jellyfin"]["volumes"]:
    if volume.get("target") == "/data/Incoming":
        print(volume.get("source"), "->", volume.get("target"),
              "read_only:", volume.get("read_only"))
'
```

The effective Jellyfin volume must map to the verified source and have `read_only: true`. Do not inadvertently change networking, credentials, GPU devices, Tailscale, or other mounts. If using the optional overlay on a new install, append its `-f compose.downloads.yml` **after all existing live files**, and consistently use that same full list in future deployments.

**4. Apply Jellyfin only** after validating and backing up the existing configuration:

```bash
docker compose -f compose.yml -f compose.override.yml -f compose.freshdock.yml up -d --no-deps --no-build --pull never jellyfin
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data/Incoming"}}{{println .Source "->" .Destination "RW:" .RW}}{{end}}{{end}}' jellyfin
```

Expected output ends with `RW: false`. Recreating Jellyfin can briefly interrupt streaming; do not touch Transmission, Gluetun, or the Tailscale sidecar. For a clean-install overlay, include the additional `-f` in these commands.

**5. Add the Jellyfin library manually.** In the Jellyfin admin interface, go to **Dashboard → Libraries → Add Media Library**. Name it **Downloads**, select `/data/Incoming`, and start a scan. A *Mixed* library is convenient when downloads include both movies and shows, but Jellyfin warns that mixed-library metadata matching is less reliable. For accurate posters, genres and episode identification, use dedicated Movies or Shows libraries with proper file names. Do not add `/data/Incoming` to an existing Movies/Shows library unless that library's content matches.

**6. Verify:** Jellyfin can browse a completed file; Transmission still sees and can seed that file from its original location; Jellyfin's `/data/Incoming` mount remains read-only. Newly added files should be scanned or picked up by scheduled scans, depending on Jellyfin's library configuration and mergerfs change notifications.

## Limitations and safety

- Read-only protects the completed-download files from write operations through Jellyfin's `/data/Incoming` mount. It does not protect the same files if another application has a writable mount.
- Jellyfin only indexes files present under the completed directory. Changing Transmission's save location later requires updating the Jellyfin mount and library path.
- **Do not move or rename actively seeded content behind Transmission's back.** If manually organizing, update Transmission's file location (or stop seeding appropriately) and let Jellyfin rescan. No automatic move was configured.
- Jellyfin metadata and genre filtering depend on matching a title to an appropriate metadata record; unorganized mixed release names may be misidentified.
- Exposing this library in Jellyfin can expose newly downloaded content to other Jellyfin accounts. Review Jellyfin per-user library access before sharing it.

## Rollback

On the inspected host, the original override is `compose.override.yml.backup.20261029-112001`. Compare before restoring; a newer edit may have been made since the backup. Remove only the `/data/Incoming` mount from the live override (or restore that backup if appropriate), validate the **entire** Compose file set, and recreate **only** the Jellyfin service using the command above. Optionally remove the `Downloads` library **from Jellyfin's interface**, without deleting underlying media. Never use `docker compose down -v`, remove download files, or restart Transmission to roll back this read-only mount.

## Genre browsing

For an existing Movie or Shows library, Jellyfin's web UI provides a **Filter → Genres** control; no plugin is required for ordinary genre filtering. If the goal is Netflix-like home-page genre rows, an **optional third-party** [Genre Manager plugin](https://github.com/max-aumard/jellyfin-plugin-genre-manager) uses the additional Home Screen Sections plugin. Check compatibility with the **installed** Jellyfin server version before considering it; neither was installed as part of this download-mount change. Genre discovery may be less reliable in the mixed Downloads library.
