#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

USECASE="${USECASE:-zoomv3}"
NUM_USERS="${NUM_USERS:-1}"
NUM_SLICES="${NUM_SLICES:-1}"
NUM_ITERATIONS="${NUM_ITERATIONS:-1}"
TEST_TYPE="${TEST_TYPE:-0}"
AUTO_CLEANUP="${AUTO_CLEANUP:-0}"

info "Starting 5GMAP with OAI RAN"
info "usecase=${USECASE}, users=${NUM_USERS}, slices=${NUM_SLICES}, iterations=${NUM_ITERATIONS}, test_type=${TEST_TYPE}"

"$SCRIPT_DIR/deploy.sh" \
    "$USECASE" \
    "$NUM_USERS" \
    "$NUM_SLICES"

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
