#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
CORE_DIR="$ROOT_DIR/5gcore"
RAN_DIR="$ROOT_DIR/oai-5g-ran"

source "$SCRIPT_DIR/common.sh"
enable_error_trap

USECASE="${USECASE:-zoomv3}"
NUM_USERS="${NUM_USERS:-1}"
NUM_SLICES="${NUM_SLICES:-1}"
RUN_MODE="${RUN_MODE:-rfsim}"
DEPLOY_UE="${DEPLOY_UE:-${DeployUE:-1}}"
RAN_PROXY="${RAN_PROXY:-${RanProxy:-0}}"
CROSS_PROTOCOL_CORRELATE="${CROSS_PROTOCOL_CORRELATE:-${CrossProtocolCorrelate:-0}}"

positional_args=()
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
        --*)
            die "Unknown argument: $1"
            ;;
        *)
            positional_args+=("$1")
            ;;
    esac
    shift
done

[ "${#positional_args[@]}" -le 7 ] || die "Too many positional arguments"
if [ "${#positional_args[@]}" -ge 1 ]; then USECASE="${positional_args[0]}"; fi
if [ "${#positional_args[@]}" -ge 2 ]; then NUM_USERS="${positional_args[1]}"; fi
if [ "${#positional_args[@]}" -ge 3 ]; then NUM_SLICES="${positional_args[2]}"; fi
if [ "${#positional_args[@]}" -ge 4 ]; then RUN_MODE="${positional_args[3]}"; fi
if [ "${#positional_args[@]}" -ge 5 ]; then DEPLOY_UE="${positional_args[4]}"; fi
if [ "${#positional_args[@]}" -ge 6 ]; then RAN_PROXY="${positional_args[5]}"; fi
if [ "${#positional_args[@]}" -ge 7 ]; then CROSS_PROTOCOL_CORRELATE="${positional_args[6]}"; fi

NAMESPACE="${NAMESPACE:-oai}"
OPMODE="${OPMODE:-OTEL}"
LOGLEVEL="${LOGLEVEL:-trace}"
PROXY_PORT="${PROXY_PORT:-11095}"
SERVICE_PORT="${SERVICE_PORT:-8080}"
PROXY_VERSION="${PROXY_VERSION:-7.0.0}"
RAN_PROXY_F1AP_IMAGE="${RAN_PROXY_F1AP_IMAGE:-docker.io/genechen0203/f1ap-sctp-proxy:latest}"
RAN_PROXY_OTEL_ENDPOINT="${RAN_PROXY_OTEL_ENDPOINT:-http://opentelemetry-collector.otel.svc.cluster.local:4317}"
RAN_PROXY_OTEL_INSECURE="${RAN_PROXY_OTEL_INSECURE:-true}"
RAN_PROXY_F1C_PORT="${RAN_PROXY_F1C_PORT:-38472}"
RAN_PROXY_NGAP_IMAGE="${RAN_PROXY_NGAP_IMAGE:-docker.io/genechen0203/ngap-sctp-proxy:latest}"
RAN_PROXY_NGAP_PORT="${RAN_PROXY_NGAP_PORT:-38412}"
RAN_PROXY_DIR="$RAN_DIR/f1-proxy"
RAN_PROXY_MANIFEST="${RAN_PROXY_MANIFEST:-$RAN_PROXY_DIR/oai-f1ap-proxy.yaml}"
RAN_PROXY_TEMPLATE_SOURCE="$ROOT_DIR/control-plane-tracing/src/proxies/f1ap-sctp-proxy/k8s-example.yaml"
RAN_PROXY_NGAP_DIR="$RAN_DIR/ngap-proxy"
RAN_PROXY_NGAP_MANIFEST="${RAN_PROXY_NGAP_MANIFEST:-$RAN_PROXY_NGAP_DIR/oai-ngap-proxy.yaml}"
RAN_PROXY_NGAP_TEMPLATE_SOURCE="$ROOT_DIR/control-plane-tracing/src/proxies/ngap-sctp-proxy/k8s-example.yaml"
RAN_PROXY_PFCP_IMAGE="${RAN_PROXY_PFCP_IMAGE:-docker.io/genechen0203/pfcp-udp-proxy:latest}"
RAN_PROXY_PFCP_PORT="${RAN_PROXY_PFCP_PORT:-8805}"
RAN_PROXY_PFCP_DIR="$CORE_DIR/pfcp-proxy"
RAN_PROXY_PFCP_MANIFEST="${RAN_PROXY_PFCP_MANIFEST:-$RAN_PROXY_PFCP_DIR/oai-pfcp-udp-proxy.yaml}"
RAN_PROXY_PFCP_TEMPLATE_SOURCE="$ROOT_DIR/control-plane-tracing/src/proxies/pfcp-udp-proxy/k8s-example.yaml"
CROSS_PROTOCOL_CORRELATOR_IMAGE="${CROSS_PROTOCOL_CORRELATOR_IMAGE:-docker.io/genechen0203/control-plane-correlator:latest}"
CROSS_PROTOCOL_CORRELATOR_ENDPOINT="${CROSS_PROTOCOL_CORRELATOR_ENDPOINT:-http://control-plane-correlator:8080}"
CROSS_PROTOCOL_CORRELATOR_DIR="$RAN_DIR/control-plane-correlator"
CROSS_PROTOCOL_CORRELATOR_MANIFEST="${CROSS_PROTOCOL_CORRELATOR_MANIFEST:-$CROSS_PROTOCOL_CORRELATOR_DIR/oai-control-plane-correlator.yaml}"
CROSS_PROTOCOL_CORRELATOR_TEMPLATE_SOURCE="$ROOT_DIR/control-plane-tracing/src/correlator/online/k8s-example.yaml"

NRF_LOC="${NRF_LOC:-az}"
UDR_LOC="${UDR_LOC:-az}"
UDM_LOC="${UDM_LOC:-az}"
AUSF_LOC="${AUSF_LOC:-az}"
AMF_LOC="${AMF_LOC:-az}"
SMF_LOC="${SMF_LOC:-az}"
UPF_LOC="${UPF_LOC:-az}"
RAN_LOC="${RAN_LOC:-edge}"
DNN_LOC="${DNN_LOC:-az}"
CORE_LOC="${CORE_LOC:-az}"

require_commands kubectl helm sed awk grep

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

ran_usrp_type() {
    case "$1" in
        rfsim) echo "rfsim" ;;
        usrp|usrpb210) echo "b2xx" ;;
    esac
}

deploy_cross_protocol_correlator() {
    local deployment_exists=0
    local rendered_manifest

    info "Deploying experimental online cross-protocol correlator"

    mkdir -p "$CROSS_PROTOCOL_CORRELATOR_DIR"
    if [ ! -f "$CROSS_PROTOCOL_CORRELATOR_MANIFEST" ]; then
        info "Creating correlator manifest from $CROSS_PROTOCOL_CORRELATOR_TEMPLATE_SOURCE"
        cp "$CROSS_PROTOCOL_CORRELATOR_TEMPLATE_SOURCE" "$CROSS_PROTOCOL_CORRELATOR_MANIFEST"
    fi

    rendered_manifest="$(mktemp)"
    cp "$CROSS_PROTOCOL_CORRELATOR_MANIFEST" "$rendered_manifest"
    set_yaml_value "$rendered_manifest" image "$CROSS_PROTOCOL_CORRELATOR_IMAGE"
    set_yaml_value "$rendered_manifest" imagePullPolicy "Always"

    if kubectl get deployment control-plane-correlator -n "$NAMESPACE" >/dev/null 2>&1; then
        deployment_exists=1
    fi

    kubectl apply -n "$NAMESPACE" -f "$rendered_manifest"
    rm -f "$rendered_manifest"

    if [ "$deployment_exists" = "1" ]; then
        info "Restarting the correlator to clear state from the previous deployment run"
        kubectl rollout restart deployment/control-plane-correlator -n "$NAMESPACE"
        kubectl rollout status deployment/control-plane-correlator -n "$NAMESPACE" --timeout=300s
    fi

    wait_for_pod "$NAMESPACE" "control-plane-correlator" 300 10
}

remove_cross_protocol_correlator() {
    info "CrossProtocolCorrelate=0; ensuring the online correlator is not deployed"
    kubectl delete deployment control-plane-correlator -n "$NAMESPACE" --ignore-not-found=true
    kubectl delete service control-plane-correlator -n "$NAMESPACE" --ignore-not-found=true
}

deploy_ran_proxy_user() {
    local u="$1"
    local cu_ip="$2"
    local proxy_name="f1proxy$u"
    local online_endpoint=""
    local rendered_manifest

    if [ "$CROSS_PROTOCOL_CORRELATE" = "1" ]; then
        online_endpoint="$CROSS_PROTOCOL_CORRELATOR_ENDPOINT"
    fi

    info "Deploying experimental F1AP tracing proxy $proxy_name for CU $cu_ip"

    mkdir -p "$RAN_PROXY_DIR"
    if [ ! -f "$RAN_PROXY_MANIFEST" ]; then
        info "Creating RAN proxy manifest from $RAN_PROXY_TEMPLATE_SOURCE"
        cp "$RAN_PROXY_TEMPLATE_SOURCE" "$RAN_PROXY_MANIFEST"
    fi

    rendered_manifest="$(mktemp)"
    cp "$RAN_PROXY_MANIFEST" "$rendered_manifest"

    sed -i \
        -e "s|__PROXY_NAME__|$proxy_name|g" \
        -e "s|__CU_HOST__|$cu_ip|g" \
        -e "s|__F1C_PORT__|$RAN_PROXY_F1C_PORT|g" \
        -e "s|__RAN_LOC__|$RAN_LOC|g" \
        -e "s|__OTEL_ENDPOINT__|$RAN_PROXY_OTEL_ENDPOINT|g" \
        -e "s|__OTEL_INSECURE__|$RAN_PROXY_OTEL_INSECURE|g" \
        -e "s|__ONLINE_CORRELATION_ENABLED__|$CROSS_PROTOCOL_CORRELATE|g" \
        -e "s|__ONLINE_CORRELATION_ENDPOINT__|$online_endpoint|g" \
        "$rendered_manifest"

    set_yaml_value "$rendered_manifest" image "$RAN_PROXY_F1AP_IMAGE"
    set_yaml_value "$rendered_manifest" imagePullPolicy "Always"

    kubectl apply -n "$NAMESPACE" -f "$rendered_manifest"
    rm -f "$rendered_manifest"

    wait_for_pod "$NAMESPACE" "$proxy_name" 300 10
}

deploy_ngap_proxy_user() {
    local u="$1"
    local amf_ip="$2"
    local proxy_name="ngapproxy$u"
    local online_endpoint=""
    local rendered_manifest

    if [ "$CROSS_PROTOCOL_CORRELATE" = "1" ]; then
        online_endpoint="$CROSS_PROTOCOL_CORRELATOR_ENDPOINT"
    fi

    info "Deploying experimental NGAP tracing proxy $proxy_name for AMF $amf_ip"

    mkdir -p "$RAN_PROXY_NGAP_DIR"
    if [ ! -f "$RAN_PROXY_NGAP_MANIFEST" ]; then
        info "Creating NGAP proxy manifest from $RAN_PROXY_NGAP_TEMPLATE_SOURCE"
        cp "$RAN_PROXY_NGAP_TEMPLATE_SOURCE" "$RAN_PROXY_NGAP_MANIFEST"
    fi

    rendered_manifest="$(mktemp)"
    cp "$RAN_PROXY_NGAP_MANIFEST" "$rendered_manifest"

    sed -i \
        -e "s|__PROXY_NAME__|$proxy_name|g" \
        -e "s|__AMF_HOST__|$amf_ip|g" \
        -e "s|__NGAP_PORT__|$RAN_PROXY_NGAP_PORT|g" \
        -e "s|__RAN_LOC__|$RAN_LOC|g" \
        -e "s|__OTEL_ENDPOINT__|$RAN_PROXY_OTEL_ENDPOINT|g" \
        -e "s|__OTEL_INSECURE__|$RAN_PROXY_OTEL_INSECURE|g" \
        -e "s|__ONLINE_CORRELATION_ENABLED__|$CROSS_PROTOCOL_CORRELATE|g" \
        -e "s|__ONLINE_CORRELATION_ENDPOINT__|$online_endpoint|g" \
        "$rendered_manifest"

    set_yaml_value "$rendered_manifest" image "$RAN_PROXY_NGAP_IMAGE"
    set_yaml_value "$rendered_manifest" imagePullPolicy "Always"

    kubectl apply -n "$NAMESPACE" -f "$rendered_manifest"
    rm -f "$rendered_manifest"

    wait_for_pod "$NAMESPACE" "$proxy_name" 300 10
}

deploy_pfcp_proxy_slice() {
    local s="$1"
    local proxy_name="pfcpproxy$s"
    local upf_host="oai-spgwu-tiny$s-svc"
    local smf_host="oai-smf$s-svc"
    local rendered_manifest

    info "Deploying experimental PFCP tracing proxy $proxy_name for SMF $smf_host and UPF $upf_host"

    mkdir -p "$RAN_PROXY_PFCP_DIR"
    if [ ! -f "$RAN_PROXY_PFCP_MANIFEST" ]; then
        info "Creating PFCP proxy manifest from $RAN_PROXY_PFCP_TEMPLATE_SOURCE"
        cp "$RAN_PROXY_PFCP_TEMPLATE_SOURCE" "$RAN_PROXY_PFCP_MANIFEST"
    fi

    rendered_manifest="$(mktemp)"
    cp "$RAN_PROXY_PFCP_MANIFEST" "$rendered_manifest"

    sed -i \
        -e "s|__PROXY_NAME__|$proxy_name|g" \
        -e "s|__UPF_HOST__|$upf_host|g" \
        -e "s|__SMF_HOST__|$smf_host|g" \
        -e "s|__PFCP_PORT__|$RAN_PROXY_PFCP_PORT|g" \
        -e "s|__CORE_LOC__|$CORE_LOC|g" \
        -e "s|__OTEL_ENDPOINT__|$RAN_PROXY_OTEL_ENDPOINT|g" \
        -e "s|__OTEL_INSECURE__|$RAN_PROXY_OTEL_INSECURE|g" \
        "$rendered_manifest"

    set_yaml_value "$rendered_manifest" image "$RAN_PROXY_PFCP_IMAGE"
    set_yaml_value "$rendered_manifest" imagePullPolicy "Always"

    kubectl apply -n "$NAMESPACE" -f "$rendered_manifest"
    rm -f "$rendered_manifest"

    wait_for_pod "$NAMESPACE" "$proxy_name" 300 10
}

pfcp_proxy_service_ip() {
    local s="$1"
    local proxy_name="pfcpproxy$s"
    local cluster_ip

    cluster_ip="$(kubectl get service "$proxy_name" -n "$NAMESPACE" -o jsonpath='{.spec.clusterIP}')"
    if [ -z "$cluster_ip" ] || [ "$cluster_ip" = "None" ]; then
        die "PFCP proxy service $proxy_name has no ClusterIP"
    fi
    printf '%s\n' "$cluster_ip"
}

remove_pfcp_proxy_slice() {
    local s="$1"
    local proxy_name="pfcpproxy$s"

    kubectl delete deployment "$proxy_name" -n "$NAMESPACE" --ignore-not-found=true
    kubectl delete service "$proxy_name" -n "$NAMESPACE" --ignore-not-found=true
}

ran_sdr_addrs() {
    case "$1" in
        rfsim) echo "$2" ;;
        usrp|usrpb210) echo "" ;;
    esac
}

du_additional_options() {
    case "$1" in
        rfsim)
            echo "-E --rfsim --thread-pool N --rfsimulator.[0].serveraddr server --log_config.global_log_options level,nocolor,time"
            ;;
        usrp|usrpb210)
            echo "-E --continuous-tx --thread-pool N --log_config.global_log_options level,nocolor,time"
            ;;
    esac
}

cu_additional_options() {
    case "$1" in
        rfsim)
            echo "--rfsim --log_config.global_log_options level,nocolor,time"
            ;;
        usrp|usrpb210)
            echo "--log_config.global_log_options level,nocolor,time"
            ;;
    esac
}

ue_additional_options() {
    local mode="$1"
    local du_host="$2"

    case "$mode" in
        rfsim)
            echo "-E --rfsim --thread-pool N --rfsimulator.[0].serveraddr $du_host -r 106 --numerology 1 -C 3619200000"
            ;;
        usrp|usrpb210)
            echo "-E --ue-fo-compensation --cont-fo-comp 1 -r 106 --numerology 1 --band 78 --ssb 516 -C 3619200000"
            ;;
    esac
}

configure_proxy_values() {
    local chart="$1"
    local slice_id="$2"
    local location="$3"

    set_yaml_value "$chart/values.yaml" opmode "$OPMODE"
    set_yaml_value "$chart/values.yaml" loglevel "$LOGLEVEL"
    set_yaml_value "$chart/values.yaml" proxyport "$PROXY_PORT"
    set_yaml_value "$chart/values.yaml" serviceport "$SERVICE_PORT"
    set_yaml_value "$chart/values.yaml" networksliceID "$slice_id"
    set_yaml_value "$chart/values.yaml" locationID "$location"
    set_yaml_value "$chart/values.yaml" proxyversion "$PROXY_VERSION"
}

install_mysql_if_needed() {
    kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 || kubectl create namespace "$NAMESPACE"

    if ! helm status mysql -n "$NAMESPACE" >/dev/null 2>&1; then
        info "Installing MySQL subscriber database"
        helm install mysql "$CORE_DIR/mysql" -n "$NAMESPACE"
    else
        info "MySQL release already exists"
    fi

    wait_for_pod "$NAMESPACE" "mysql" 420
}

deploy_core_slice() {
    local s="$1"
    local st="$((s + 1))"
    local amf_pod
    local upf_pod
    local pfcp_proxy_ip=""

    configure_proxy_values "$CORE_DIR/oai-nrf" "$s" "$NRF_LOC"
    configure_proxy_values "$CORE_DIR/oai-udr" "$s" "$UDR_LOC"
    configure_proxy_values "$CORE_DIR/oai-udm" "$s" "$UDM_LOC"
    configure_proxy_values "$CORE_DIR/oai-ausf" "$s" "$AUSF_LOC"
    configure_proxy_values "$CORE_DIR/oai-amf" "$s" "$AMF_LOC"
    configure_proxy_values "$CORE_DIR/oai-smf" "$s" "$SMF_LOC"

    info "Deploying core slice $s"

    if [ "$RAN_PROXY" = "1" ]; then
        deploy_pfcp_proxy_slice "$s"
        pfcp_proxy_ip="$(pfcp_proxy_service_ip "$s")"
        set_yaml_value "$CORE_DIR/oai-smf/values.yaml" discoverUpf '"no"'
        set_yaml_value "$CORE_DIR/oai-smf/values.yaml" upfFqdn0 "\"pfcpproxy$s\""
        set_yaml_value "$CORE_DIR/oai-smf/values.yaml" upfIpv4Address "\"$pfcp_proxy_ip\""
    else
        remove_pfcp_proxy_slice "$s"
        set_yaml_value "$CORE_DIR/oai-smf/values.yaml" discoverUpf '"yes"'
        set_yaml_value "$CORE_DIR/oai-smf/values.yaml" upfFqdn0 '""'
        set_yaml_value "$CORE_DIR/oai-smf/values.yaml" upfIpv4Address '""'
    fi

    sed -i "22s/.*/name: oai-nrf$s/" "$CORE_DIR/oai-nrf/Chart.yaml"
    set_yaml_value "$CORE_DIR/oai-nrf/values.yaml" saname "\"oai-nrf$s-sa\""
    set_yaml_value "$CORE_DIR/oai-nrf/values.yaml" servicename "\"nrf$st\""
    set_yaml_value "$CORE_DIR/oai-nrf/values.yaml" deplocation "$NRF_LOC"
    helm upgrade --install "nrf$s" "$CORE_DIR/oai-nrf" -n "$NAMESPACE"
    wait_for_pod "$NAMESPACE" "oai-nrf$s"

    sed -i "23s/.*/name: oai-udr$s/" "$CORE_DIR/oai-udr/Chart.yaml"
    set_yaml_value "$CORE_DIR/oai-udr/values.yaml" nrfFqdn "\"oai-nrf$s-svc\""
    set_yaml_value "$CORE_DIR/oai-udr/values.yaml" saname "\"oai-udr$s-sa\""
    set_yaml_value "$CORE_DIR/oai-udr/values.yaml" servicename "\"udr$st\""
    set_yaml_value "$CORE_DIR/oai-udr/values.yaml" deplocation "$UDR_LOC"
    helm upgrade --install "udr$s" "$CORE_DIR/oai-udr" -n "$NAMESPACE"
    wait_for_pod "$NAMESPACE" "oai-udr$s"

    sed -i "23s/.*/name: oai-udm$s/" "$CORE_DIR/oai-udm/Chart.yaml"
    set_yaml_value "$CORE_DIR/oai-udm/values.yaml" nrfFqdn "\"oai-nrf$s-svc\""
    set_yaml_value "$CORE_DIR/oai-udm/values.yaml" udrFqdn "\"oai-udr$s-svc\""
    set_yaml_value "$CORE_DIR/oai-udm/values.yaml" saname "\"oai-udm$s-sa\""
    set_yaml_value "$CORE_DIR/oai-udm/values.yaml" servicename "\"udm$st\""
    set_yaml_value "$CORE_DIR/oai-udm/values.yaml" deplocation "$UDM_LOC"
    helm upgrade --install "udm$s" "$CORE_DIR/oai-udm" -n "$NAMESPACE"
    wait_for_pod "$NAMESPACE" "oai-udm$s"

    sed -i "22s/.*/name: oai-ausf$s/" "$CORE_DIR/oai-ausf/Chart.yaml"
    set_yaml_value "$CORE_DIR/oai-ausf/values.yaml" nrfFqdn "\"oai-nrf$s-svc\""
    set_yaml_value "$CORE_DIR/oai-ausf/values.yaml" udmFqdn "\"oai-udm$s-svc\""
    set_yaml_value "$CORE_DIR/oai-ausf/values.yaml" saname "\"oai-ausf$s-sa\""
    set_yaml_value "$CORE_DIR/oai-ausf/values.yaml" servicename "\"ausf$st\""
    set_yaml_value "$CORE_DIR/oai-ausf/values.yaml" deplocation "$AUSF_LOC"
    helm upgrade --install "ausf$s" "$CORE_DIR/oai-ausf" -n "$NAMESPACE"
    wait_for_pod "$NAMESPACE" "oai-ausf$s"

    sed -i "22s/.*/name: oai-amf$s/" "$CORE_DIR/oai-amf/Chart.yaml"
    set_yaml_value "$CORE_DIR/oai-amf/values.yaml" nrfFqdn "\"oai-nrf$s-svc\""
    if ! grep -qE "^[[:space:]]*smfFqdn:" "$CORE_DIR/oai-amf/values.yaml"; then
        sed -i "/ausfFqdn:/a\  smfFqdn: \"oai-smf$s-svc\"" "$CORE_DIR/oai-amf/values.yaml"
    fi
    set_yaml_value "$CORE_DIR/oai-amf/values.yaml" smfFqdn "\"oai-smf$s-svc\""
    set_yaml_value "$CORE_DIR/oai-amf/values.yaml" ausfFqdn "\"oai-ausf$s-svc\""
    set_yaml_value "$CORE_DIR/oai-amf/values.yaml" saname "\"oai-amf$s-sa\""
    set_yaml_value "$CORE_DIR/oai-amf/values.yaml" sst0 "\"2$s\""
    set_yaml_value "$CORE_DIR/oai-amf/values.yaml" servicename "\"amf$st\""
    set_yaml_value "$CORE_DIR/oai-amf/values.yaml" deplocation "$AMF_LOC"
    helm upgrade --install "amf$s" "$CORE_DIR/oai-amf" -n "$NAMESPACE"
    wait_for_pod "$NAMESPACE" "oai-amf$s"

    sed -i "22s/.*/name: oai-smf$s/" "$CORE_DIR/oai-smf/Chart.yaml"
    set_yaml_value "$CORE_DIR/oai-smf/values.yaml" nrfFqdn "\"oai-nrf$s-svc\""
    set_yaml_value "$CORE_DIR/oai-smf/values.yaml" udmFqdn "\"oai-udm$s-svc\""
    set_yaml_value "$CORE_DIR/oai-smf/values.yaml" amfFqdn "\"oai-amf$s-svc\""
    set_yaml_value "$CORE_DIR/oai-smf/values.yaml" nssaiSst0 "\"2$s\""
    set_yaml_value "$CORE_DIR/oai-smf/values.yaml" saname "\"oai-smf$s-sa\""
    set_yaml_value "$CORE_DIR/oai-smf/values.yaml" servicename "\"smf$st\""
    set_yaml_value "$CORE_DIR/oai-smf/values.yaml" deplocation "$SMF_LOC"
    helm upgrade --install "smf$s" "$CORE_DIR/oai-smf" -n "$NAMESPACE"
    wait_for_pod "$NAMESPACE" "oai-smf$s"

    sed -i "22s/.*/name: oai-spgwu-tiny$s/" "$CORE_DIR/oai-spgwu-tiny/Chart.yaml"
    set_yaml_value "$CORE_DIR/oai-spgwu-tiny/values.yaml" nrfFqdn "\"oai-nrf$s-svc\""
    if [ "$RAN_PROXY" = "1" ]; then
        # The UPF advertises this Node ID in PFCP Association Setup Response.
        # Keep the SMF's response-driven endpoint on the proxy path.
        set_yaml_value "$CORE_DIR/oai-spgwu-tiny/values.yaml" fqdn "\"pfcpproxy$s\""
    else
        set_yaml_value "$CORE_DIR/oai-spgwu-tiny/values.yaml" fqdn "\"oai-spgwu-tiny$s-svc\""
    fi
    set_yaml_value "$CORE_DIR/oai-spgwu-tiny/values.yaml" nssaiSst0 "\"2$s\""
    set_yaml_value "$CORE_DIR/oai-spgwu-tiny/values.yaml" deplocation "$UPF_LOC"
    sed -i "/oai-spgwu-tiny-sa/c\  name: \"oai-spgwu-tiny$s-sa\"" "$CORE_DIR/oai-spgwu-tiny/values.yaml"
    sed -i "24s/.*/  name: \"oai-spgwu-tiny$s\"/" "$CORE_DIR/oai-spgwu-tiny/values.yaml"
    helm upgrade --install "upf$s" "$CORE_DIR/oai-spgwu-tiny" -n "$NAMESPACE"
    wait_for_pod "$NAMESPACE" "oai-spgwu-tiny$s"

    amf_pod="$(pod_by_prefix "$NAMESPACE" "oai-amf$s")"
    upf_pod="$(pod_by_prefix "$NAMESPACE" "oai-spgwu-tiny$s")"
    AMF_IP="$(get_pod_ip "$NAMESPACE" "$amf_pod" amf)"
    UPF_IP="$(get_pod_ip "$NAMESPACE" "$upf_pod" spgwu)"
    export AMF_IP UPF_IP

    success "Core slice $s deployed: AMF=$AMF_IP UPF=$UPF_IP"
}

deploy_oai_ran_user() {
    local u="$1"
    local s="$2"
    local ue_ip_suffix="$3"
    local imsi="2089500000000$u"
    local key="0C0A34601D4F07677303652C046253$u"
    local cu_chart="$RAN_DIR/oai-gnb-cu"
    local du_chart="$RAN_DIR/oai-gnb-du"
    local ue_chart="$RAN_DIR/oai-nr-ue"
    local usrp_type
    local du_sdr_addrs
    local ue_sdr_addrs

    usrp_type="$(ran_usrp_type "$RUN_MODE")"
    du_sdr_addrs="$(ran_sdr_addrs "$RUN_MODE" "server")"
    ue_sdr_addrs="$(ran_sdr_addrs "$RUN_MODE" "oai-gnb-du$u")"

    info "Deploying OAI CU/DU for user $u on slice $s with run_mode=$RUN_MODE"

    local amf_target="$AMF_IP"
    if [ "$RAN_PROXY" = "1" ]; then
        deploy_ngap_proxy_user "$u" "$AMF_IP"
        amf_target="ngapproxy$u"
    fi

    sed -i "s/^name: .*/name: oai-gnb-cu$u/" "$cu_chart/Chart.yaml"
    sed -i -E "s|^([[:space:]]*)name: \"oai-gnb-cu.*-sa\"|\\1name: \"oai-gnb-cu$u-sa\"|" "$cu_chart/values.yaml"
    set_yaml_value "$cu_chart/values.yaml" mcc "\"208\""
    set_yaml_value "$cu_chart/values.yaml" mnc "\"95\""
    set_yaml_value "$cu_chart/values.yaml" mncLength "\"2\""
    set_yaml_value "$cu_chart/values.yaml" tac "\"0x00a000\""
    set_yaml_value "$cu_chart/values.yaml" nssaiSst "\"2$s\""
    set_yaml_value "$cu_chart/values.yaml" nssaiSd0 "\"123\""
    set_yaml_value "$cu_chart/values.yaml" amfIpAddress "\"$amf_target\""
    set_yaml_value "$cu_chart/values.yaml" mountConfig "true"
    set_yaml_value "$cu_chart/values.yaml" rfSimulator "\"server\""
    set_yaml_value "$cu_chart/values.yaml" gnbcuName "\"oai-gnb-cu$u-$RUN_MODE\""
    set_yaml_value "$cu_chart/values.yaml" f1cuIpAddress "\"status.podIP\""
    set_yaml_value "$cu_chart/values.yaml" f1duIpAddress "\"oai-gnb-du$u\""
    set_yaml_value "$cu_chart/values.yaml" useAdditionalOptions "\"$(cu_additional_options "$RUN_MODE")\""
    sed -i "/nodeSelector:/,/nodeName:/c\nodeSelector:\n  deplocation: $RAN_LOC\n\nnodeName: " "$cu_chart/values.yaml"
    helm upgrade --install "gnbcu$u" "$cu_chart" -n "$NAMESPACE"
    wait_for_pod "$NAMESPACE" "oai-gnb-cu$u" 420 45
    local cu_pod
    local cu_ip
    cu_pod="$(pod_by_prefix "$NAMESPACE" "oai-gnb-cu$u")"
    cu_ip="$(get_pod_ip "$NAMESPACE" "$cu_pod")"

    local f1cu_target="$cu_ip"
    if [ "$RAN_PROXY" = "1" ]; then
        deploy_ran_proxy_user "$u" "$cu_ip"
        f1cu_target="f1proxy$u"
    fi

    sed -i "s/^name: .*/name: oai-gnb-du$u/" "$du_chart/Chart.yaml"
    sed -i -E "s|^([[:space:]]*)name: \"oai-gnb-du.*-sa\"|\\1name: \"oai-gnb-du$u-sa\"|" "$du_chart/values.yaml"
    set_yaml_value "$du_chart/values.yaml" mcc "\"208\""
    set_yaml_value "$du_chart/values.yaml" mnc "\"95\""
    set_yaml_value "$du_chart/values.yaml" mncLength "\"2\""
    set_yaml_value "$du_chart/values.yaml" tac "\"0x00a000\""
    set_yaml_value "$du_chart/values.yaml" nssaiSst "\"2$s\""
    set_yaml_value "$du_chart/values.yaml" nssaiSd0 "\"123\""
    set_yaml_value "$du_chart/values.yaml" amfIpAddress "\"$AMF_IP\""
    set_yaml_value "$du_chart/values.yaml" mountConfig "true"
    set_yaml_value "$du_chart/values.yaml" usrp "\"$usrp_type\""
    set_yaml_value "$du_chart/values.yaml" rfSimulator "\"server\""
    set_yaml_value "$du_chart/values.yaml" sdrAddrs "\"$du_sdr_addrs\""
    set_yaml_value "$du_chart/values.yaml" gnbduName "\"oai-gnb-du$u-$RUN_MODE\""
    set_yaml_value "$du_chart/values.yaml" f1cuIpAddress "\"$f1cu_target\""
    set_yaml_value "$du_chart/values.yaml" f1duIpAddress "\"status.podIP\""
    set_yaml_value "$du_chart/values.yaml" useAdditionalOptions "\"$(du_additional_options "$RUN_MODE")\""
    sed -i "/nodeSelector:/,/nodeName:/c\nodeSelector:\n  deplocation: $RAN_LOC\n\nnodeName: " "$du_chart/values.yaml"
    helm upgrade --install "gnbdu$u" "$du_chart" -n "$NAMESPACE"
    wait_for_pod "$NAMESPACE" "oai-gnb-du$u" 420 45

    if [ "$DEPLOY_UE" = "0" ]; then
        info "DeployUE=0; skipping NR-UE and DNN for user $u"
        return 0
    fi

    info "Deploying OAI NR-UE and DNN for UE $u on slice $s"

    sed -i "s/^name: .*/name: oai-nr-ue$u/" "$ue_chart/Chart.yaml"
    sed -i -E "s|^([[:space:]]*)name: \"oai-nr-ue.*-sa\"|\\1name: \"oai-nr-ue$u-sa\"|" "$ue_chart/values.yaml"
    set_yaml_value "$ue_chart/values.yaml" usrp "\"$usrp_type\""
    set_yaml_value "$ue_chart/values.yaml" rfSimulator "\"oai-gnb-du$u\""
    set_yaml_value "$ue_chart/values.yaml" sdrAddrs "\"$ue_sdr_addrs\""
    set_yaml_value "$ue_chart/values.yaml" fullImsi "\"$imsi\""
    set_yaml_value "$ue_chart/values.yaml" fullKey "\"$key\""
    set_yaml_value "$ue_chart/values.yaml" opc "\"63bfa50ee6523365ff14c1f45f88737d\""
    set_yaml_value "$ue_chart/values.yaml" dnn "\"oai\""
    set_yaml_value "$ue_chart/values.yaml" nssaiSst "\"2$s\""
    set_yaml_value "$ue_chart/values.yaml" nssaiSd "\"123\""
    set_yaml_value "$ue_chart/values.yaml" useAdditionalOptions "\"$(ue_additional_options "$RUN_MODE" "oai-gnb-du$u")\""
    sed -i "/nodeSelector:/,/nodeName:/c\nodeSelector:\n  deplocation: $RAN_LOC\n\nnodeName: " "$ue_chart/values.yaml"
    helm upgrade --install "nrue$u" "$ue_chart" -n "$NAMESPACE"
    wait_for_pod "$NAMESPACE" "oai-nr-ue$u" 420 45

    sed -i "4s/.*/  name: oai-dnn$u/" "$CORE_DIR/oai-dnn/02_deployment.yaml"
    sed -i "6s/.*/    app: oai-dnn$u/" "$CORE_DIR/oai-dnn/02_deployment.yaml"
    sed -i "11s/.*/      app: oai-dnn$u/" "$CORE_DIR/oai-dnn/02_deployment.yaml"
    sed -i "17s/.*/        app: oai-dnn$u/" "$CORE_DIR/oai-dnn/02_deployment.yaml"
    sed -i "22s/.*/        deplocation: $DNN_LOC/" "$CORE_DIR/oai-dnn/02_deployment.yaml"
    sed -i "28s/.*/        image: tolgaomeratalay\/oai-dnn:${USECASE}/" "$CORE_DIR/oai-dnn/02_deployment.yaml"
    kubectl apply -k "$CORE_DIR/oai-dnn" -n "$NAMESPACE"
    wait_for_pod "$NAMESPACE" "oai-dnn$u"

    local dnn_pod
    local dnn_ip
    dnn_pod="$(pod_by_prefix "$NAMESPACE" "oai-dnn$u")"
    dnn_ip="$(get_pod_ip "$NAMESPACE" "$dnn_pod")"

    kubectl exec -n "$NAMESPACE" "$dnn_pod" -- sh -c "iptables -t nat -C POSTROUTING -o eth0 -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE"
    kubectl exec -n "$NAMESPACE" "$dnn_pod" -- sh -c "ip route replace 12.1.1.0/24 via $UPF_IP dev eth0 onlink"

    info "DNN $u is $dnn_ip; expected UE data IP is 12.1.1.$ue_ip_suffix"
}

install_mysql_if_needed

if [ "$CROSS_PROTOCOL_CORRELATE" = "1" ]; then
    deploy_cross_protocol_correlator
else
    remove_cross_protocol_correlator
fi

slice_end=$((NUM_SLICES + 9))
u=10
ue_ip_suffix=2

for ((s=10; s<=slice_end; s++)); do
    deploy_core_slice "$s"

    for ((ut=0; ut<NUM_USERS; ut++)); do
        deploy_oai_ran_user "$u" "$s" "$ue_ip_suffix"
        u=$((u + 1))
        ue_ip_suffix=$((ue_ip_suffix + 1))
    done
done

success "Finished 5G core and OAI RAN deployment"
