# OMV | Temporary TUI and sandbox validation

Initial live Debian 12/OMV read-only test: **10/10 CLI checks passed** and 11 files compiled, without a permanent install.

## Next safe test

Run migration/debian/host_tui_sandbox_test.py from a **pinned development commit** as user **nobody**, with AWTSERVER_SANDBOX_TEST=1.

The runner:
- Confirms live-host mutating operations are blocked.
- Executes all unit tests, including real job-state writes, cron-file creation/update, and installer copies **only in newly created temporary directories**.
- Traverses every TUI menu with a fake curses screen: leaf actions, scrolling, Back, Quit, minimum terminal dimensions and error handling.
- Calls every safe TUI read-only backend on the actual OMV host.
- **Never launches gdu/ncdu** and never invokes the OS package manager, Docker changes, cron services, SnapRAID jobs, SMTP delivery or backup/restore actions.

## Boundaries

- Test writes remain under private temporary paths, not /etc, /opt, /var/lib/awtserver or mounted data volumes.
- In tests that call VM-protected routines, write authorization is mocked **only in memory** and the destination is a temporary path. The real OMV write gate remains intact.
- The temporary source checkout is removed by a shell trap; no command is permanently installed.
- Test execution is unprivileged. A root-only guard check can also be performed using the non-mutating apply_guard(True) function.
- A passing test is **not** validation of actual curses rendering in the user's terminal, disk tool interaction, cron activation, email delivery, privileged installation or backup integrity.
- Tests still perform small amounts of temporary disk I/O. Do not claim an absolute absence of risk for unreviewed code.

See migration/debian/omv-readonly-validation-2026-10-22.md for the previous integration test.
