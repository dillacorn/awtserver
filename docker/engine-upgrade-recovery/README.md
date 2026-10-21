# Docker Engine upgrade recovery

An optional Debian APT hook and systemd timer for recovering containers unexpectedly stopped by Docker Engine/containerd package updates.

## Usage

From this directory, inspect before installing:

```bash
./install.sh --check
```

`./install.sh --apply` installs the safeguard; `--enable-live-restore` is an optional, separately reviewed Docker daemon setting.

**Scope:** Only containers that were running before the APT upgrade and still match their original identities. It does not recreate containers, change Compose stacks, repair unhealthy applications or run on manual `dpkg -i` updates.

[Installation, limitations, verification and recovery details](OPERATIONS.md)
