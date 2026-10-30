#!/usr/bin/env python3
"""Guarded Prowlarr private Tailscale + Pi-hole local HTTPS setup on OMV.

--check: read-only audit of current host and Compose provenance.
--apply: enroll new tailscale-prowlarr only, export its certificate, add a
single local Pi-hole DNS record, and add an nginx site/cert mount.
Never touches Transmission, Prowlarr, Gluetun, aMuTorrent or Watchtower.
The apply requires a root-only ts/prowlarr/authkey.env created by the operator.
"""
import argparse
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time

PRIV = Path("/docker/privacy")
PI = Path("/docker/pihole")
SIDECAR = PRIV / "compose.prowlarr-access.yml"
PIMOUNT = PI / "compose.prowlarr.yml"
SITE = PI / "conf.d/prowlarr.conf"
AUTH = PRIV / "ts/prowlarr/authkey.env"
STATE = PRIV / "ts/prowlarr/state"
BACKUP = Path("/root/awtserver-prowlarr-access")
PRIV_FILES = (
    "compose.yml", "compose.override.yml", "compose.amutorrent.yml",
    "compose.trawl.yml", "compose.amutorrent-media.yml",
    "compose.transmission-music.yml",
)


class Stop(RuntimeError):
    pass


def need(ok, message):
    if not ok:
        raise Stop(message)


def run(args, check=True, timeout=90):
    try:
        result = subprocess.run(args, cwd=PRIV, text=True, capture_output=True,
                                timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Stop(f"Command unavailable or timed out: {args[0]}") from error
    if check and result.returncode:
        # Never echo potentially interpolated secrets or Tailscale credentials.
        raise Stop(f"Command failed: {args[0]} (status {result.returncode}, output hidden)")
    return result


def inspect(name):
    answer = run(["docker", "inspect", name], check=False, timeout=25)
    return json.loads(answer.stdout)[0] if answer.returncode == 0 else None


def labels(c):
    return c["Config"].get("Labels") or {}


def files_from_container(c, expected_project):
    meta = labels(c)
    need(meta.get("com.docker.compose.project") == expected_project,
         f"Unexpected Compose project for {c['Name']}")
    string = meta.get("com.docker.compose.project.config_files", "")
    need(bool(string), "Missing original Compose file provenance")
    paths = [Path(value.strip()) for value in string.split(",")]
    need(all(p.is_absolute() and p.is_file() and not p.is_symlink()
             for p in paths), "Missing/unsafe original Compose file")
    return paths


def compose(files, root, project, *args, check=True):
    command = ["docker", "compose", "-p", project,
               "--project-directory", str(root)]
    for file in files:
        command.extend(["-f", str(file)])
    return run(command + list(args), timeout=170, check=check)


def effective(files, root, project):
    return json.loads(compose(files, root, project, "config", "--format",
                              "json").stdout)["services"]


def compare(old, new, selected):
    need(set(old) == set(new), "Compose service list changed unexpectedly")
    for key in old:
        if key != selected:
            need(old[key] == new[key], f"Unrelated service changed: {key}")


def read_templates(folder):
    names = ("compose.prowlarr-access.yml", "compose.prowlarr.yml",
             "prowlarr.conf")
    data = {n: (folder / n) for n in names}
    need(all(p.is_file() and not p.is_symlink() for p in data.values()),
         "Missing proposed source templates")
    side = data[names[0]].read_text()
    pi = data[names[1]].read_text()
    site = data[names[2]].read_text()
    need(side.count("http://gluetun:9696") == 1 and
         "AllowFunnel" in side and "false" in side and
         "tailscale-prowlarr:" in side,
         "Unexpected Tailscale Serve template")
    need("/docker/privacy/ts/prowlarr/state/certs:/etc/nginx/prowlarr-certs:ro"
         in pi, "Unexpected Pi-hole certificate overlay")
    need(site.count("prowlarr.example-tailnet.ts.net") == 3 and
         "http://gluetun:9696" in site,
         "Unexpected nginx site template")
    return data


def tailnet_suffix():
    proc = run(["docker", "exec", "tailscale-amutorrent", "tailscale",
                "status", "--self", "--json"], timeout=20)
    self_info = json.loads(proc.stdout)["Self"]
    fqdn = self_info["DNSName"].rstrip(".").lower()
    need(re.fullmatch(r"amutorrent\.[a-z0-9.-]+\.ts\.net", fqdn),
         "Existing Tailscale aMuTorrent DNS name unexpected")
    return fqdn.removeprefix("amutorrent.")


def locate_dns(files, domain, current):
    hosts = (current["pihole"].get("environment") or {}).get("FTLCONF_dns_hosts")
    need(isinstance(hosts, str) and hosts.strip(),
         "Pi-hole FTLCONF_dns_hosts string missing; stop for manual inspection")
    lines = hosts.splitlines()
    matches = [line.split() for line in lines if len(line.split()) == 2
               and line.split()[1].lower() == "amutorrent." + domain]
    need(len(matches) == 1, "Expected exactly one existing aMuTorrent DNS record")
    ip = matches[0][0]
    need(ipaddress.ip_address(ip).version == 4, "Existing record is not IPv4")
    new_record = "prowlarr." + domain
    need(not any(new_record in line.split() for line in lines),
         "Prowlarr DNS record already exists")
    source_matches = []
    for path in files:
        text = path.read_text()
        for entry in text.splitlines(keepends=True):
            parts = entry.strip().split()
            if len(parts) == 2 and parts == [ip, "amutorrent." + domain]:
                source_matches.append((path, entry))
    need(len(source_matches) == 1,
         "Cannot find unique literal existing Pi-hole DNS record in live Compose")
    origin, line = source_matches[0]
    indent = line[:len(line) - len(line.lstrip())]
    new_line = indent + ip + " " + new_record + "\n"
    edited = origin.read_text().replace(line, line + new_line, 1)
    need(edited != origin.read_text(), "Failed to stage DNS record insertion")
    return origin, edited, new_record, ip


def identify_pi_proxy(parent, containers, services, pfiles):
    dependents = [c for c in containers
                  if c["HostConfig"].get("NetworkMode") ==
                  "container:" + parent["Id"]]
    need(len(dependents) == 1,
         "Expected exactly one known Pi-hole namespace dependent")
    client = dependents[0]
    client_name = client["Name"].lstrip("/")
    need(client_name in ("dnsproxy", "dnsproxy-quad9"),
         "Unexpected container attached to Pi-hole namespace")
    need(client["State"]["Status"] == "running",
         "Pi-hole DNS proxy dependent is not running")
    need(labels(client).get("com.docker.compose.project") == "pihole",
         "Pi-hole DNS proxy has unexpected Compose project")
    service_name = labels(client).get("com.docker.compose.service")
    need(service_name in ("dnsproxy", "dnsproxy-quad9"),
         "Pi-hole DNS proxy has unexpected Compose service")
    need(service_name in services,
         "Pi-hole DNS proxy service is absent from active Compose")
    need(services[service_name].get("network_mode") == "service:pihole",
         "Pi-hole DNS proxy Compose service is not namespace-dependent")
    need(files_from_container(client, "pihole") == pfiles,
         "Pi-hole DNS proxy uses different Compose file provenance")
    return client_name, service_name


def preflight(template_dir):
    need(os.geteuid() == 0 and socket.gethostname() == "openmediavault",
         "Root on openmediavault required")
    need(PRIV.is_dir() and not PRIV.is_symlink() and
         PI.is_dir() and not PI.is_symlink(), "Unexpected project directories")
    template_files = read_templates(template_dir)
    privfiles = [PRIV / name for name in PRIV_FILES]
    need(all(p.is_file() and not p.is_symlink() for p in privfiles),
         "Current SIX privacy Compose overlays not found")
    need(not SIDECAR.exists() and not SIDECAR.is_symlink(),
         "Prowlarr Tailscale sidecar overlay exists; refuse repeat apply")
    need(not PIMOUNT.exists() and not PIMOUNT.is_symlink() and
         not SITE.exists() and not SITE.is_symlink(),
         "Prowlarr Pi-hole/nginx files already exist")
    existing = {n: inspect(n) for n in (
        "gluetun", "prowlarr", "transmission", "amutorrent",
        "tailscale-amutorrent", "pihole", "nginx-pihole", "watchtower")}
    need(all(c and c["State"]["Status"] == "running" for c in existing.values()),
         "One or more existing containers not running")
    need(inspect("tailscale-prowlarr") is None,
         "A Prowlarr Tailscale container already exists")
    for name in ("gluetun", "prowlarr", "transmission", "amutorrent"):
        meta = labels(existing[name])
        need(meta.get("com.docker.compose.project") == "privacy",
             f"Unexpected Compose project: {name}")
    need(labels(existing["prowlarr"]).get("com.docker.compose.service") ==
         "prowlarr", "Prowlarr service name mismatch")
    need(existing["prowlarr"]["HostConfig"].get("NetworkMode") ==
         "container:" + existing["gluetun"]["Id"],
         "Prowlarr must remain attached to the existing Gluetun namespace")
    need((existing["gluetun"]["State"].get("Health") or {}).get("Status") ==
         "healthy", "Gluetun is not healthy")
    configured = effective(privfiles, PRIV, "privacy")
    need(configured.get("prowlarr", {}).get("network_mode") == "service:gluetun",
         "Current privacy effective Compose unexpectedly changed")
    # The new sidecar must add only one new service, never alter the existing stack.
    newside = effective([*privfiles, template_files["compose.prowlarr-access.yml"]],
                        PRIV, "privacy")
    need(set(newside) == set(configured) | {"tailscale-prowlarr"},
         "Tailscale overlay changed existing service list")
    for name in configured:
        need(configured[name] == newside[name],
             f"Tailscale overlay alters existing service: {name}")

    pfiles = files_from_container(existing["pihole"], "pihole")
    need(pfiles == files_from_container(existing["nginx-pihole"], "pihole"),
         "Pi-hole/nginx Compose provenance differs")
    need(all(str(p).startswith(str(PI) + "/") for p in pfiles),
         "Pi-hole Compose provenance outside /docker/pihole")
    pcompose = effective(pfiles, PI, "pihole")
    need("pihole" in pcompose and "nginx" in pcompose,
         "Expected pihole and nginx services not in Compose")
    # Inspect the real Docker namespace dependency rather than assuming a
    # container named dnsproxy. Live OMV uses dnsproxy-quad9.
    all_ids = run(["docker", "ps", "-aq"], timeout=20).stdout.split()
    need(all_ids, "Docker inventory is empty")
    all_containers = json.loads(run(["docker", "inspect", *all_ids],
                                    timeout=90).stdout)
    client_name, service_name = identify_pi_proxy(
        existing["pihole"], all_containers, pcompose, pfiles)
    domain = tailnet_suffix()
    dns_path, dns_edited, new_domain, lan_ip = locate_dns(
        pfiles, domain, pcompose)
    need(dns_path.stat().st_uid == 0 and
         stat.S_IMODE(dns_path.stat().st_mode) & 0o022 == 0,
         "Pi-hole Compose DNS source has unsafe ownership/permissions")
    need("system.posix_acl_access" not in os.listxattr(dns_path),
         "Pi-hole Compose DNS source has an extended ACL; refuse atomic replacement")
    nginx = existing["nginx-pihole"]
    mounts = {m["Destination"]: m for m in nginx["Mounts"]}
    need(mounts.get("/etc/nginx/conf.d", {}).get("Source") == str(PI / "conf.d"),
         "nginx conf.d directory does not match the expected host path")
    need("/etc/nginx/prowlarr-certs" not in mounts,
         "nginx already has a Prowlarr certificate mount")
    networks = set(nginx["NetworkSettings"]["Networks"]) & set(
        existing["gluetun"]["NetworkSettings"]["Networks"])
    need("local-webapps" in networks,
         "Existing nginx and Gluetun do not share local-webapps")
    need(run(["docker", "exec", "nginx-pihole", "nginx", "-t"],
             check=False, timeout=20).returncode == 0,
         "Existing nginx config test failed")

    key_status = "not created"
    if AUTH.exists() or AUTH.is_symlink():
        need(AUTH.is_file() and not AUTH.is_symlink() and
             AUTH.stat().st_uid == 0 and
             stat.S_IMODE(AUTH.stat().st_mode) & 0o077 == 0,
             "Tailscale authkey.env must be root-only (0600)")
        key_status = "root-private file present"
    print("PASS: Existing six privacy Compose files and Prowlarr VPN unchanged")
    print("PASS: Pi-hole/nginx live Compose provenance and current DNS record verified")
    print("PASS: nginx and Gluetun share the existing local-webapps network")
    print("PASS: Pi-hole namespace dependent:", client_name,
          "(Compose service:", service_name + ")")
    print("Planned HTTPS hostname:", new_domain)
    print("Current Pi-hole DNS source:", dns_path)
    print("Current Pi-hole Compose files:", ", ".join(p.name for p in pfiles))
    print("Auth key:", key_status, "(contents never displayed)")
    return (template_files, privfiles, pfiles, pcompose, dns_path,
            dns_path.read_bytes(), dns_edited, new_domain, lan_ip,
            client_name, service_name)


def atomic(path, content, original=None):
    mode = stat.S_IMODE(path.stat().st_mode) if original is not None else 0o644
    fd, staged = tempfile.mkstemp(prefix=".prowlarr-stage-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        if original is not None:
            os.fchown(fd, path.stat().st_uid, path.stat().st_gid)
        with os.fdopen(fd, "wb") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(staged, path)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)


def wait_tailnet(name, domain):
    for attempt in range(35):
        c = inspect(name)
        if c and c["State"]["Status"] == "running":
            status = run(["docker", "exec", name, "tailscale", "status",
                          "--self", "--json"], check=False, timeout=12)
            if status.returncode == 0:
                try:
                    dns = json.loads(status.stdout)["Self"]["DNSName"].rstrip(".").lower()
                    if dns == domain:
                        return
                except (KeyError, ValueError, TypeError):
                    pass
        time.sleep(2)
    raise Stop("New Tailscale machine did not register with expected MagicDNS name")


def save_cert(hostname):
    cert_root = STATE / "certs"
    need(cert_root.is_dir() or not cert_root.exists(),
         "Unexpected certificate directory type")
    run(["docker", "exec", "tailscale-prowlarr", "mkdir", "-p",
         "/var/lib/tailscale/certs"])
    run(["docker", "exec", "tailscale-prowlarr", "tailscale", "cert",
         "--cert-file", f"/var/lib/tailscale/certs/{hostname}.crt",
         "--key-file", f"/var/lib/tailscale/certs/{hostname}.key",
         hostname], timeout=100)
    crt = cert_root / (hostname + ".crt")
    key = cert_root / (hostname + ".key")
    need(crt.is_file() and key.is_file() and not crt.is_symlink() and
         not key.is_symlink() and key.stat().st_size > 0,
         "Tailscale certificate files not exported to persistent state")
    need(run(["openssl", "x509", "-in", str(crt), "-noout"],
             check=False).returncode == 0, "Exported certificate invalid")


def dns_lookup_a(ip, hostname):
    """Query Pi-hole's actual DNS socket, not Docker's embedded resolver."""
    qname = b"".join(bytes([len(label)]) + label.encode("ascii")
                     for label in hostname.split(".")) + b"\x00"
    packet = (struct.pack("!HHHHHH", 0x9876, 0x0100, 1, 0, 0, 0) +
              qname + struct.pack("!HH", 1, 1))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(3)
        sock.sendto(packet, (ip, 53))
        answer, _ = sock.recvfrom(4096)
    need(len(answer) >= 12 and answer[:2] == b"\x98\x76",
         "Unexpected Pi-hole DNS reply")
    _, flags, questions, answers, _, _ = struct.unpack("!HHHHHH",
                                                        answer[:12])
    need((flags & 0x000F) == 0 and questions == 1,
         "Pi-hole returned a DNS error")
    def skip_name(offset):
        while offset < len(answer):
            size = answer[offset]
            if size & 0xC0 == 0xC0:
                return offset + 2
            if size == 0:
                return offset + 1
            offset += 1 + size
        raise Stop("Truncated DNS name in Pi-hole response")
    offset = skip_name(12) + 4
    found = []
    for _ in range(answers):
        offset = skip_name(offset)
        need(offset + 10 <= len(answer), "Truncated DNS resource record")
        kind, klass, _, length = struct.unpack("!HHIH",
                                               answer[offset:offset+10])
        offset += 10
        need(offset + length <= len(answer), "Truncated DNS answer")
        if kind == 1 and klass == 1 and length == 4:
            found.append(str(ipaddress.IPv4Address(answer[offset:offset+4])))
        offset += length
    return found


def recycle_pi(files, client_name, service_name):
    # Pi-hole is the proxy's network namespace parent. Recreate the exact
    # observed Compose service after Pi-hole is replaced. Fail closed if the
    # dependent's runtime name or network relationship changes.
    compose(files, PI, "pihole", "up", "-d", "--no-deps", "--no-build",
            "--pull", "never", "pihole")
    compose(files, PI, "pihole", "up", "-d", "--no-deps",
            "--force-recreate", "--no-build", "--pull", "never", service_name)
    compose(files, PI, "pihole", "up", "-d", "--no-deps", "--no-build",
            "--pull", "never", "nginx")
    parent = inspect("pihole")
    proxy = inspect(client_name)
    need(parent and proxy and
         parent["State"]["Status"] == "running" and
         proxy["State"]["Status"] == "running" and
         proxy["HostConfig"].get("NetworkMode") ==
         "container:" + parent["Id"],
         "Pi-hole DNS proxy dependent network not restored")


def apply(context):
    (templates, privfiles, pfiles, old_pi, dns_path,
     saved_dns_bytes, dns_text, hostname, lan_ip,
     client_name, service_name) = context
    need(AUTH.is_file() and not AUTH.is_symlink() and
         AUTH.stat().st_uid == 0 and
         stat.S_IMODE(AUTH.stat().st_mode) & 0o077 == 0 and
         AUTH.read_text().startswith("TS_AUTHKEY=") and
         20 < len(AUTH.read_text().strip()) < 300,
         "Create a root-only ts/prowlarr/authkey.env with TS_AUTHKEY first")
    need(not STATE.exists() or
         (STATE.is_dir() and not STATE.is_symlink()),
         "Tailscale state path is not a safe directory")
    # Stage only the new sidecar Compose file; no existing container is recreated.
    fd = os.open(SIDECAR, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w") as dst:
        dst.write(templates["compose.prowlarr-access.yml"].read_text())
    compose([*privfiles, SIDECAR], PRIV, "privacy", "up", "-d",
            "--no-deps", "--no-build", "--pull", "missing", "tailscale-prowlarr")
    wait_tailnet("tailscale-prowlarr", hostname)
    save_cert(hostname)
    print("PASS: Tailscale Prowlarr machine registered and HTTPS certificate exported")
    # Stage candidate DNS content in the same directory, then compare effective
    # Compose before modifying either running Pi-hole or nginx.
    fd, staging = tempfile.mkstemp(prefix=".prowlarr-dns-stage-", dir=PI,
                                  suffix=".yml")
    with os.fdopen(fd, "w") as f:
        f.write(dns_text)
    stage_path = Path(staging)
    try:
        staged_files = [stage_path if p == dns_path else p for p in pfiles]
        candidate = effective(staged_files, PI, "pihole")
        for name in old_pi:
            if name != "pihole":
                need(old_pi[name] == candidate[name],
                     f"DNS edit changes unrelated Pi-hole service {name}")
        a, b = dict(old_pi["pihole"]), dict(candidate["pihole"])
        ae, be = dict(a.pop("environment")), dict(b.pop("environment"))
        old_records = ae.pop("FTLCONF_dns_hosts")
        new_records = be.pop("FTLCONF_dns_hosts")
        lines = old_records.splitlines()
        anchor_indices = [i for i, line in enumerate(lines)
                          if line.strip() ==
                          lan_ip + " " + "amutorrent." +
                          hostname.removeprefix("prowlarr.")]
        need(len(anchor_indices) == 1, "Original Pi-hole record not unique")
        lines.insert(anchor_indices[0] + 1, lan_ip + " " + hostname)
        need(a == b and ae == be and new_records.splitlines() == lines,
             "DNS edit changes anything beyond the one Prowlarr record")
        mount_candidate = effective([*staged_files,
                                     templates["compose.prowlarr.yml"]],
                                    PI, "pihole")
        for name in candidate:
            if name != "nginx":
                need(candidate[name] == mount_candidate[name],
                     "Certificate overlay changes a non-nginx service")
        old_nginx = dict(candidate["nginx"])
        new_nginx = dict(mount_candidate["nginx"])
        av = old_nginx.pop("volumes")
        bv = new_nginx.pop("volumes")
        need(old_nginx == new_nginx and len(bv) == len(av) + 1 and
             bv[:len(av)] == av and
             bv[-1].get("target") == "/etc/nginx/prowlarr-certs",
             "Certificate overlay changes existing nginx settings")
    finally:
        stage_path.unlink(missing_ok=True)

    need(not BACKUP.is_symlink(), "Backup directory symlink disallowed")
    BACKUP.mkdir(mode=0o700, exist_ok=True)
    need(BACKUP.stat().st_uid == 0 and
         stat.S_IMODE(BACKUP.stat().st_mode) & 0o077 == 0,
         "Backup directory must remain root-private")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUP / (stamp + "-" + str(os.getpid()))
    backup.mkdir(mode=0o700)
    original = dns_path.read_bytes()
    need(original == saved_dns_bytes,
         "Pi-hole source changed since the read-only preflight")
    (backup / "pihole-original.yml").write_bytes(original)
    (backup / "source-path.txt").write_text(str(dns_path) + "\n")
    (backup / "pihole-original.yml").chmod(0o600)
    # Mutate only one existing Pi-hole Compose source and create two new files.
    atomic(dns_path, dns_text.encode(), original=original)
    site_content = templates["prowlarr.conf"].read_text().replace(
        "prowlarr.example-tailnet.ts.net", hostname)
    try:
        fd = os.open(SITE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "w") as dst:
            dst.write(site_content)
        fd = os.open(PIMOUNT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "w") as dst:
            dst.write(templates["compose.prowlarr.yml"].read_text())
        recycle_pi([*pfiles, PIMOUNT], client_name, service_name)
        need(run(["docker", "exec", "nginx-pihole", "nginx", "-t"],
                 check=False, timeout=15).returncode == 0,
             "nginx configuration test failed after recreation")
        # Query Pi-hole directly, not the container's Docker DNS resolver.
        for attempt in range(20):
            try:
                if lan_ip in dns_lookup_a(lan_ip, hostname):
                    break
            except (OSError, Stop):
                pass
            time.sleep(2)
        else:
            raise Stop("Pi-hole does not serve the new local DNS A record")
        for attempt in range(20):
            check = run(["curl", "--silent", "--show-error", "-o", "/dev/null",
                         "-w", "%{http_code}", "--max-time", "12",
                         "--resolve", hostname + ":443:" + lan_ip,
                         "https://" + hostname + "/"],
                        check=False, timeout=18)
            if check.returncode == 0 and check.stdout.strip() in (
                    "200", "301", "302", "303", "307", "308", "401", "403"):
                break
            time.sleep(2)
        else:
            raise Stop("LAN HTTPS/TLS proxy did not return a web response")
    except Exception as problem:
        print("STOP: Pi-hole/nginx validation failed; attempting scoped rollback",
              file=sys.stderr)
        try:
            need(dns_path.read_text() == dns_text,
                 "DNS source changed concurrently; manual restore required")
            atomic(dns_path, original, original=original)
            if SITE.exists() and SITE.read_text() == site_content:
                SITE.unlink()
            if PIMOUNT.exists() and PIMOUNT.read_text() == \
                    templates["compose.prowlarr.yml"].read_text():
                PIMOUNT.unlink()
            recycle_pi(pfiles, client_name, service_name)
            print("PASS: Pi-hole/nginx Compose restored; Tailscale sidecar retained",
                  file=sys.stderr)
        except Exception as rollback:
            print("WARNING: Pi-hole/nginx rollback unverified: " + str(rollback),
                  file=sys.stderr)
        print("Backup:", backup, file=sys.stderr)
        raise Stop("Local HTTPS setup not completed") from problem
    # Remove the bootstrap key from disk and from the running container's
    # environment. The persisted Tailscale state authenticates restarts.
    try:
        need(AUTH.is_file() and not AUTH.is_symlink() and
             AUTH.read_text().startswith("TS_AUTHKEY="),
             "Bootstrap authkey file changed during setup")
        atomic(AUTH, b"", original=AUTH.read_bytes())
        compose([*privfiles, SIDECAR], PRIV, "privacy", "up", "-d",
                "--no-deps", "--force-recreate", "--no-build", "--pull",
                "never", "tailscale-prowlarr")
        wait_tailnet("tailscale-prowlarr", hostname)
        current = inspect("tailscale-prowlarr")
        env_names = {x.split("=", 1)[0] for x in
                     (current["Config"].get("Env") or [])}
        need("TS_AUTHKEY" not in env_names,
             "Bootstrap auth key still present in container environment")
        print("PASS: Bootstrap auth key cleared from file and container environment")
    except Exception:
        print("WARNING: Verify/revoke bootstrap auth key in Tailscale admin; "
              "automatic credential scrubbing was not confirmed",
              file=sys.stderr)
    print("PASS: Pi-hole DNS and local nginx HTTPS respond correctly")
    print("PASS: Existing privacy services and VPN unchanged")
    print("Private HTTPS:", "https://" + hostname)
    print("Pi-hole backup:", backup)
    print("IMPORTANT: Keep 7 privacy overlays and add the Pi-hole overlay to its full Compose set")
    print("IMPORTANT: Revoke the one-time Tailscale auth key after verifying registration")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    flag = p.add_mutually_exclusive_group(required=True)
    flag.add_argument("--check", action="store_true")
    flag.add_argument("--apply", action="store_true")
    p.add_argument("--templates", type=Path, required=True)
    args = p.parse_args()
    try:
        context = preflight(args.templates)
        if args.apply:
            apply(context)
        else:
            print("READ-ONLY PASS; no files or containers changed")
        return 0
    except (Stop, OSError, KeyError, TypeError, ValueError) as error:
        print("STOP:", error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
