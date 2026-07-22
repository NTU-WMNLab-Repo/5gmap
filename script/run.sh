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

while [ "$#" -gt 0 ]; do
    case "$1" in
        --run_mode|--run-mode)
            shift
            [ "$#" -gt 0 ] || die "Missing value for --run_mode"
            RUN_MODE="$1"
            ;;
        --run_mode=*|--run-mode=*)
            RUN_MODE="${1#*=}"
            ;;
        run_mode=*)
            RUN_MODE="${1#*=}"
            ;;
        *)
            die "Unknown argument: $1"
            ;;
    esac
    shift
done

case "$RUN_MODE" in
    rfsim|usrpb210)
        ;;
    *)
        die "Unsupported run_mode '$RUN_MODE'. Supported values: rfsim, usrpb210"
        ;;
esac

info "Starting 5GMAP with OAI RAN"
info "usecase=${USECASE}, users=${NUM_USERS}, slices=${NUM_SLICES}, iterations=${NUM_ITERATIONS}, test_type=${TEST_TYPE}, run_mode=${RUN_MODE}"

"$SCRIPT_DIR/deploy.sh" \
    "$USECASE" \
    "$NUM_USERS" \
    "$NUM_SLICES" \
    "$RUN_MODE"

"$SCRIPT_DIR/start_traffic.sh" \
    "$USECASE" \
    "$NUM_USERS" \
    "$NUM_SLICES" \
    "$NUM_ITERATIONS" \
    "$TEST_TYPE"

if [ "$AUTO_CLEANUP" = "1" ]; then
    "$SCRIPT_DIR/undeploy.sh" "$NUM_USERS" "$NUM_SLICES"
else
    read -r -p "Press ENTER to cleanup, or Ctrl-C to keep the deployment running..."
    "$SCRIPT_DIR/undeploy.sh" "$NUM_USERS" "$NUM_SLICES"
fi

success "Experiment finished"
