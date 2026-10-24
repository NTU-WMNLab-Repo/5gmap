#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="${SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
source "$SCRIPT_DIR/common.sh"
enable_error_trap

USECASE="${1:-zoomv3}"
NUM_USERS="${2:-1}"
NUM_SLICES="${3:-1}"
NUM_ITERATIONS="${4:-1}"
TEST_TYPE="${5:-0}"
NAMESPACE="${NAMESPACE:-oai}"
POD_PROBE="${POD_PROBE:-${pod_probe:-1}}"
SAMPLE_INTERVAL="${SAMPLE_INTERVAL:-5}"
BASELINE_SECONDS="${BASELINE_SECONDS:-15}"
RECOVERY_SECONDS="${RECOVERY_SECONDS:-15}"
IPERF_SECONDS="${IPERF_SECONDS:-20}"

require_commands kubectl python3 timeout
[[ "$NUM_USERS" =~ ^[1-9][0-9]*$ && "$NUM_SLICES" =~ ^[1-9][0-9]*$ &&
   "$NUM_ITERATIONS" =~ ^[1-9][0-9]*$ ]] || die "users, slices and iterations must be positive integers"
[[ "$SAMPLE_INTERVAL" =~ ^[1-9][0-9]*$ && "$BASELINE_SECONDS" =~ ^[1-9][0-9]*$ &&
   "$RECOVERY_SECONDS" =~ ^[1-9][0-9]*$ && "$IPERF_SECONDS" =~ ^[1-9][0-9]*$ ]] ||
    die "sample interval and test durations must be positive integers"
[ "$TEST_TYPE" = "0" ] || die "OAI RAN traffic supports pod-level testing only (TEST_TYPE=0)"
[[ "$POD_PROBE" = 0 || "$POD_PROBE" = 1 ]] || die "POD_PROBE must be 0 or 1"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
LOG_DIR="$ROOT_DIR/5gcore/logs/$USECASE/iperf-cpu/$RUN_ID"
mkdir -p "$LOG_DIR"
SAMPLES="$LOG_DIR/samples.jsonl"
POD_MAP="$LOG_DIR/pods.tsv"
SNAPSHOT_PATH="/api/v1/namespaces/$NAMESPACE/services/http:pod-probe-receiver:8080/proxy/v1/snapshot"
ACTIVE_PID=""
CURRENT_ITERATION=0
CURRENT_PHASE_START=""

cleanup() {
    if [ -n "$ACTIVE_PID" ] && kill -0 "$ACTIVE_PID" 2>/dev/null; then
        kill "$ACTIVE_PID" 2>/dev/null || true
        wait "$ACTIVE_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

if [ "$POD_PROBE" = 1 ]; then
    ready=0
    for ((attempt=1; attempt<=12; attempt++)); do
        if kubectl --request-timeout=8s get --raw "$SNAPSHOT_PATH" >/dev/null 2>&1; then
            ready=1
            break
        fi
        sleep 5
    done
    [ "$ready" = 1 ] || die "probe snapshot did not become available within 60 seconds"
else
    info "POD_PROBE=0: running iperf3 without CPU/RAM sampling"
fi

kubectl get pods -n "$NAMESPACE" -o json | python3 -c '
import json, sys
for pod in json.load(sys.stdin)["items"]:
    meta = pod["metadata"]
    print("\t".join((meta["uid"], meta["name"], pod.get("spec", {}).get("nodeName", ""))))
' > "$POD_MAP"

sample_once() {
    local phase="$1"
    [ "$POD_PROBE" = 1 ] || return 0
    kubectl --request-timeout=8s get --raw "$SNAPSHOT_PATH" | python3 -c '
import json, sys
snapshot = json.load(sys.stdin)
metrics = {"node_cpu_usage_cores", "node_memory_working_set_bytes",
           "os_cpu_busy_percent", "os_memory_available_bytes",
           "pod_cpu_usage_cores", "pod_memory_working_set_bytes",
           "container_cpu_usage_cores", "container_memory_working_set_bytes"}
records = []
for record in snapshot["observations"]:
    metric = record["metric"]
    if metric not in metrics and not (metric.startswith("net_") and metric.endswith("_bytes_rate")):
        continue
    records.append({key: record.get(key) for key in
                    ("subject_kind", "subject_id", "node_uid", "site_id", "metric",
                     "value", "unit", "source", "observed_at", "collected_at")})
print(json.dumps({"generated_at": snapshot["generated_at"], "phase": sys.argv[1],
                  "iteration": int(sys.argv[2]), "phase_started_at": sys.argv[3],
                  "inventory": snapshot["inventory"],
                  "missing": snapshot["missing"], "excluded": snapshot["excluded"],
                  "observations": records}, separators=(",", ":")))
' "$phase" "$CURRENT_ITERATION" "$CURRENT_PHASE_START" >> "$SAMPLES"
}

sample_for_seconds() {
    local phase="$1" duration="$2" deadline
    [ "$POD_PROBE" = 1 ] || return 0
    CURRENT_PHASE_START="$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)"
    deadline=$((SECONDS + duration))
    while [ "$SECONDS" -lt "$deadline" ]; do
        sample_once "$phase" || die "probe snapshot sampling failed during $phase"
        sleep "$SAMPLE_INTERVAL"
    done
}

run_iperf_phase() {
    local phase="$1" log_file="$2" result
    shift 2
    CURRENT_PHASE_START="$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)"
    timeout "$((IPERF_SECONDS + 15))s" "$@" > "$log_file" 2>&1 &
    ACTIVE_PID=$!
    while kill -0 "$ACTIVE_PID" 2>/dev/null; do
        sample_once "$phase" || die "probe snapshot sampling failed during $phase"
        sleep "$SAMPLE_INTERVAL"
    done
    result=0
    wait "$ACTIVE_PID" || result=$?
    ACTIVE_PID=""
    cat "$log_file"
    return "$result"
}

start_iperf_server() {
    local dnn_pod="$1" dnn_ip="$2"
    kubectl exec -n "$NAMESPACE" "$dnn_pod" -- sh -c \
        "pkill iperf3 2>/dev/null || true; iperf3 -s -B $dnn_ip -D"
    sleep 2
}

summarize_samples() {
    [ "$POD_PROBE" = 1 ] || return 0
    python3 - "$SAMPLES" "$POD_MAP" > "$LOG_DIR/cpu-memory-summary.tsv" <<'PY'
import collections
from datetime import datetime
import json
import statistics
import sys

samples_path, pod_map_path = sys.argv[1:]
pod_names = {}
with open(pod_map_path, encoding="utf-8") as handle:
    for line in handle:
        uid, name, _node = line.rstrip("\n").split("\t", 2)
        pod_names[uid] = name

values = collections.defaultdict(lambda: collections.defaultdict(list))
seen = set()
with open(samples_path, encoding="utf-8") as handle:
    for line in handle:
        sample = json.loads(line)
        phase_start = datetime.fromisoformat(sample["phase_started_at"].replace("Z", "+00:00"))
        for record in sample["observations"]:
            metric = record["metric"]
            if not metric.endswith(("cpu_usage_cores", "memory_working_set_bytes")):
                continue
            kind, subject = record["subject_kind"], record["subject_id"]
            source_time = record.get("observed_at") or record["collected_at"]
            if datetime.fromisoformat(source_time.replace("Z", "+00:00")) < phase_start:
                continue
            sample_key = (kind, subject, metric, sample["phase"], sample["iteration"], source_time)
            if sample_key in seen:
                continue
            seen.add(sample_key)
            if kind == "node":
                label = record.get("site_id") or subject
            else:
                pod_name = pod_names.get(subject.split("/")[0], "")
                if not pod_name.startswith(("oai-nr-ue", "oai-dnn", "oai-gnb-cu", "oai-gnb-du")):
                    continue
                label = pod_name + ("/" + subject.split("/", 1)[1] if "/" in subject else "")
            unit = "MiB" if metric.endswith("memory_working_set_bytes") else "cores"
            value = float(record["value"]) / (1024 * 1024) if unit == "MiB" else float(record["value"])
            values[(kind, label, metric, unit)][sample["phase"]].append(value)

phases = ("baseline", "dl", "dl_recovery", "ul", "ul_recovery")
print("\t".join(("kind", "name", "metric", "unit") +
                tuple(column for phase in phases for column in (phase + "_n", phase + "_mean"))))
for key in sorted(values):
    cells = list(key)
    for phase in phases:
        phase_values = values[key][phase]
        cells.extend((str(len(phase_values)),
                      f"{statistics.mean(phase_values):.3f}" if phase_values else ""))
    print("\t".join(cells))
PY
}

info "iperf3 CPU/RAM test; output: $LOG_DIR"
total=$((NUM_USERS * NUM_SLICES))
for ((offset=0; offset<total; offset++)); do
    u=$((10 + offset))
    index=$((offset + 1))
    dnn_pod="$(pod_by_prefix "$NAMESPACE" "oai-dnn$u")"
    ue_pod="$(pod_by_prefix "$NAMESPACE" "oai-nr-ue$u")"
    [ -n "$dnn_pod" ] || die "Cannot find DNN pod oai-dnn$u"
    [ -n "$ue_pod" ] || die "Cannot find NR UE pod oai-nr-ue$u"
    exec_has "$NAMESPACE" "$dnn_pod" "" iperf3 || die "iperf3 missing in $dnn_pod"
    exec_has "$NAMESPACE" "$ue_pod" nr-ue iperf3 || die "iperf3 missing in $ue_pod"
    dnn_ip="$(get_pod_ip "$NAMESPACE" "$dnn_pod")"
    ue_ip="$(kubectl exec -n "$NAMESPACE" "$ue_pod" -c nr-ue -- \
        ip -4 -o addr show oaitun_ue1 | awk '{split($4, a, "/"); print a[1]}')"
    [ -n "$ue_ip" ] || die "Cannot find oaitun_ue1 IPv4 in $ue_pod"
    kubectl exec -n "$NAMESPACE" "$ue_pod" -c nr-ue -- \
        ping -I oaitun_ue1 -c 3 "$dnn_ip" > "$LOG_DIR/ping.$index.txt"

    for ((iteration=1; iteration<=NUM_ITERATIONS; iteration++)); do
        CURRENT_ITERATION=$iteration
        info "UE $index, iteration $iteration: baseline"
        sample_for_seconds baseline "$BASELINE_SECONDS"

        start_iperf_server "$dnn_pod" "$dnn_ip"
        info "UE $index, iteration $iteration: DL iperf3"
        dl_log="$LOG_DIR/throughput.DL.$index.$iteration.txt"
        if ! run_iperf_phase dl "$dl_log" kubectl exec -n "$NAMESPACE" "$ue_pod" -c nr-ue -- \
            iperf3 -c "$dnn_ip" -B "$ue_ip" -t "$IPERF_SECONDS" -R; then
            info "DL retry with MSS 1300"
            run_iperf_phase dl "$LOG_DIR/throughput.DL.$index.$iteration.retry.txt" \
                kubectl exec -n "$NAMESPACE" "$ue_pod" -c nr-ue -- \
                iperf3 -c "$dnn_ip" -B "$ue_ip" -t "$IPERF_SECONDS" -R -M 1300
        fi
        sample_for_seconds dl_recovery "$RECOVERY_SECONDS"

        start_iperf_server "$dnn_pod" "$dnn_ip"
        info "UE $index, iteration $iteration: UL iperf3"
        run_iperf_phase ul "$LOG_DIR/throughput.UL.$index.$iteration.txt" \
            kubectl exec -n "$NAMESPACE" "$ue_pod" -c nr-ue -- \
            iperf3 -c "$dnn_ip" -B "$ue_ip" -t "$IPERF_SECONDS"
        sample_for_seconds ul_recovery "$RECOVERY_SECONDS"
    done
done

summarize_samples
success "iperf3 test complete; logs: $LOG_DIR"
