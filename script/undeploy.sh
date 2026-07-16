#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"
enable_error_trap

NUM_USERS="${1:-1}"
NUM_SLICES="${2:-1}"
NAMESPACE="${NAMESPACE:-oai}"
DELETE_MYSQL="${DELETE_MYSQL:-0}"

require_commands kubectl helm

info "Cleaning 5GMAP OAI RAN deployment"

slice_end=$((NUM_SLICES + 9))
total=$((NUM_USERS * NUM_SLICES))

for ((offset=0; offset<total; offset++)); do
    u=$((10 + offset))
    kubectl delete deployment "oai-dnn$u" -n "$NAMESPACE" --ignore-not-found=true
    helm_uninstall_if_exists "nrue$u" "$NAMESPACE"
    helm_uninstall_if_exists "gnbdu$u" "$NAMESPACE"
    helm_uninstall_if_exists "gnbcu$u" "$NAMESPACE"
    helm_uninstall_if_exists "gnb$u" "$NAMESPACE"
done

for ((s=10; s<=slice_end; s++)); do
    helm_uninstall_if_exists "nrf$s" "$NAMESPACE"
    helm_uninstall_if_exists "udr$s" "$NAMESPACE"
    helm_uninstall_if_exists "udm$s" "$NAMESPACE"
    helm_uninstall_if_exists "ausf$s" "$NAMESPACE"
    helm_uninstall_if_exists "amf$s" "$NAMESPACE"
    helm_uninstall_if_exists "smf$s" "$NAMESPACE"
    helm_uninstall_if_exists "upf$s" "$NAMESPACE"
done

if [ "$DELETE_MYSQL" = "1" ]; then
    helm_uninstall_if_exists mysql "$NAMESPACE"
fi

success "Cleanup complete"
