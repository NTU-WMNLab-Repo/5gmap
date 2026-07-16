#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
source "$SCRIPT_DIR/common.sh"

USECASE="${1:-zoomv3}"
NUM_USERS="${2:-1}"
NUM_SLICES="${3:-1}"
NUM_ITERATIONS="${4:-1}"
TEST_TYPE="${5:-0}"
NAMESPACE="${NAMESPACE:-oai}"

LOG_DIR="$ROOT_DIR/5gcore/logs/$USECASE/throughput"
mkdir -p "$LOG_DIR"

if [ "$TEST_TYPE" != "0" ]; then
    die "OAI RAN traffic currently supports pod-level testing only. Set TEST_TYPE=0."
fi

require_commands kubectl awk sed grep

run_ping_test() {
    local dnn_pod="$1"
    local ue_ip="$2"
    local index="$3"
    local log="$LOG_DIR/ping.$index.log.txt"

    info "Ping test: $dnn_pod -> $ue_ip"
    kubectl exec -n "$NAMESPACE" "$dnn_pod" -- ping -c 5 "$ue_ip" | tee "$log"

    local loss
    loss="$(awk -F',' '/packet loss/ {gsub(/^[ \t]+|[ \t]+$/, "", $3); print $3}' "$log")"
    success "Ping result for test $index: ${loss:-see $log}"
}

run_iperf_test() {
    local dnn_pod="$1"
    local ue_pod="$2"
    local dnn_ip="$3"
    local ue_ip="$4"
    local index="$5"

    local dl_log="$LOG_DIR/throughput.DL.$index.log.txt"
    local ul_log="$LOG_DIR/throughput.UL.$index.log.txt"
    local ite

    if ! exec_has "$NAMESPACE" "$dnn_pod" "" iperf3; then
        info "Skipping iperf3 for $dnn_pod: iperf3 is not installed"
        return 0
    fi

    if ! exec_has "$NAMESPACE" "$ue_pod" nr-ue iperf3; then
        info "Skipping iperf3 for $ue_pod: iperf3 is not installed in nr-ue"
        return 0
    fi

    for ((ite=1; ite<=NUM_ITERATIONS; ite++)); do
        info "DL iperf3 test $index.$ite: $dnn_pod -> $ue_ip"
        kubectl exec -n "$NAMESPACE" "$ue_pod" -c nr-ue -- sh -c "pkill iperf3 2>/dev/null || true; iperf3 -s -B $ue_ip -D"
        sleep 2
        kubectl exec -n "$NAMESPACE" "$dnn_pod" -- iperf3 -c "$ue_ip" -t 20 | tee -a "$dl_log"

        info "UL iperf3 test $index.$ite: $ue_pod -> $dnn_ip"
        kubectl exec -n "$NAMESPACE" "$dnn_pod" -- sh -c "pkill iperf3 2>/dev/null || true; iperf3 -s -B $dnn_ip -D"
        sleep 2
        kubectl exec -n "$NAMESPACE" "$ue_pod" -c nr-ue -- iperf3 -c "$dnn_ip" -t 20 | tee -a "$ul_log"
    done
}

info "Starting OAI RAN traffic tests"
total=$((NUM_USERS * NUM_SLICES))
ue_ip_suffix=2

for ((offset=0; offset<total; offset++)); do
    u=$((10 + offset))
    test_index=$((offset + 1))
    ue_ip="12.1.1.$ue_ip_suffix"

    dnn_pod="$(pod_by_prefix "$NAMESPACE" "oai-dnn$u")"
    ue_pod="$(pod_by_prefix "$NAMESPACE" "oai-nr-ue$u")"

    [ -n "$dnn_pod" ] || die "Cannot find DNN pod oai-dnn$u"
    [ -n "$ue_pod" ] || die "Cannot find NR UE pod oai-nr-ue$u"

    dnn_ip="$(get_pod_ip "$NAMESPACE" "$dnn_pod")"

    run_ping_test "$dnn_pod" "$ue_ip" "$test_index"
    run_iperf_test "$dnn_pod" "$ue_pod" "$dnn_ip" "$ue_ip" "$test_index"

    ue_ip_suffix=$((ue_ip_suffix + 1))
done

success "Traffic tests complete. Logs are in $LOG_DIR"
