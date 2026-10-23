#!/usr/bin/env bash
set -euo pipefail

PROBE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${NAMESPACE:-oai}"
POD_PROBE_IMAGE="${POD_PROBE_IMAGE:-python:3.12-slim}"

case "$NAMESPACE" in
    *[!a-z0-9-]*|"") echo "Invalid namespace: $NAMESPACE" >&2; exit 1 ;;
esac
case "$POD_PROBE_IMAGE" in
    *[!a-zA-Z0-9_./:@-]*|"") echo "Invalid POD_PROBE_IMAGE" >&2; exit 1 ;;
esac

kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 || kubectl create namespace "$NAMESPACE"
kubectl create configmap pod-probe-code -n "$NAMESPACE" \
    --from-file="$PROBE_DIR/src/common.py" \
    --from-file="$PROBE_DIR/src/receiver.py" \
    --from-file="$PROBE_DIR/src/cluster_probe.py" \
    --from-file="$PROBE_DIR/src/node_probe.py" \
    --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap pod-probe-fixtures -n "$NAMESPACE" \
    --from-file=fixtures.json="$PROBE_DIR/config/fixtures.json" \
    --dry-run=client -o yaml | kubectl apply -f -
sed -e "s/namespace: oai/namespace: $NAMESPACE/g" \
    -e "s|__POD_PROBE_IMAGE__|$POD_PROBE_IMAGE|g" \
    "$PROBE_DIR/deploy/resources.yaml" | kubectl apply -n "$NAMESPACE" -f -
kubectl rollout restart deployment/pod-probe-receiver -n "$NAMESPACE"
kubectl rollout restart deployment/pod-probe-cluster -n "$NAMESPACE"
kubectl rollout restart daemonset/pod-probe-node -n "$NAMESPACE"
kubectl rollout status deployment/pod-probe-receiver -n "$NAMESPACE" --timeout=180s
kubectl rollout status deployment/pod-probe-cluster -n "$NAMESPACE" --timeout=180s
kubectl rollout status daemonset/pod-probe-node -n "$NAMESPACE" --timeout=180s
