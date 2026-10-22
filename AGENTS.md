# Repository instructions for awtserver

Applies to this repository, including `docker/` and OMV service documentation.

## Project and operational boundaries

- This repository focuses on a Debian Stable server managed through SSH/CLI, native services, and Docker Compose. It also retains notes and scripts for the existing OMV host. The repository is **not** a complete, authoritative image of any live server.
- Before any host-specific diagnosis or suggested change, establish the **current host**, actual container names, Compose project/service names, and relevant live paths from that host. Do not infer them from old output, another server, or the example repository.
- Treat source files, example Compose configuration, active Compose files, container state, and host files as distinct. A commit to `main` does **not** prove that the running server has changed, and applying a host change is a separate authorization.
- Preserve persistent Docker volumes, databases, configuration, secrets, filesystem ownership, networking, DNS, and backup data. Never replace, prune, reset, migrate, or delete live data based only on example paths; require appropriate host evidence, safety checks, and explicit permission for destructive operations.
- `docker/pihole/` documents Pi-hole, Quad9/DNS transport, Tailscale/DNS routing, profile management (`pihm`), and optional Arachnidium integrations. Preserve live DNS availability and profile separation; never assume container, network, or configuration names without checking.
- Updates sourced from `main` may be fetched by host-side installation/update helpers even without a GitHub Release. Document this distinction; do not assume adding a release tag alone deploys any code.
- The `install.sh` bootstrap and `awtserver_installer.py` manage **only** `/opt/awtserver` and `/usr/local/bin/awtserver`. Debian 12/OMV can install this **command only**; `awtserver.apply_guard` remains a separate hard stop for service/package/cron/storage writes outside disposable Debian 13 VMs. Never treat program installation as permission to modify the NAS.
- During update/uninstall, reject modified/foreign files and symlinks in the managed program directory; do not remove arbitrary data or change service configurations. Preserve full details in `docs/awtserver-cli.md`.
- Do not commit credentials, environment secrets, Tailscale auth data, private keys, passwords, database copies, or sensitive device-specific output.

## User-facing documentation

- Keep README files short and navigable: purpose, quick start or key facts, essential caveats, and links to deeper instructions. Do not turn a README into a debug transcript or accumulated incident log.
- **Shorten presentation, not retained context.** Never discard troubleshooting evidence, safety checks, compatibility boundaries, rollback instructions, service dependencies, or implementation decisions just to make a README smaller. Preserve substantive material in relevant reference documents and link it from the README and the context map below.
- Before modifying any service or writing advice about it, read the applicable `AGENTS.md` files and the relevant full operational references below. A short README is an index, **not** a complete source of technical context.
- When behavior, assumptions, or deployment facts change, update the detailed operational reference alongside the concise README. Mark old host observations as dated history; do not mistake them for current runtime evidence.
- Put deployment steps, safeguards, rollback procedures, and historical host evidence in purpose-specific reference files such as `OPERATIONS.md`, `SETUP.md`, and `NETWORKING.md`. Keep them complete and inspectable; do not discard critical constraints simply to reduce README length.
- Keep `AGENTS.md` for contributor/agent operational rules, not as a substitute for user-facing instructions.
- Present Debian Stable as the project's focused operating environment. Avoid claiming a validated production-ready installer where only examples or components exist.
- Historical OMV-specific scripts and docs remain constrained to their proven host. Do not retarget them to vanilla Debian by changing prose or assuming compatibility.

## Technical context map

The full operational guides remain available even when a service README is short. **Read the relevant sources before diagnosis, scripts, Compose edits, migrations, or GitHub issue work.** Existing deployment snapshots and legacy commands are not proof of present host state.

| Topic | Detailed sources |
| --- | --- |
| **awtserver quick navigation** | [Tailscale manual steps](docs/quick/remote-apps.md), [Android Auto Rules](docs/quick/android-auto.md), [Pi-hole DNS](docs/quick/dns.md), [CLI and TUI](docs/awtserver-cli.md); quick docs are human-readable summaries, not authoritative deployment configuration. Keep detailed host-specific safeguards in existing OPERATIONS/NETWORKING guides. |
| **Storage, SnapRAID and recovery prototypes** | [Storage/mergerfs guides](docs/quick/mergerfs.md), [SnapRAID AIO](docs/quick/snapraid.md), [USB restore](docs/quick/recovery-usb.md), [disk/SMTP alerts](docs/quick/alerts.md), [implementation gates](docs/IMPLEMENTATION.md). Backend modules: `awtserver_storage.py`, `awtserver_snapraid.py`, `awtserver_backup.py`, `awtserver_monitor.py`. Do not assert that previews install snapshots or activate schedules. OMV runtime data is not available without a fresh read-only probe. |
| **awtserver CLI prototype** | [VM-only CLI commands and restrictions](docs/awtserver-cli.md), [OMV feature map](docs/feature-map.md), [implementation and validation gates](docs/IMPLEMENTATION.md); `awtserver.py` contains experimental package profiles and declarative job state. `awtserver_cron.py` can synchronize only an owned `/etc/cron.d/awtserver` file on a VM under explicit guards; job enable alone does not activate cron. Production adoption, storage, network or OMV removal are not implemented. |
| **Debian build / server recovery** | [Inventory and historical transition plan](migration/debian/OPERATIONS.md), [restore requirements](migration/debian/restore-manifest.md), [Oct 20 host findings](migration/debian/host-findings-2026-10-20.md), [Oct 22 sanitized capability report](migration/debian/host-findings-2026-10-22.md), [OMV scheduled jobs and rsync audit](migration/debian/omv-schedules-2026-10-22.md), [Oct 22 read-only CLI live validation](migration/debian/omv-readonly-validation-2026-10-22.md), [unprivileged TUI + temp-write sandbox test limits](docs/host-sandbox-validation.md), [non-deployable schedule inventory](docs/examples/omv-schedules-2026-10-22.json) |
| **Docker services** | [Service index](docker/README.md), [historical Docker commands](docker/LEGACY-NOTES.md); inspect each service's Compose files and host runtime |
| **Pi-hole, DNS and pihm** | [Local instructions](docker/pihole/AGENTS.md), [full operational notes](docker/pihole/OPERATIONS.md), [setup](docker/pihole/SETUP.md), [networking](docker/pihole/NETWORKING.md), [DNS recovery](docker/pihole/DNS-RECOVERY.md) |
| **Seerr / Jellyseerr** | [Migration guards, historical paths and rollback](docker/seerr/OPERATIONS.md) |
| **Watchtower** | [Updater scope, verifier, tests and recovery limitations](docker/watchtower/OPERATIONS.md) |
| **Docker Engine APT recovery** | [APT hook, install and failure-mode details](docker/engine-upgrade-recovery/OPERATIONS.md) |
| **Tailscale certificates** | [Renewal and certificate-mount procedures](docker/tailscale-certs/OPERATIONS.md) |
| **Navidrome** | [Storage paths, access and network overlays](docker/navidrome/OPERATIONS.md) |
| **Arachnidium** | [Proxy network, profiles and CA security](docker/arachnidium/OPERATIONS.md) |

- Files under `migration/debian/` and some service references describe the **existing OMV host** for evidence/recovery. Preserve them as history and do not treat OMV-specific scripts, old repository URLs, or `/docker/...` paths as portable Debian instructions.
- Prefer the relevant service's `OPERATIONS.md` for detailed procedures and `AGENTS.md` for constraints. Do not duplicate long procedures into top-level READMEs or delete the only copy of a safeguard.
## Merge and release authorization

Operate autonomously within the user's approved scope; do not add needless approval checkpoints.

- Implementation, investigation, fixes, tests, branches, and ordinary review PRs are not implicit authorization to merge, tag, or publish.
- A clear request to merge, commit/apply directly to `main`, tag, or publish authorizes the named operation for the specified work. An approved release includes its necessary scoped merge unless the user specifies a different target or restriction; do not ask for the same approval twice.
- An authorized but **unfinished** merge/release remains authorized through related small fixes, adjustments, tests, and interruptions. If the user pauses the release to correct a defect, an unambiguous "good to go", "working, continue", "looks good", or equivalent can resume the **same previously approved** operation. A pause ("wait"/"hold off") must be respected until the user signals continuation.
- The approval is **consumed when that operation finishes**. After a release has been published, fixing another issue or hearing "perfect"/"that works" does not authorize a follow-up merge or release. A new release requires a new authorization, even for a fix to the previous one.
- Stop and clarify when authorization is genuinely unclear, explicitly withdrawn, or when the scope, release target, or version materially changes. Do not invent an approval merely because CI passed, a prior release happened, or publishing would be convenient.
- A user can expressly approve releasing without manual runtime testing. Run reasonable available static/CI checks and report what was actually validated; do not misrepresent missing runtime testing or ignore significant failing checks.
- Preparing release notes, identifying a proposed version, writing code, and opening a feature PR are not themselves publication. Creating or triggering release-publishing workflows, one-use GitHub Actions release bridges, Git tags, Releases, uploads, or other publication requires an active approval for that specific release.
- Preserve any stricter project-specific permissions for deployments, package publication, destructive changes, and external infrastructure. A GitHub Release authorization does not inherently approve deployment, package publication, or replacing production data.

## Validation and release readiness

- Inspect the actual modified files and validate shell/Python/Compose syntax with appropriate available tools. Do not claim a real host integration test on the basis of static repository checks.
- No GitHub Release need be created for routine repository changes. If the user later requests releases, first verify existing tags/versions, precisely identify what is included, and link relevant setup/update documentation; only then publish within the explicit approved scope.
- Keep changes to remote installation/deployment, container restarts, database writes, network/DNS reconfiguration, and host updates separate from ordinary repository edits unless expressly authorized.
