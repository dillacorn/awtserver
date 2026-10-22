# Live OMV read-only CLI validation | 2026-10-22

**Evidence:** Operator-supplied terminal results from the existing Debian 12 / OMV host. Tested source was the pinned commit `74aac6262426c467f8d9c9600d17a045bc0d1571` from the development branch. This report records outcomes only; no host IP addresses, disk IDs, mount paths or private command bodies.

## Method

- Downloaded the pinned GitHub source tarball into a temporary `/tmp` directory, with cleanup trap.
- Compiled Python source in memory using `compile()`; no bytecode files were generated.
- Launched CLI checks as the unprivileged `nobody` user with `python3 -B` and no `--apply` or `--confirm-vm`.
- **No permanent awtserver installation**, APT changes, cron activation, Docker operations, SnapRAID runs, mount writes or service restarts.

## Observed results

| Check | Operator result |
| --- | --- |
| Python syntax | 11 Python files passed |
| CLI integration | **10 / 10 passed** |
| Doctor | OMV detected, unsupported write target |
| Package profiles and plans | Passed |
| lsblk inspection | Six top-level block devices |
| mergerfs mount discovery | One pool |
| Disk utilization | Seven mounts; zero capacity warnings; zero inspection errors |
| Host stats | Passed |
| Historical schedules | Five enabled historical jobs; two possible timing gaps |
| Saved job-state read | Passed |
| Tailscale offline guide | Passed |

## Limits and next checks

- This is a **real Debian 12 OMV read-only CLI compatibility result**, not a full TUI terminal-interaction test.
- It does **not** prove package installation, privileged cron writes, email delivery, disk changes, SnapRAID sync/scrub, backup restore, real Docker networking, or OMV migration safety.
- Historical schedule output comes from the committed sanitized sample, **not live OMV cron parsing**.
- No near-full warning was seen **for the seven mounts measured**; this does not prove every data disk is healthy or independently backed up.
- Next low-risk exercise: temporary unprivileged interactive TUI over SSH, recording navigation, narrow-terminal behavior and visibility of storage/status screens. Keep all write operations VM-only.

This evidence can support read-only adoption planning but does not authorize a host installation, service change or merge.
