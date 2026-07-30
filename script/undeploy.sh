#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"
enable_error_trap

NUM_USERS="${1:-1}"
NUM_SLICES="${2:-1}"
NAMESPACE="${NAMESPACE:-oai}"
DELETE_MYSQL="${DELETE_MYSQL:-0}"
CLEAR_JAEGER_DATA="${CLEAR_JAEGER_DATA:-0}"
JAEGER_NAMESPACE="${JAEGER_NAMESPACE:-jaeger}"

require_commands kubectl helm

info "Cleaning 5GMAP OAI RAN deployment"

slice_end=$((NUM_SLICES + 9))
total=$((NUM_USERS * NUM_SLICES))

for ((offset=0; offset<total; offset++)); do
    u=$((10 + offset))
    kubectl delete deployment "oai-dnn$u" -n "$NAMESPACE" --ignore-not-found=true
    helm_uninstall_if_exists "nrue$u" "$NAMESPACE"
    helm_uninstall_if_exists "gnbdu$u" "$NAMESPACE"
    kubectl delete deployment "f1proxy$u" -n "$NAMESPACE" --ignore-not-found=true
    kubectl delete service "f1proxy$u" -n "$NAMESPACE" --ignore-not-found=true
    kubectl delete deployment "oai-f1ap-proxy$u" -n "$NAMESPACE" --ignore-not-found=true
    kubectl delete service "oai-f1ap-proxy$u" -n "$NAMESPACE" --ignore-not-found=true
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

if [ "$CLEAR_JAEGER_DATA" = "1" ]; then
    info "Clearing Jaeger trace data by restarting deployment/jaeger in namespace $JAEGER_NAMESPACE"
    if kubectl get deployment jaeger -n "$JAEGER_NAMESPACE" >/dev/null 2>&1; then
        kubectl rollout restart deployment/jaeger -n "$JAEGER_NAMESPACE"
        kubectl rollout status deployment/jaeger -n "$JAEGER_NAMESPACE" --timeout=120s
    else
        info "Jaeger deployment not found in namespace $JAEGER_NAMESPACE; skipping"
    fi
fi

success "Cleanup complete"
