#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-oai}"
kubectl delete daemonset pod-probe-node -n "$NAMESPACE" --ignore-not-found=true
kubectl delete deployment pod-probe-cluster pod-probe-receiver -n "$NAMESPACE" --ignore-not-found=true
kubectl delete service pod-probe-receiver -n "$NAMESPACE" --ignore-not-found=true
kubectl delete serviceaccount pod-probe-cluster pod-probe-node -n "$NAMESPACE" --ignore-not-found=true
kubectl delete configmap pod-probe-code pod-probe-fixtures -n "$NAMESPACE" --ignore-not-found=true
kubectl delete clusterrolebinding pod-probe-cluster pod-probe-node --ignore-not-found=true
kubectl delete clusterrole pod-probe-cluster pod-probe-node --ignore-not-found=true
