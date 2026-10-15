#!/usr/bin/env bash
# Install the opt-in Pi-hole Tailscale DNS continuity guard without container restarts.
set -euo pipefail

main() {
    local mode="${1:---check}" i sha old target source manifest
    local base
    local -a sources targets
    case "$mode" in
        --check|--apply) ;;
        *) printf 'Usage: %s [--check|--apply]\n' "$0" >&2; return 2 ;;
    esac
    if [[ "$mode" == --apply && "$EUID" != 0 ]]; then
        printf 'ERROR: --apply requires root\n' >&2
        return 1
    fi
    base="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    manifest=/var/lib/omv-pihole-tailscale-dns-guard/installed.sha256
    sources=(
        "$base/../tailscale-dns-rescue.sh"
        "$base/omv-pihole-tailscale-dns-guard"
        "$base/omv-pihole-tailscale-dns-guard.service"
        "$base/omv-pihole-tailscale-dns-guard.timer"
    )
    targets=(
        /usr/local/libexec/omv-pihole-tailscale-dns-rescue
        /usr/local/libexec/omv-pihole-tailscale-dns-guard
        /etc/systemd/system/omv-pihole-tailscale-dns-guard.service
        /etc/systemd/system/omv-pihole-tailscale-dns-guard.timer
    )
    for i in "${!sources[@]}"; do
        source="${sources[$i]}"; target="${targets[$i]}"
        [[ -f "$source" && ! -L "$source" ]] || { printf 'ERROR: missing or unsafe source: %s\n' "$source" >&2; return 1; }
        if [[ -e "$target" || -L "$target" ]]; then
            [[ -f "$target" && ! -L "$target" ]] || { printf 'ERROR: unsupported existing file: %s\n' "$target" >&2; return 1; }
            if cmp -s -- "$source" "$target"; then
                printf 'Unchanged: %s\n' "$target"
                continue
            fi
            sha="$(sha256sum -- "$target")"; sha="${sha%% *}"
            old=''
            if [[ -f "$manifest" ]]; then
                old="$(awk -v path="$target" '$2 == path {print $1}' "$manifest")"
            fi
            [[ -n "$old" && "$old" == "$sha" ]] || { printf 'ERROR: refusing to replace foreign/edited file: %s\n' "$target" >&2; return 1; }
            printf 'Update: %s\n' "$target"
        else
            printf 'Install: %s\n' "$target"
        fi
    done
    if [[ "$mode" == --check ]]; then
        printf 'CHECK ONLY: no changes made\n'
        return 0
    fi
    install -d -m 0755 /usr/local/libexec
    install -d -m 0700 /var/lib/omv-pihole-tailscale-dns-guard
    for i in "${!sources[@]}"; do
        local permissions=0755
        if (( i > 1 )); then permissions=0644; fi
        install -m "$permissions" "${sources[$i]}" "${targets[$i]}"
    done
    local tmp="${manifest}.tmp"
    sha256sum -- "${targets[@]}" > "$tmp"
    chmod 0600 "$tmp"
    mv -f -- "$tmp" "$manifest"
    systemctl daemon-reload
    systemctl enable --now omv-pihole-tailscale-dns-guard.timer
    printf 'DNS guard enabled; Pi-hole/Docker/Tailscale were not restarted\n'
}
main "$@"
