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
```

`tailscaled.state` excludes Tailscale's volatile identity/state file by filename
at any array depth. This is a **SnapRAID parity exclusion**, not a deletion
or exclusion from Docker backup creation. Do not remove existing backups or
identity files to address duplicate-copy detection errors. Add the rule in
OMV's live SnapRAID **Exclusions** settings separately; the GitHub example
does not change the host.
