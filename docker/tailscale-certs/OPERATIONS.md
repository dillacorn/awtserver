# Tailscale Cert Quick Command (enter your magic DNS address in command)

Generate the cert and key with fixed names (`cert.crt` / `cert.key`) in one step:

    tailscale cert --cert-file cert.crt --key-file cert.key YOUR-DOMAIN.ts.net

## (all-in-one) tailscale cert command with ownership fix (enter your magic DNS address in command)

    cd /docker/tailscale-certs && tailscale cert --cert-file cert.crt --key-file cert.key YOUR-DOMAIN.ts.net && chown 1000:1000 cert.crt cert.key && chmod 640 cert.crt cert.key


---

## Mounting Certs into Docker (guide)

When using the certs with Docker (e.g., Nginx), you must mount the directory where they are stored as an **absolute path on your host**:

    volumes:
      - /absolute/path/to/docker/tailscale-certs:/etc/nginx/certs:ro # absolute path

### Path Examples

| OS      | Example Path                                    |
|---------|-------------------------------------------------|
| Linux   | `/home/username/docker/tailscale-certs`         |
| Windows | `C:/Users/YourName/docker/tailscale-certs`      |

> Replace `/absolute/path/to/docker/tailscale-certs` with the actual full path where your certs are stored.

## Weekly exported certificate renewal on OpenMediaVault

For OMV servers using the exported certificate renewal script at `/docker/tailscale-certs/renew.sh`, configure a single **OMV Scheduled Tasks** entry:

- User: `root`; command: `bash /docker/tailscale-certs/renew.sh`.
- Enabled: yes; email notification: preserve the server's existing setting.
- Time of execution: **Weekly** (`@weekly`, Sunday midnight in cron).
- Renewal threshold: `RENEW_BEFORE_DAYS=35` in `renew.sh`.

The renewal script checks expiry at each run and only renews missing or soon-expiring certificates. Weekly checks provide more retry opportunities than monthly runs if renewal fails or the host is unavailable. They do not cause certificates to be reissued every week. `RESTART_NGINX` still controls whether Nginx is restarted when a certificate is actually renewed.

For an existing monthly OMV task, use the repository's `set-omv-renewal-weekly.py` to change the stored `conf.system.cron.job` record and regenerate OMV's managed cron file. It locates the existing task by its exact command, stops on unexpected task settings, and preserves its UUID, command, user, and email preference. The default mode is read-only:

```bash
python3 set-omv-renewal-weekly.py
python3 set-omv-renewal-weekly.py --apply
```

Before applying, it backs up `config.xml` and the OMV cron file under root-only `/root/omv-renewal-weekly-backups`. It runs `omv-confdbadm update conf.system.cron.job` and `omv-salt deploy run cron`, then verifies `@weekly` was generated. A failed verification attempts to restore the prior monthly task. This changes **only scheduling**, never renews certificates or restarts Docker containers. Do not edit `/etc/cron.d/openmediavault-userdefined` or OMV's generated task wrapper directly.

For the OMV web UI alternative, open **System → Scheduled Tasks**, edit the existing renewal task, select **Weekly**, then save and apply.

OMV's send-email setting routes command output to its configured mail recipient; it does not guarantee successful delivery. Confirm the mail system separately if email alerts are important.
