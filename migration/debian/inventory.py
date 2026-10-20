#!/usr/bin/env python3
"""Read-only server inventory for future OMV -> Debian transition.

Only writes to a private /root folder. No mounts, services, containers,
packages, disks or firewall rules are changed. NO raw secret-bearing files,
Docker environment values, passwords, SSH keys or API keys are copied.
The report still contains private host metadata (IPs, paths, UUIDs, serials).
NEVER commit it to a public repository.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys

HOST = "openmediavault"
OUT = Path("/root/debian-migration-inventory")
CONFIG_PATHS = [
    "/etc/fstab", "/etc/snapraid.conf", "/etc/mergerfs",
    "/etc/ssh/sshd_config", "/etc/ssh/sshd_config.d",
    "/etc/fail2ban", "/etc/smartd.conf", "/etc/smartmontools",
    "/etc/samba/smb.conf", "/etc/exports", "/etc/exports.d",
    "/etc/apcupsd", "/etc/nut", "/etc/nftables.conf", "/etc/ufw",
    "/etc/network/interfaces", "/etc/network/interfaces.d",
    "/etc/NetworkManager/system-connections", "/etc/docker",
    "/etc/systemd/system", "/etc/cron.d", "/etc/cron.daily",
    "/etc/openmediavault", "/var/spool/cron/crontabs", "/docker", "/srv",
]
PKG_PREFIXES = (
    "openmediavault", "snapraid", "mergerfs", "docker", "containerd",
    "fail2ban", "openssh", "smartmontools", "cockpit", "ufw",
    "nftables", "iptables", "samba", "nfs-", "apcupsd", "nut-",
    "tailscale", "wireguard", "systemd-resolved", "network-manager",
    "avahi", "rsync", "restic", "borgbackup", "mailutils", "postfix",
    "msmtp", "cron", "logrotate", "hd-idle", "lvm2", "cryptsetup",
    "mdadm", "linux-image", "linux-headers", "unattended-upgrades",
)


def run(*args, timeout=30, limit=3000000):
    """Don't return stderr; tools may include credential values in errors."""
    if not shutil.which(args[0]):
        return ""
    try:
        p = subprocess.run(args, text=True, capture_output=True, timeout=timeout,
                           errors="replace", check=False)
        return p.stdout[:limit] if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def run_json(*args, **kwargs):
    try:
        return json.loads(run(*args, **kwargs))
    except (ValueError, TypeError):
        return None


def text(path, limit=150000):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def names(path):
    try:
        return sorted(p.name for p in Path(path).iterdir())[:500]
    except OSError:
        return []


def metadata(path):
    p = Path(path)
    try:
        st = p.lstat()
        return {"path": path, "type": "symlink" if p.is_symlink()
                else "directory" if p.is_dir() else "file",
                "mode": oct(stat.S_IMODE(st.st_mode)),
                "uid": st.st_uid, "gid": st.st_gid}
    except OSError:
        return {"path": path, "type": "missing"}


def fstab():
    rows = []
    for ln in text("/etc/fstab").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        fields = s.split()
        if len(fields) >= 4:
            options = fields[3].split(",")
            safe = {"ro", "rw", "nofail", "noauto", "defaults", "bind",
                    "noatime", "relatime", "x-systemd.automount"}
            rows.append({"source": fields[0], "target": fields[1],
                         "fstype": fields[2],
                         "safe_options": [o for o in options if o in safe],
                         "other_options_redacted": sum(o not in safe for o in options)})
    return rows


def snapraid():
    directives = []
    keys = {"disk", "content", "parity", "2-parity", "3-parity", "4-parity",
            "5-parity", "6-parity", "exclude", "include", "autosave", "block_size"}
    for ln in text("/etc/snapraid.conf").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        fields = s.split(maxsplit=2)
        if fields[0] in keys:
            directives.append({"directive": fields[0], "values": fields[1:]})
    status = run("snapraid", "status", timeout=45)
    status_lines = [line.strip() for line in status.splitlines()
                    if any(k in line for k in ("No sync is in progress",
                        "NOT fully synced", "WARNING!", "Scrubbed", "Unscrubbed"))]
    return {"directives": directives[:2000], "status_summary": status_lines[:100],
            "version": run("snapraid", "-V").splitlines()[:3]}


def systemd():
    enabled = run("systemctl", "list-unit-files", "--state=enabled",
                  "--no-legend", "--no-pager", timeout=45)
    running = run("systemctl", "list-units", "--type=service",
                  "--state=running", "--no-legend", "--no-pager", timeout=45)
    timers = run("systemctl", "list-timers", "--all", "--no-legend",
                 "--no-pager", timeout=45)
    suffixes = (".service", ".socket", ".timer", ".mount", ".automount", ".path")
    return {
        "enabled_units": [p[0] for line in enabled.splitlines()
                          if (p := line.split()) and p[0].endswith(suffixes)],
        "running_services": [p[0] for line in running.splitlines()
                             if (p := line.split()) and p[0].endswith(".service")],
        "timers": sorted(set(re.findall(r"[\w@.-]+\.timer", timers))),
        "local_unit_file_names": names("/etc/systemd/system"),
        "local_drop_in_directories": {
            p.name: names(str(p))
            for p in Path("/etc/systemd/system").glob("*.d") if p.is_dir()},
    }


def fail2ban():
    output = run("fail2ban-client", "status", timeout=15)
    matched = re.search(r"Jail list:\s*(.*)", output)
    active = [p.strip() for p in matched.group(1).split(",") if p.strip()] if matched else []
    jails = []
    for name in active[:100]:
        if not re.fullmatch(r"[-\w.]+", name):
            continue
        raw = run("fail2ban-client", "status", name, timeout=12)
        counts = {}
        for label in ("Currently banned", "Total banned", "Currently failed",
                      "Total failed"):
            m = re.search(re.escape(label) + r":\s*(\d+)", raw)
            if m:
                counts[label] = int(m.group(1))
        jails.append({"name": name, "counts": counts})
    return {
        "active_jails": jails,
        "jail_directory_names_only": names("/etc/fail2ban/jail.d"),
        "filter_directory_names_only": names("/etc/fail2ban/filter.d"),
        "action_directory_names_only": names("/etc/fail2ban/action.d"),
        "jail_local_exists": Path("/etc/fail2ban/jail.local").is_file(),
        "banned_ip_addresses_not_collected": True,
    }


def ssh():
    keys = {"port", "listenaddress", "passwordauthentication",
            "permitrootlogin", "pubkeyauthentication",
            "kbdinteractiveauthentication", "allowusers", "allowgroups",
            "authorizedkeysfile", "usepam", "allowtcpforwarding",
            "gatewayports", "x11forwarding"}
    settings = {}
    for ln in run("sshd", "-T", timeout=15).splitlines():
        k, _, v = ln.partition(" ")
        if k in keys:
            settings.setdefault(k, []).append(v)
    return {"effective_allowlisted_settings": settings,
            "drop_in_filenames": names("/etc/ssh/sshd_config.d"),
            "keys_and_credentials_not_collected": True}


def cron():
    tasks = []
    for ln in run("crontab", "-l", "-u", "root").splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or "=" in s.split()[0]:
            continue
        fields = s.split()
        if fields and fields[0].startswith("@"):
            tasks.append({"schedule": fields[0], "command": "REDACTED"})
        elif len(fields) >= 6:
            tasks.append({"schedule": " ".join(fields[:5]), "command": "REDACTED"})
    return {"root_crontab_schedules_only": tasks,
            "cron_d_filenames": names("/etc/cron.d"),
            "cron_daily_filenames": names("/etc/cron.daily"),
            "cron_weekly_filenames": names("/etc/cron.weekly"),
            "cron_monthly_filenames": names("/etc/cron.monthly")}


def services():
    units = ["ssh", "sshd", "fail2ban", "smartd", "smartmontools",
             "docker", "containerd", "cron", "ufw", "nftables", "smbd",
             "nfs-server", "nfs-kernel-server", "rpcbind", "apcupsd",
             "nut-server", "nut-monitor", "tailscaled",
             "systemd-resolved", "NetworkManager", "networking",
             "unattended-upgrades", "pihm-web"]
    enabled = set(systemd()["enabled_units"])
    running = set(systemd()["running_services"])
    return {name: {"enabled": name + ".service" in enabled,
                   "running": name + ".service" in running}
            for name in units}


def shares():
    smb = []
    current = ""
    for ln in text("/etc/samba/smb.conf").splitlines():
        s = ln.strip()
        if not s or s.startswith(("#", ";")):
            continue
        m = re.fullmatch(r"\[([^\]]+)\]", s)
        if m:
            current = m.group(1)
            if current != "global":
                smb.append({"name": current})
        elif current != "global" and smb:
            key, sep, val = s.partition("=")
            if sep and key.strip().lower() == "path":
                smb[-1]["path"] = val.strip()
    exports = []
    for p in [Path("/etc/exports"), *Path("/etc/exports.d").glob("*.exports")]:
        for ln in text(p).splitlines():
            parts = ln.strip().split()
            if parts and not parts[0].startswith("#"):
                exports.append({"file": str(p), "path": parts[0],
                                "client_rules": "REDACTED"})
    return {"samba": smb, "nfs": exports[:250]}


def docker():
    ids = run("docker", "ps", "-aq", timeout=35).split()
    rows = []
    for offset in range(0, len(ids), 20):
        inspected = run_json("docker", "inspect", *ids[offset:offset + 20], timeout=90)
        if not isinstance(inspected, list):
            continue
        for c in inspected:
            cfg, host = c.get("Config") or {}, c.get("HostConfig") or {}
            labels = cfg.get("Labels") or {}
            rows.append({
                "name": str(c.get("Name", "")).lstrip("/"),
                "image": cfg.get("Image"),
                "state": (c.get("State") or {}).get("Status"),
                "health": ((c.get("State") or {}).get("Health") or {}).get("Status"),
                "compose_project": labels.get("com.docker.compose.project"),
                "compose_service": labels.get("com.docker.compose.service"),
                "compose_working_dir": labels.get("com.docker.compose.project.working_dir"),
                "compose_config_files": labels.get("com.docker.compose.project.config_files"),
                "network_mode": host.get("NetworkMode"),
                "restart_policy": (host.get("RestartPolicy") or {}).get("Name"),
                "runtime_user": cfg.get("User"),
                "mounts": [
                    {"type": m.get("Type"), "source": m.get("Source"),
                     "destination": m.get("Destination"), "rw": m.get("RW")}
                    for m in c.get("Mounts") or []],
                "published_ports": host.get("PortBindings") or {},
                "networks": sorted(((c.get("NetworkSettings") or {})
                                    .get("Networks") or {}).keys()),
                "env_variable_NAMES_only": sorted(
                    entry.split("=", 1)[0] for entry in cfg.get("Env") or []
                    if "=" in entry),
            })
    return {
        "docker_version": run("docker", "version", "--format",
                              "{{.Server.Version}}").strip(),
        "compose_version": run("docker", "compose", "version").strip(),
        "containers": sorted(rows, key=lambda c: c["name"]),
        "volume_names": sorted(run("docker", "volume", "ls", "--format",
                                   "{{.Name}}").splitlines()),
        "no_secrets_or_environment_values_collected": True,
    }


def networking():
    ts = run_json("tailscale", "status", "--json", timeout=25)
    own = ts.get("Self") or {} if isinstance(ts, dict) else {}
    nft = run("nft", "list", "tables", timeout=15)
    return {
        "addresses": run_json("ip", "-j", "address", "show"),
        "routes_v4": run_json("ip", "-j", "route", "show"),
        "routes_v6": run_json("ip", "-6", "-j", "route", "show"),
        "tailscale": {"state": ts.get("BackendState") if isinstance(ts, dict) else None,
                      "dns_name": own.get("DNSName"),
                      "ips": own.get("TailscaleIPs"),
                      "peer_count": len(ts.get("Peer") or {})
                      if isinstance(ts, dict) else None},
        "firewall": {
            "ufw_status_header": run("ufw", "status").splitlines()[:1],
            "nft_tables_only": [ln for ln in nft.splitlines()
                                if ln.startswith("table ")][:100],
            "iptables_rules_count": sum(
                ln.startswith(("-A ", "-I ")) for ln in
                run("iptables", "-S").splitlines()),
        },
        "tcp_udp_listeners": [
            ln.split()[:5] for ln in
            run("ss", "-lntup").splitlines()[1:300]],
    }


def packages():
    all_packages = run("dpkg-query", "-W",
                       "-f=" + "$" + "{binary:Package}\\t" + "$" + "{Version}\\n",
                       timeout=60)
    infrastructure = []
    for ln in all_packages.splitlines():
        fields = ln.split("\t", 1)
        if len(fields) == 2 and fields[0].startswith(PKG_PREFIXES):
            infrastructure.append({"package": fields[0], "version": fields[1]})
    manual = run("apt-mark", "showmanual", timeout=45).splitlines()
    return {
        "infrastructure": infrastructure,
        "manual_packages": manual[:2500],
        "apt_source_file_names_only": names("/etc/apt/sources.list.d"),
    }


def accounts():
    users = []
    for ln in run("getent", "passwd").splitlines():
        fields = ln.split(":")
        if len(fields) != 7:
            continue
        try:
            uid = int(fields[2])
            gid = int(fields[3])
        except ValueError:
            continue
        if uid == 0 or 1000 <= uid < 60000:
            users.append({"name": fields[0], "uid": uid, "gid": gid,
                          "home": fields[5], "shell": fields[6]})
    group = run("getent", "group", "docker").strip().split(":")
    return {"root_and_regular_users": users,
            "docker_group_users": group[3].split(",") if len(group) > 3 else [],
            "password_hashes_not_collected": True}


def collect():
    os_release = {}
    for ln in text("/etc/os-release").splitlines():
        k, sep, value = ln.partition("=")
        if sep and k in ("ID", "VERSION_ID", "VERSION_CODENAME", "PRETTY_NAME"):
            os_release[k] = value.strip('"')
    systemd_data = systemd()
    service_data = {
        "systemd": systemd_data,
        "status": {name: {"enabled": name + ".service" in systemd_data["enabled_units"],
                          "running": name + ".service" in systemd_data["running_services"]}
                   for name in ("ssh", "fail2ban", "smartd", "docker",
                                "cron", "smbd", "nfs-server", "apcupsd",
                                "nut-monitor", "tailscaled", "pihm-web",
                                "unattended-upgrades")},
        "fail2ban": fail2ban(), "sshd": ssh(), "cron": cron(),
        "shares": shares(),
        "ups": {
            "apcaccess_status_and_charge_only": [
                ln for ln in run("apcaccess", "status", timeout=12).splitlines()
                if ln.strip().split(":", 1)[0].strip() in
                {"STATUS", "MODEL", "BCHARGE", "TIMELEFT"}],
            "nut_ups_names": run("upsc", "-l", timeout=12).splitlines()[:20],
            "apcupsd_filenames": names("/etc/apcupsd"),
            "nut_filenames": names("/etc/nut"),
        },
        "mail": {
            "installed_mail_executables": [
                p for p in ("mailx", "sendmail", "msmtp", "postfix") if shutil.which(p)],
            "postfix_filenames": names("/etc/postfix"),
        },
    }
    return {
        "schema": 1,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "identity": {
            "hostname": socket.gethostname(),
            "os_release": os_release,
            "kernel": run("uname", "-srmo").strip(),
            "boot_mode": "UEFI" if Path("/sys/firmware/efi").is_dir() else "BIOS",
        },
        "storage": {
            "block_devices": run_json("lsblk", "-J", "-b", "-o",
                "NAME,PATH,TYPE,SIZE,MODEL,SERIAL,TRAN,ROTA,FSTYPE,UUID,PARTUUID,MOUNTPOINTS"),
            "mounts": run_json("findmnt", "-J", "-o", "TARGET,SOURCE,FSTYPE"),
            "fstab_safe_fields_only": fstab(),
            "snapraid": snapraid(),
        },
        "host_features": service_data,
        "network": networking(),
        "packages": packages(),
        "accounts": accounts(),
        "docker": docker(),
        "paths_metadata_only": [metadata(path) for path in CONFIG_PATHS],
        "directory_filenames_only": {
            p: names(p) for p in (
                "/etc/fail2ban/jail.d", "/etc/ssh/sshd_config.d",
                "/etc/samba", "/etc/apcupsd", "/etc/nut",
                "/etc/openmediavault", "/etc/systemd/system",
                "/etc/docker", "/etc/cron.d")},
        "private_report_warning": [
            "This contains IP addresses, disk UUIDs/serials and paths.",
            "Does NOT include passwords, SSH keys, Docker env values or Compose bodies.",
            "NEVER push to public GitHub. This is NOT a backup.",
        ],
    }


def private_write(path, contents):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(contents)


def summary(report):
    host = report["host_features"]
    jails = [j["name"] for j in host["fail2ban"]["active_jails"]]
    state = host["status"]
    running = [name for name, value in state.items() if value["running"]]
    lines = [
        "DEBIAN MIGRATION READ-ONLY INVENTORY",
        "Hostname: " + report["identity"]["hostname"],
        "OS: " + report["identity"]["os_release"].get("PRETTY_NAME", "unknown"),
        "Boot: " + report["identity"]["boot_mode"],
        "Docker containers: " + str(len(report["docker"]["containers"])),
        "Docker named volumes: " + str(len(report["docker"]["volume_names"])),
        "Detected active host services: " + (", ".join(running) or "none"),
        "Fail2ban jails: " + (", ".join(jails) or "none"),
        "Samba shares: " + str(len(host["shares"]["samba"])),
        "NFS exported paths: " + str(len(host["shares"]["nfs"])),
        "Systemd enabled units: " + str(len(host["systemd"]["enabled_units"])),
        "Cron root jobs: " + str(len(host["cron"]["root_crontab_schedules_only"])),
        "SnapRAID directives: " + str(len(report["storage"]["snapraid"]["directives"])),
        "APT infrastructure packages: " + str(len(report["packages"]["infrastructure"])),
        "No services, mounts or containers modified. No credentials copied.",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-base", type=Path, default=OUT,
                        help="output base restricted to private /root")
    args = parser.parse_args()
    if os.geteuid() != 0 or socket.gethostname() != HOST:
        parser.error("Run as root on the confirmed openmediavault host")
    base = args.output_base
    if not base.is_absolute() or base.is_symlink() or not str(base).startswith("/root/"):
        parser.error("Private output must be under /root")
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    base.chmod(0o700)
    destination = base / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    destination.mkdir(mode=0o700)
    print("Collecting read-only server inventory...", flush=True)
    report = collect()
    lines = summary(report)
    private_write(destination / "inventory.json", json.dumps(report, indent=2) + "\n")
    private_write(destination / "summary.txt", lines)
    print("\n" + lines)
    print("Private details:", destination / "inventory.json")
    print("Review this file before sharing it privately in ChatGPT.")
    print("Do NOT publish or commit the inventory JSON to GitHub.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
