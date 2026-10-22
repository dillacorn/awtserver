# Docker | First checks

1. Confirm host and intended Compose project; read the deployed Compose files and enabled overlays.
2. Identify persistent application data, environment secrets, volumes, and shared namespaces.
3. **The current OMV host uses Docker CE**, not Debian `docker.io`. On fresh Debian the intended parity path is Docker's official APT repository and Compose plugin; that installer is **not yet implemented**. Explicit `docker-debian` is a separate experimental alternative and never a silent migration choice. Follow [Docker's Debian documentation](https://docs.docker.com/engine/install/debian/) for provider compatibility and firewall considerations.
4. Test networking, app health, storage paths, and recovery after restart in a disposable VM.
5. Restore from backed-up Compose sources and application data, never from container names alone.

**Do not** automatically recreate running applications, prune volumes, remove networks or publish service ports.

Details: [Docker index](https://github.com/dillacorn/awtserver/blob/main/docker/README.md) · [recovery requirements](https://github.com/dillacorn/awtserver/blob/main/migration/debian/restore-manifest.md).
