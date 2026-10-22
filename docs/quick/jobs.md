# Scheduling | Jobs

1. Choose or write a *known, reviewed* script under the approved jobs directory, with a **non-root** execution account.
2. Add a five-field cron schedule with `awtserver jobs add`. New jobs start disabled.
3. Use `awtserver jobs enable` or `disable` to preview; add `--apply --confirm-vm` only on an authorized disposable Debian 13 VM.
4. Use `awtserver jobs render` to inspect the actual change.
5. **Separately** use `awtserver jobs sync --apply --confirm-vm` in the VM to install only awtserver's managed cron file. Confirm cron is running and examine logs.

Enabling desired state is **not** activation. Active cron has no built-in retry, overlap protection or email routing in this prototype.

Details: [CLI and cron safety](../awtserver-cli.md) · [development checklist](../IMPLEMENTATION.md).
