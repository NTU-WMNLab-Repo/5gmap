#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
CORE_DIR="$ROOT_DIR/5gcore"
RAN_DIR="$ROOT_DIR/oai-5g-ran"

source "$SCRIPT_DIR/common.sh"
enable_error_trap

USECASE="${1:-zoomv3}"
NUM_USERS="${2:-1}"
NUM_SLICES="${3:-1}"

NAMESPACE="${NAMESPACE:-oai}"
OPMODE="${OPMODE:-OTEL}"
LOGLEVEL="${LOGLEVEL:-trace}"
PROXY_PORT="${PROXY_PORT:-11095}"
SERVICE_PORT="${SERVICE_PORT:-8080}"
PROXY_VERSION="${PROXY_VERSION:-7.0.0}"

NRF_LOC="${NRF_LOC:-edge}"
UDR_LOC="${UDR_LOC:-az}"
UDM_LOC="${UDM_LOC:-az}"
AUSF_LOC="${AUSF_LOC:-az}"
AMF_LOC="${AMF_LOC:-edge}"
SMF_LOC="${SMF_LOC:-edge}"
UPF_LOC="${UPF_LOC:-edge}"
RAN_LOC="${RAN_LOC:-az}"
DNN_LOC="${DNN_LOC:-edge}"

require_commands kubectl helm sed awk grep

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

    configure_proxy_values "$CORE_DIR/oai-nrf" "$s" "$NRF_LOC"
    configure_proxy_values "$CORE_DIR/oai-udr" "$s" "$UDR_LOC"
    configure_proxy_values "$CORE_DIR/oai-udm" "$s" "$UDM_LOC"
    configure_proxy_values "$CORE_DIR/oai-ausf" "$s" "$AUSF_LOC"
    configure_proxy_values "$CORE_DIR/oai-amf" "$s" "$AMF_LOC"
    configure_proxy_values "$CORE_DIR/oai-smf" "$s" "$SMF_LOC"

    info "Deploying core slice $s"

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
    set_yaml_value "$CORE_DIR/oai-spgwu-tiny/values.yaml" fqdn "\"oai-spgwu-tiny$s-svc\""
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

    info "Deploying OAI CU/DU/NR-UE for UE $u on slice $s"

    sed -i "s/^name: .*/name: oai-gnb-cu$u/" "$cu_chart/Chart.yaml"
    sed -i -E "s|^([[:space:]]*)name: \"oai-gnb-cu.*-sa\"|\\1name: \"oai-gnb-cu$u-sa\"|" "$cu_chart/values.yaml"
    set_yaml_value "$cu_chart/values.yaml" mcc "\"208\""
    set_yaml_value "$cu_chart/values.yaml" mnc "\"95\""
    set_yaml_value "$cu_chart/values.yaml" mncLength "\"2\""
    set_yaml_value "$cu_chart/values.yaml" tac "\"0x00a000\""
    set_yaml_value "$cu_chart/values.yaml" nssaiSst "\"2$s\""
    set_yaml_value "$cu_chart/values.yaml" nssaiSd0 "\"123\""
    set_yaml_value "$cu_chart/values.yaml" amfIpAddress "\"$AMF_IP\""
    set_yaml_value "$cu_chart/values.yaml" mountConfig "true"
    set_yaml_value "$cu_chart/values.yaml" rfSimulator "\"server\""
    set_yaml_value "$cu_chart/values.yaml" gnbcuName "\"oai-gnb-cu$u-rfsim\""
    set_yaml_value "$cu_chart/values.yaml" f1cuIpAddress "\"status.podIP\""
    set_yaml_value "$cu_chart/values.yaml" f1duIpAddress "\"oai-gnb-du$u\""
    sed -i "/nodeSelector:/,/nodeName:/c\nodeSelector:\n  deplocation: $RAN_LOC\n\nnodeName: " "$cu_chart/values.yaml"
    helm upgrade --install "gnbcu$u" "$cu_chart" -n "$NAMESPACE"
    wait_for_pod "$NAMESPACE" "oai-gnb-cu$u" 420

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
    set_yaml_value "$du_chart/values.yaml" rfSimulator "\"server\""
    set_yaml_value "$du_chart/values.yaml" gnbduName "\"oai-gnb-du$u-rfsim\""
    set_yaml_value "$du_chart/values.yaml" f1cuIpAddress "\"oai-gnb-cu$u\""
    set_yaml_value "$du_chart/values.yaml" f1duIpAddress "\"status.podIP\""
    sed -i "/nodeSelector:/,/nodeName:/c\nodeSelector:\n  deplocation: $RAN_LOC\n\nnodeName: " "$du_chart/values.yaml"
    helm upgrade --install "gnbdu$u" "$du_chart" -n "$NAMESPACE"
    wait_for_pod "$NAMESPACE" "oai-gnb-du$u" 420

    sed -i "s/^name: .*/name: oai-nr-ue$u/" "$ue_chart/Chart.yaml"
    sed -i -E "s|^([[:space:]]*)name: \"oai-nr-ue.*-sa\"|\\1name: \"oai-nr-ue$u-sa\"|" "$ue_chart/values.yaml"
    set_yaml_value "$ue_chart/values.yaml" rfSimulator "\"oai-gnb-du$u\""
    set_yaml_value "$ue_chart/values.yaml" fullImsi "\"$imsi\""
    set_yaml_value "$ue_chart/values.yaml" fullKey "\"$key\""
    set_yaml_value "$ue_chart/values.yaml" opc "\"63bfa50ee6523365ff14c1f45f88737d\""
    set_yaml_value "$ue_chart/values.yaml" dnn "\"oai\""
    set_yaml_value "$ue_chart/values.yaml" nssaiSst "\"2$s\""
    set_yaml_value "$ue_chart/values.yaml" nssaiSd "\"123\""
    sed -i "/nodeSelector:/,/nodeName:/c\nodeSelector:\n  deplocation: $RAN_LOC\n\nnodeName: " "$ue_chart/values.yaml"
    helm upgrade --install "nrue$u" "$ue_chart" -n "$NAMESPACE"
    wait_for_pod "$NAMESPACE" "oai-nr-ue$u" 420

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
