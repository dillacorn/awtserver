#!/usr/bin/env python3
"""Print a focused migration review from an existing PRIVATE inventory JSON.

Does not run host commands, make connections, change services or copy secrets.
By default, shows selected private infrastructure metadata (service names and
paths) on stdout for sharing in a PRIVATE support conversation. Never publish
its output in public GitHub issues or other public resources.
"""
import argparse
import json
from pathlib import Path
import sys

HOME = Path("/root/debian-migration-inventory")
HOST = "openmediavault"


def checked_path(raw):
    p = Path(raw)
    if not p.is_absolute() or p.is_symlink():
        raise ValueError("Inventory path must be absolute and not a symlink")
    resolved = p.resolve(strict=True)
    if not resolved.is_relative_to(HOME) or resolved.name != "inventory.json":
        raise ValueError("Inventory must be under /root/debian-migration-inventory")
    if not resolved.is_file():
        raise ValueError("Inventory is not a regular file")
    return resolved


def newest_report():
    try:
        paths = [
            p for p in HOME.glob("*/inventory.json")
            if p.is_file() and not p.is_symlink()
        ]
        if not paths:
            raise ValueError("No existing inventory found")
        return checked_path(max(paths, key=lambda p: p.parent.name))
    except OSError:
        raise ValueError("Cannot discover private inventory") from None


def fmt(value, default="-"):
    if value is None or value == "" or value == []:
        return default
    return str(value)


def emit_review(data):
    if data.get("schema") != 1 or data.get("identity", {}).get("hostname") != HOST:
        raise ValueError("Unknown inventory schema or host")

    output = []
    def line(value=""):
        output.append(str(value))
    def heading(name):
        line()
        line("===== " + name + " =====")

    ident = data.get("identity") or {}
    storage = data.get("storage") or {}
    host = data.get("host_features") or {}
    services = host.get("systemd") or {}
    dock = data.get("docker") or {}
    shares = host.get("shares") or {}
    network = data.get("network") or {}
    fail2ban = host.get("fail2ban") or {}

    line("PRIVATE DEBIAN MIGRATION REVIEW - NO CHANGES")
    line("Host: " + HOST)
    line("Captured UTC: " + fmt(data.get("collected_at_utc")))
    line("OS: " + fmt((ident.get("os_release") or {}).get("PRETTY_NAME")))
    line("Boot mode: " + fmt(ident.get("boot_mode")))

    heading("NON-DOCKER SERVICES")
    status = host.get("status") or {}
    for name, state in sorted(status.items()):
        line(f"{name}: enabled={bool(state.get('enabled'))} running={bool(state.get('running'))}")
    line("Enabled systemd units:")
    for name in sorted(services.get("enabled_units") or []):
        line("  " + name)
    line("Systemd timer unit names: " +
         ", ".join(services.get("timers") or []))
    line("Local systemd unit files: " +
         ", ".join(services.get("local_unit_file_names") or []))

    heading("FAIL2BAN / SSH")
    for jail in fail2ban.get("active_jails") or []:
        line("Jail " + fmt(jail.get("name")) + ": " +
             json.dumps(jail.get("counts") or {}, sort_keys=True))
    line("Fail2ban jail.d filenames: " +
         ", ".join(fail2ban.get("jail_directory_names_only") or []))
    line("Fail2ban custom filters: " +
         ", ".join(fail2ban.get("filter_directory_names_only") or []))
    line("Fail2ban jail.local exists: " +
         str(bool(fail2ban.get("jail_local_exists"))))
    ssh = host.get("sshd") or {}
    for name, value in sorted((ssh.get("effective_allowlisted_settings") or {}).items()):
        # No authorized_keys contents, authentication credentials or raw key bytes.
        line(f"SSHD {name}: {', '.join(str(v) for v in value)}")

    heading("STORAGE / BOOT")
    def disk_walk(nodes, prefix=""):
        for device in nodes or []:
            mp = device.get("mountpoints") or []
            line("  " + prefix + fmt(device.get("name")) + " | " +
                 fmt(device.get("type")) + " | " + fmt(device.get("size")) +
                 " bytes | fs=" + fmt(device.get("fstype")) +
                 " | mount=" + ",".join(str(p) for p in mp if p))
            disk_walk(device.get("children"), prefix + "  ")
    disk_walk((storage.get("block_devices") or {}).get("blockdevices"))
    line("fstab entries (credential options redacted by collector):")
    for entry in storage.get("fstab_safe_fields_only") or []:
        source = str(entry.get("source", ""))
        if not source.startswith(("UUID=", "PARTUUID=", "LABEL=", "/dev/")):
            source = "[network-or-other-source-redacted]"
        line("  " + fmt(entry.get("target")) + " <- " + source +
             " type=" + fmt(entry.get("fstype")) +
             " redacted_options=" + str(entry.get("other_options_redacted", 0)))
    line("Active mergerfs mountpoints:")
    def visit_mounts(nodes):
        for item in nodes or []:
            kind = str(item.get("fstype") or "")
            if kind == "fuse.mergerfs" or kind == "mergerfs":
                line("  " + fmt(item.get("target")) + " (sources recorded privately)")
            visit_mounts(item.get("children"))
    visit_mounts((storage.get("mounts") or {}).get("filesystems"))
    snap = storage.get("snapraid") or {}
    line("SnapRAID directives:")
    for d in snap.get("directives") or []:
        values = d.get("values") or []
        # Only migration-relevant paths/counts; no literal include/exclude
        # globs in terminal output; the JSON retains full directives.
        kind = d.get("directive")
        if kind in ("disk", "content", "parity", "2-parity", "3-parity"):
            line("  " + fmt(kind) + ": " + " ".join(str(v) for v in values))
        elif kind in ("exclude", "include"):
            continue
    line("SnapRAID exclusion/include directives retained privately: " +
         str(sum(d.get("directive") in ("exclude", "include")
                 for d in snap.get("directives") or [])))
    line("SnapRAID status: " +
         "; ".join(snap.get("status_summary") or []))

    heading("SHARES / UPS / MAIL")
    line("Samba shares (names and paths only):")
    for share in shares.get("samba") or []:
        line("  " + fmt(share.get("name")) + " -> " + fmt(share.get("path")))
    line("NFS exports: " + str(len(shares.get("nfs") or [])))
    ups = host.get("ups") or {}
    line("APC UPS:")
    for entry in ups.get("apcaccess_status_and_charge_only") or []:
        line("  " + str(entry).strip())
    line("NUT UPS names: " + ", ".join(ups.get("nut_ups_names") or []))
    mail = host.get("mail") or {}
    line("Mail programs: " +
         ", ".join(mail.get("installed_mail_executables") or []))
    line("Postfix config filenames: " +
         ", ".join(mail.get("postfix_filenames") or []))

    heading("FIREWALL / NETWORK (IP ADDRESS VALUES OMITTED)")
    nft = (network.get("firewall") or {}).get("nft_tables_only") or []
    line("nft table declarations: " + ", ".join(nft))
    line("iptables rule count: " +
         str((network.get("firewall") or {}).get("iptables_rules_count", 0)))
    line("ufw status header: " + ", ".join(
        (network.get("firewall") or {}).get("ufw_status_header") or []))
    ip = network.get("addresses") or []
    if isinstance(ip, list):
        line("Interfaces: " + ", ".join(
            fmt(n.get("ifname")) for n in ip if isinstance(n, dict)))
    ts = network.get("tailscale") or {}
    line("Tailscale state: " + fmt(ts.get("state")))
    line("Tailscale peer count: " + fmt(ts.get("peer_count")))

    heading("DOCKER COMPOSE PROVENANCE")
    containers = dock.get("containers") or []
    line(f"Containers: {len(containers)} | named volumes: " +
         str(len(dock.get("volume_names") or [])))
    line("Version: " + fmt(dock.get("docker_version")))
    line("Compose: " + fmt(dock.get("compose_version")))
    unknown = []
    for c in containers:
        name = fmt(c.get("name"))
        project = fmt(c.get("compose_project"))
        service = fmt(c.get("compose_service"))
        working = fmt(c.get("compose_working_dir"))
        source = fmt(c.get("compose_config_files"))
        if project == "-" or service == "-" or source == "-":
            unknown.append(name)
        # Identifies projects and their working source paths. Never dumps
        # env values, Docker inspect labels or private Compose contents.
        line(f"  {name} | {fmt(c.get('state'))} | {project}/{service} | " +
             f"dir={working} | config={source}")
    line("Missing Compose provenance: " +
         (", ".join(unknown) if unknown else "none"))
    line("Named volumes: " + ", ".join(dock.get("volume_names") or []))

    heading("ACCOUNTS / APT")
    users = (data.get("accounts") or {}).get("root_and_regular_users") or []
    for u in users:
        line(f"  {fmt(u.get('name'))} uid={fmt(u.get('uid'))} " +
             f"gid={fmt(u.get('gid'))} home={fmt(u.get('home'))}")
    pkgs = (data.get("packages") or {}).get("infrastructure") or []
    line("Infrastructure packages: " +
         ", ".join(fmt(pkg.get("package")) for pkg in pkgs))
    line("APT manual package count: " + str(len(
        (data.get("packages") or {}).get("manual_packages") or [])))

    heading("NOTES")
    line("This is a PRIVATE configuration inventory, not a data backup.")
    line("Credentials, key bodies, Docker env values and Compose file bodies omitted.")
    line("Do not copy this report into GitHub or another public channel.")
    return "\n".join(output) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path,
                        help="existing inventory.json; default is newest private one")
    args = parser.parse_args()
    try:
        file = checked_path(args.inventory) if args.inventory else newest_report()
        with file.open(encoding="utf-8") as source:
            data = json.load(source)
        sys.stdout.write(emit_review(data))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as err:
        print("STOP: Could not read/validate private inventory: " +
              str(err), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
