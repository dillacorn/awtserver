# Tailscale HTTPS certificates

Export certificate files for applications that need file-mounted TLS instead of Tailscale Serve.

```bash
tailscale cert --cert-file cert.crt --key-file cert.key server.example-tailnet.ts.net
```

Replace the hostname with your actual Tailscale MagicDNS name. Keep the private key restricted, and mount certificate directories read-only in consuming containers.

`renew.sh` provides certificate renewal for configured services. Inspect its configured paths and dry-run behavior before enabling a systemd timer or other scheduler.

[Certificate mounts, ownership, renewal and legacy scheduling notes](OPERATIONS.md)
