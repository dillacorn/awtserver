#!/usr/bin/env bash
# Temporary Tailscale-only DNS forwarding when Pi-hole lost its Tailscale port binding.
# Does not change Docker, Compose, Pi-hole, or other firewall rules.
set -euo pipefail

main() {
    local action="${1:---check}" container="${PIHOLE_CONTAINER:-pihole}"
    local tsip udp_binding tcp_binding lan_ip protocol added=() native_udp=0 native_tcp=0
    local -a rule

    case "$action" in
        --check|--apply|--remove) ;;
        *) printf 'Usage: %s [--check|--apply|--remove]\n' "$0" >&2; return 2 ;;
    esac
    if [[ "$action" != --check && "$EUID" != 0 ]]; then
        printf 'ERROR: apply/remove require root\n' >&2
        return 1
    fi
    for cmd in docker tailscale iptables ip python3; do
        command -v "$cmd" >/dev/null || { printf 'ERROR: missing %s\n' "$cmd" >&2; return 1; }
    done
    [[ "$(docker inspect --format '{{.State.Running}} {{.State.Paused}}' "$container")" == 'true false' ]] || {
        printf 'ERROR: Pi-hole container not running or paused\n' >&2
        return 1
    }
    tsip="$(tailscale ip -4)"
    udp_binding="$(docker port "$container" 53/udp)"
    tcp_binding="$(docker port "$container" 53/tcp)"
    # A corrected Pi-hole may publish *both* LAN and Tailscale addresses.
    # Retain the LAN address for removing previously inserted rescue rules.
    lan_ip="$(python3 - "$tsip" "$udp_binding" "$tcp_binding" <<'PYPORT'
import ipaddress
import sys

tail, udp, tcp = sys.argv[1:]
def get_entries(lines):
    entries = set()
    for line in lines.splitlines():
        if not line.endswith(':53'):
            raise ValueError('unexpected port publication')
        ip = line[:-3]
        ipaddress.IPv4Address(ip)
        entries.add(ip)
    return entries

try:
    udp_entries, tcp_entries = get_entries(udp), get_entries(tcp)
    if not udp_entries or udp_entries != tcp_entries:
        raise ValueError('mismatched TCP and UDP DNS publication')
    lans = [x for x in udp_entries if x != tail and not (
        ipaddress.IPv4Address(x).is_unspecified or
        ipaddress.IPv4Address(x).is_loopback or
        ipaddress.IPv4Address(x).is_multicast)]
    if len(lans) != 1:
        raise ValueError('expected one unambiguous LAN DNS binding')
    print(lans[0])
except ValueError as error:
    sys.stderr.write('ERROR: ' + str(error) + '\n')
    raise SystemExit(1)
PYPORT
)" || return 1
    if [[ "$udp_binding" == *"${tsip}:53"* ]]; then native_udp=1; fi
    if [[ "$tcp_binding" == *"${tsip}:53"* ]]; then native_tcp=1; fi
    if [[ "$action" == --apply && "$native_udp" == 1 && "$native_tcp" == 1 ]]; then
        printf 'Native Tailscale DNS ports already published; no rescue rules needed.\n'
        return 0
    fi
    python3 - "$tsip" "$lan_ip" <<'PY'
import ipaddress, sys
try:
    tail = ipaddress.IPv4Address(sys.argv[1])
    lan = ipaddress.IPv4Address(sys.argv[2])
    if tail not in ipaddress.IPv4Network('100.64.0.0/10') or lan.is_unspecified or lan.is_loopback or lan.is_multicast or lan == tail:
        raise ValueError('invalid Tailscale or LAN binding')
except ValueError as error:
    raise SystemExit('ERROR: ' + str(error))
PY
    ip -4 -o addr show dev tailscale0 | grep -Fq "${tsip}/" || {
        printf 'ERROR: Tailscale IP is not assigned to tailscale0\n' >&2
        return 1
    }
    printf 'Pi-hole LAN DNS: %s:53; Tailscale DNS: %s:53\n' "$lan_ip" "$tsip"
    for protocol in udp tcp; do
        rule=(-i tailscale0 -d "$tsip" -p "$protocol" --dport 53
              -m comment --comment 'omv-pihole-ts-dns-rescue' -j DNAT --to-destination "$lan_ip")
        if iptables -w 5 -t nat -C PREROUTING "${rule[@]}" >/dev/null 2>&1; then
            if [[ "$action" == --remove ]]; then
                iptables -w 5 -t nat -D PREROUTING "${rule[@]}"
                printf 'Removed %s redirect\n' "$protocol"
            else
                printf 'Present %s redirect\n' "$protocol"
            fi
        elif [[ "$action" == --apply ]]; then
            if ! iptables -w 5 -t nat -I PREROUTING 1 "${rule[@]}"; then
                # Undo only rules this attempt created. Preserve pre-existing rules.
                for prior in "${added[@]}"; do
                    iptables -w 5 -t nat -D PREROUTING -i tailscale0 -d "$tsip" \
                        -p "$prior" --dport 53 -m comment --comment \
                        'omv-pihole-ts-dns-rescue' -j DNAT --to-destination "$lan_ip" || true
                done
                printf 'ERROR: failed to install %s redirect\n' "$protocol" >&2
                return 1
            fi
            added+=("$protocol")
            printf 'Added %s redirect\n' "$protocol"
        else
            printf 'Absent %s redirect\n' "$protocol"
        fi
    done
    if [[ "$action" == --apply ]]; then
        printf 'Temporary Tailscale DNS forwarding active; Pi-hole and Docker not restarted.\n'
        printf 'Check remote Tailscale DNS before treating this as working.\n'
    fi
}

main "$@"
