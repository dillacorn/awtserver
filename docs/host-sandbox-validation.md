# OMV | Temporary TUI and sandbox validation

Initial live Debian 12/OMV read-only test: **10/10 CLI checks passed** and 11 files compiled, without a permanent install.

## First real OMV run (2026-10-22)

The operator ran the pinned temporary test with unprivileged sandbox writes. The production/root write guard **passed**; the suite executed 96 tests with **one test-fixture failure** in `test_real_host_rejected`. That test mocked Debian 13 and VM status but not the actual presence of `/etc/openmediavault`, and incorrectly expected the VM-specific error. The guard correctly rejected the OMV host instead. The runner stopped before checking real read-only TUI backends or launching the interactive menu. No server configuration changes were observed.

**Fix:** Isolated OMV detection in `omv_present()`, mocked absence only for the non-VM scenario, and added an explicit OMV-present regression test even when Debian 13 + VM are simulated. This retains the OMV write refusal; it does **not** relax it.

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
- Interactive gdu/ncdu launches are **never executed by the automated host smoke test**. For manual SSH navigation, launch the TUI with AWTSERVER_TUI_TEST_MODE=1; this blocks both disk-browser subprocesses regardless of installed packages. Independently, external disk-tool launch is blocked as root.
- Test execution is unprivileged. A root-only guard check can also be performed using the non-mutating apply_guard(True) function.
- A passing test is **not** validation of actual curses rendering in the user's terminal, disk tool interaction, cron activation, email delivery, privileged installation or backup integrity.
- Tests still perform small amounts of temporary disk I/O. Do not claim an absolute absence of risk for unreviewed code.

See migration/debian/omv-readonly-validation-2026-10-22.md for the previous integration test.
