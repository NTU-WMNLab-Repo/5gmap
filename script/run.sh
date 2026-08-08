#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"
enable_error_trap

USECASE="${USECASE:-zoomv3}"
NUM_USERS="${NUM_USERS:-1}"
NUM_SLICES="${NUM_SLICES:-1}"
NUM_ITERATIONS="${NUM_ITERATIONS:-1}"
TEST_TYPE="${TEST_TYPE:-0}"
AUTO_CLEANUP="${AUTO_CLEANUP:-0}"
RUN_MODE="${RUN_MODE:-rfsim}"
DEPLOY_UE="${DEPLOY_UE:-${DeployUE:-1}}"
RAN_PROXY="${RAN_PROXY:-${RanProxy:-0}}"
CROSS_PROTOCOL_CORRELATE="${CROSS_PROTOCOL_CORRELATE:-${CrossProtocolCorrelate:-0}}"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --run_mode|--run-mode|--runmode)
            shift
            [ "$#" -gt 0 ] || die "Missing value for --run_mode"
            RUN_MODE="$1"
            ;;
        --run_mode=*|--run-mode=*|--runmode=*)
            RUN_MODE="${1#*=}"
            ;;
        run_mode=*|runmode=*)
            RUN_MODE="${1#*=}"
            ;;
        --DeployUE|--deploy_ue|--deploy-ue)
            opt="$1"
            shift
            [ "$#" -gt 0 ] || die "Missing value for $opt"
            DEPLOY_UE="$1"
            ;;
        --DeployUE=*|--deploy_ue=*|--deploy-ue=*)
            DEPLOY_UE="${1#*=}"
            ;;
        DeployUE=*|deployUE=*|deploy_ue=*)
            DEPLOY_UE="${1#*=}"
            ;;
        --RanProxy|--ran_proxy|--ran-proxy)
            opt="$1"
            shift
            [ "$#" -gt 0 ] || die "Missing value for $opt"
            RAN_PROXY="$1"
            ;;
        --RanProxy=*|--ran_proxy=*|--ran-proxy=*)
            RAN_PROXY="${1#*=}"
            ;;
        RanProxy=*|ranProxy=*|ran_proxy=*)
            RAN_PROXY="${1#*=}"
            ;;
        --CrossProtocolCorrelate|--cross_protocol_correlate|--cross-protocol-correlate)
            opt="$1"
            shift
            [ "$#" -gt 0 ] || die "Missing value for $opt"
            CROSS_PROTOCOL_CORRELATE="$1"
            ;;
        --CrossProtocolCorrelate=*|--cross_protocol_correlate=*|--cross-protocol-correlate=*)
            CROSS_PROTOCOL_CORRELATE="${1#*=}"
            ;;
        CrossProtocolCorrelate=*|crossProtocolCorrelate=*|cross_protocol_correlate=*)
            CROSS_PROTOCOL_CORRELATE="${1#*=}"
            ;;
        *)
            die "Unknown argument: $1"
            ;;
    esac
    shift
done

case "$RUN_MODE" in
    rfsim|usrp|usrpb210)
        ;;
    *)
        die "Unsupported run_mode '$RUN_MODE'. Supported values: rfsim, usrp, usrpb210"
        ;;
esac

case "$DEPLOY_UE" in
    0|1)
        ;;
    *)
        die "Unsupported DeployUE '$DEPLOY_UE'. Supported values: 0, 1"
        ;;
esac

case "$RAN_PROXY" in
    0|1)
        ;;
    *)
        die "Unsupported RanProxy '$RAN_PROXY'. Supported values: 0, 1"
        ;;
esac

case "$CROSS_PROTOCOL_CORRELATE" in
    0|1)
        ;;
    *)
        die "Unsupported CrossProtocolCorrelate '$CROSS_PROTOCOL_CORRELATE'. Supported values: 0, 1"
        ;;
esac

if [ "$CROSS_PROTOCOL_CORRELATE" = "1" ] && [ "$RAN_PROXY" != "1" ]; then
    die "CrossProtocolCorrelate=1 requires RanProxy=1"
fi

info "Starting 5GMAP with OAI RAN"
info "usecase=${USECASE}, users=${NUM_USERS}, slices=${NUM_SLICES}, iterations=${NUM_ITERATIONS}, test_type=${TEST_TYPE}, run_mode=${RUN_MODE}, DeployUE=${DEPLOY_UE}, RanProxy=${RAN_PROXY}, CrossProtocolCorrelate=${CROSS_PROTOCOL_CORRELATE}"

"$SCRIPT_DIR/deploy.sh" \
    "$USECASE" \
    "$NUM_USERS" \
    "$NUM_SLICES" \
    "$RUN_MODE" \
    "$DEPLOY_UE" \
    "$RAN_PROXY" \
    "$CROSS_PROTOCOL_CORRELATE"

if [ "$DEPLOY_UE" = "1" ]; then
    "$SCRIPT_DIR/start_traffic.sh" \
        "$USECASE" \
        "$NUM_USERS" \
        "$NUM_SLICES" \
        "$NUM_ITERATIONS" \
        "$TEST_TYPE"
else
    info "DeployUE=0; skipping traffic tests because NR-UE and DNN were not deployed"
fi

if [ "$AUTO_CLEANUP" = "1" ]; then
    "$SCRIPT_DIR/undeploy.sh" "$NUM_USERS" "$NUM_SLICES"
else
    read -r -p "Press ENTER to cleanup, or Ctrl-C to keep the deployment running..."
    "$SCRIPT_DIR/undeploy.sh" "$NUM_USERS" "$NUM_SLICES"
fi

success "Experiment finished"
