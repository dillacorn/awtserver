#!/usr/bin/env bash
# Install APT Docker-upgrade recovery without restarting Docker or containers.
set -euo pipefail

main() {
    local mode="" enable_live_restore=0 base target old_sha present_sha
    local manifest=/var/lib/omv-docker-upgrade-recovery/installed.sha256
    local i
    local -a source_files target_files

    for option in "$@"; do
        case "$option" in
            --check|--apply)
                if [[ -n "$mode" ]]; then
                    printf 'ERROR: specify exactly one of --check or --apply\n' >&2
                    return 2
                fi
                mode="$option"
                ;;
            --enable-live-restore) enable_live_restore=1 ;;
            *) printf 'Usage: %s --check | --apply [--enable-live-restore]\n' "$0" >&2; return 2 ;;
        esac
    done
    if [[ -z "$mode" || ( "$mode" != --apply && "$enable_live_restore" == 1 ) ]]; then
        printf 'Usage: %s --check | --apply [--enable-live-restore]\n' "$0" >&2
        return 2
    fi
    if [[ "$mode" == --apply && "$EUID" != 0 ]]; then
        printf 'ERROR: --apply requires root\n' >&2
        return 1
    fi

    base="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    source_files=(
        "$base/docker-upgrade-recovery.py"
        "$base/90-omv-docker-upgrade-recovery"
        "$base/omv-docker-upgrade-recovery.service"
        "$base/omv-docker-upgrade-recovery.timer"
    )
    target_files=(
        /usr/local/libexec/omv-docker-upgrade-recovery
        /etc/apt/apt.conf.d/90-omv-docker-upgrade-recovery
        /etc/systemd/system/omv-docker-upgrade-recovery.service
        /etc/systemd/system/omv-docker-upgrade-recovery.timer
    )

    # Preflight every file. Updates are allowed only when the installed copy
    # still matches the checksum this installer previously recorded.
    for i in "${!source_files[@]}"; do
        [[ -f "${source_files[$i]}" ]] || { printf 'ERROR: missing %s\n' "${source_files[$i]}" >&2; return 1; }
        target="${target_files[$i]}"
        if [[ -e "$target" || -L "$target" ]]; then
            if [[ -L "$target" || ! -f "$target" ]]; then
                printf 'ERROR: unexpected target %s\n' "$target" >&2
                return 1
            fi
            if cmp -s -- "${source_files[$i]}" "$target"; then
                printf 'Unchanged: %s\n' "$target"
                continue
            fi
            old_sha=""
            if [[ -f "$manifest" ]]; then
                old_sha="$(awk -v path="$target" '$2 == path {print $1}' "$manifest")"
            fi
            present_sha="$(sha256sum -- "$target")"
            present_sha="${present_sha%% *}"
            if [[ -z "$old_sha" || "$present_sha" != "$old_sha" ]]; then
                printf 'ERROR: modified or foreign file %s; refusing to replace\n' "$target" >&2
                return 1
            fi
            printf 'Update: %s\n' "$target"
        else
            printf 'Install: %s\n' "$target"
        fi
    done
    if ((enable_live_restore)) && [[ ! -f "$base/enable-live-restore.py" ]]; then
        printf 'ERROR: missing live-restore helper\n' >&2
        return 1
    fi
    if [[ "$mode" == --check ]]; then
        printf 'CHECK ONLY: no changes made\n'
        return 0
    fi

    install -d -m 0755 /usr/local/libexec /var/lib/omv-docker-upgrade-recovery
    chmod 0700 /var/lib/omv-docker-upgrade-recovery
    for i in "${!source_files[@]}"; do
        local perms=0644
        if ((i == 0)); then perms=0755; fi
        install -m "$perms" "${source_files[$i]}" "${target_files[$i]}"
    done
    # Write ownership manifest only after every managed file is installed.
    local manifest_tmp="${manifest}.tmp"
    : > "$manifest_tmp"
    chmod 0600 "$manifest_tmp"
    sha256sum -- "${target_files[@]}" > "$manifest_tmp"
    mv -f -- "$manifest_tmp" "$manifest"
    systemctl daemon-reload
    systemctl enable --now omv-docker-upgrade-recovery.timer
    printf 'APT Docker upgrade recovery installed; no container or Docker restart.\n'

    if ((enable_live_restore)); then
        python3 "$base/enable-live-restore.py" --apply
    fi
}

main "$@"
