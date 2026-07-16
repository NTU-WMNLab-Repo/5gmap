#!/usr/bin/env bash

set -euo pipefail

GREEN='\033[32m'
BLUE='\033[34m'
RED='\033[31m'
NC='\033[0m'

bold="$(tput bold 2>/dev/null || true)"
NORMAL="$(tput sgr0 2>/dev/null || true)"

info() {
    echo -e "${BLUE}${bold}$*${NC}${NORMAL}"
}

success() {
    echo -e "${GREEN}${bold}$*${NC}${NORMAL}"
}

error() {
    echo -e "${RED}${bold}$*${NC}${NORMAL}" >&2
}

die() {
    error "$*"
    exit 1
}

enable_error_trap() {
    trap 'error "Failed at ${BASH_SOURCE[0]}:${LINENO}: ${BASH_COMMAND}"' ERR
}

require_commands() {
    local cmd
    for cmd in "$@"; do
        command -v "$cmd" >/dev/null 2>&1 || die "Missing required command: $cmd"
    done
}

set_yaml_value() {
    local file="$1"
    local key="$2"
    local value="$3"

    if ! grep -qE "^[[:space:]]*${key}:" "$file"; then
        die "Cannot find key '$key' in $file"
    fi

    sed -i -E "s|^([[:space:]]*)${key}:.*|\\1${key}: ${value}|" "$file"
}

pod_by_prefix() {
    local namespace="$1"
    local prefix="$2"

    kubectl get pods -n "$namespace" \
        --field-selector=status.phase!=Succeeded,status.phase!=Failed \
        --no-headers 2>/dev/null \
        | awk -v prefix="$prefix" '$1 ~ "^" prefix {print $1; exit}'
}

wait_for_pod() {
    local namespace="$1"
    local prefix="$2"
    local timeout="${3:-300}"
    local elapsed=0
    local pod=""
    local phase=""
    local ready=""
    local waiting_reasons=""

    info "Waiting for pod ${prefix} in namespace ${namespace}"

    while [ "$elapsed" -lt "$timeout" ]; do
        pod="$(pod_by_prefix "$namespace" "$prefix" || true)"

        if [ -n "$pod" ]; then
            phase="$(kubectl get pod "$pod" -n "$namespace" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
            ready="$(kubectl get pod "$pod" -n "$namespace" -o jsonpath='{.status.containerStatuses[*].ready}' 2>/dev/null || true)"
            waiting_reasons="$(kubectl get pod "$pod" -n "$namespace" -o jsonpath='{.status.containerStatuses[*].state.waiting.reason}' 2>/dev/null || true)"

            if [[ "$waiting_reasons" == *CrashLoopBackOff* ]] || [[ "$waiting_reasons" == *ImagePullBackOff* ]] || [[ "$waiting_reasons" == *ErrImagePull* ]]; then
                kubectl describe pod "$pod" -n "$namespace" >&2 || true
                die "Pod $pod is not healthy: $waiting_reasons"
            fi

            if [ "$phase" = "Running" ] && [[ "$ready" != *false* ]]; then
                success "$pod is running"
                return 0
            fi
        fi

        sleep 5
        elapsed=$((elapsed + 5))
    done

    kubectl get pods -n "$namespace" >&2 || true
    die "Timed out waiting for pod prefix '$prefix'"
}

get_pod_ip() {
    local namespace="$1"
    local pod="$2"
    local container="${3:-}"
    local ip=""
    local exec_args=(-n "$namespace" "$pod")

    ip="$(kubectl get pod "$pod" -n "$namespace" -o jsonpath='{.status.podIP}' 2>/dev/null || true)"
    if [ -n "$ip" ]; then
        echo "$ip"
        return 0
    fi

    if [ -n "$container" ]; then
        exec_args+=(-c "$container")
    fi

    ip="$(kubectl exec "${exec_args[@]}" -- sh -c "ip -4 addr show eth0 2>/dev/null | awk '/inet / {print \$2; exit}' | cut -d/ -f1" 2>/dev/null || true)"

    if [ -z "$ip" ]; then
        ip="$(kubectl exec "${exec_args[@]}" -- sh -c "ifconfig 2>/dev/null | awk '/inet 10\\.42/ {print \$2; exit}'" 2>/dev/null || true)"
    fi

    [ -n "$ip" ] || die "Could not get eth0 IP for pod $pod"
    echo "$ip"
}

exec_has() {
    local namespace="$1"
    local pod="$2"
    local container="$3"
    local cmd="$4"
    local exec_args=(-n "$namespace" "$pod")

    if [ -n "$container" ]; then
        exec_args+=(-c "$container")
    fi

    kubectl exec "${exec_args[@]}" -- sh -c "command -v $cmd >/dev/null 2>&1"
}

helm_uninstall_if_exists() {
    local release="$1"
    local namespace="$2"

    if helm status "$release" -n "$namespace" >/dev/null 2>&1; then
        helm uninstall "$release" -n "$namespace"
    fi
}
