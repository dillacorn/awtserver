# Docker | First checks

1. Confirm host and intended Compose project; read the deployed Compose files and enabled overlays.
2. Identify persistent application data, environment secrets, volumes, and shared namespaces.
3. Select exactly one supported Docker package provider. The CLI prototype uses Debian's repository packages, not Docker's official repository.
4. Test networking, app health, storage paths, and recovery after restart in a disposable VM.
5. Restore from backed-up Compose sources and application data, never from container names alone.

**Do not** automatically recreate running applications, prune volumes, remove networks or publish service ports.

Details: [Docker index](../../docker/README.md) · [recovery requirements](../../migration/debian/restore-manifest.md).
