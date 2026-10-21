# Navidrome

Dedicated music server for the existing OMV music library.

## Library

The Compose configuration mounts the existing music collection read-only:

```text
/srv/mergerfs/data/root/Music -> /music:ro
```

Navidrome stores its database and cache under `/docker/navidrome/data`.

## First start

Create the writable data directory for the configured Navidrome UID:GID, then start the stack:

```bash
cd /docker/navidrome
mkdir -p data ts/state
chown -R 1000:1000 data
docker compose up -d
```

If `NAVIDROME_UID` or `NAVIDROME_GID` is changed in `.env`, use the same numeric ownership for `data`.

## Access

Open the service using its Tailscale HTTPS address:

```text
https://navidrome.<your-tailnet>.ts.net
```

Example:

```text
https://navidrome.time-puffin.ts.net
```

On first access, Navidrome prompts for the initial administrator account.

## Export Tailscale certificate

Tailscale Serve handles HTTPS directly for remote tailnet access. File-based certificates are only needed for the repo's optional local Pi-hole/Nginx HTTPS path.

```bash
docker exec -it tailscale-navidrome tailscale cert navidrome.<your-tailnet>.ts.net
```

Example:

```bash
docker exec -it tailscale-navidrome tailscale cert navidrome.time-puffin.ts.net
```

The shared renewal script is also configured for Navidrome:

```bash
bash /docker/tailscale-certs/renew.sh --dry-run
bash /docker/tailscale-certs/renew.sh
```

## Optional LAN-only Pi-hole/Nginx path

Create the shared Docker network once if it does not already exist:

```bash
docker network inspect local-webapps >/dev/null 2>&1 ||
    docker network create local-webapps
```

Then start Navidrome with the overlay:

```bash
docker compose \
    -f compose.yml \
    -f compose.local-webapps.yml \
    up -d
```

The Pi-hole example routes `navidrome.example-tailnet.ts.net` to `tailscale-navidrome:4533` and mounts Navidrome's exported certificate directory into Nginx.
