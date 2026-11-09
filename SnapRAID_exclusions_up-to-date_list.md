### example exclusions list - openmediavault SnapRAID

#### You may need to add/remove some lines.

```
/*.log
/cache/
/temp/
*.sqlite3-wal
*.sqlite-wal
/.cache/
*.cache
/.config/
.cache
.config
/*.db
/gen.php
*.db-wal
jellyfin.db-wal
gen.php
/*.metadata-v2
/*.sqlite
*wleabcEoxlt-eengsairo.sqlite
*.metadata-v2
pg_filenode.map
2840_vm
220062
tailscaled.log*.txt
tailscaled.state
compose.override.yml
/root/docker_week/immich/postgres/
```

`/root/docker_week/immich/postgres/` excludes Immich's live PostgreSQL directory
from parity, not from the filesystem or independent database backups. The
November 9, 2026 OMV AIO run completed sync and scrub after this exclusion;
the previously protected PostgreSQL files appeared as removed from parity,
not deleted from disk.

`tailscaled.state` excludes Tailscale's volatile identity/state file by filename
at any array depth. This is a **SnapRAID parity exclusion**, not a deletion
or exclusion from Docker backup creation. Do not remove existing backups or
identity files to address duplicate-copy detection errors. Add the rule in
OMV's live SnapRAID **Exclusions** settings separately; the GitHub example
does not change the host.
