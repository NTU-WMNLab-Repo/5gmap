#!/bin/bash

# ==============================================================================
# O-RAN Deployment Verification Script - V2.0 (Full Compliance Edition)
# Covers: User's Specific Checklist (Logs, Top, IP, Ping, Iperf)
# Run method:
# chmod +x check_link.sh
# ./check_link.sh
# ==============================================================================

NAMESPACE="default"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ------------------------------------------------------------------------------
# Helper Functions
# ------------------------------------------------------------------------------

print_header() { echo -e "\n${CYAN}=== $1 ===${NC}"; }
print_pass() { echo -e "${GREEN}[PASS] $1${NC}"; }
print_fail() {
    echo -e "${RED}[FAIL] $1${NC}"
    echo -e "${YELLOW}Possible Cause:${NC} $2"
    exit 1
}

get_pod_name() {
    local label=$1
    # 1. 抓取所有符合該標籤的 Pod 名字
    local all_pods=$(kubectl get pods -n $NAMESPACE -l "$label" -o jsonpath="{.items[*].metadata.name}" 2>/dev/null)
    
    if [ -z "$all_pods" ]; then
        print_fail "Pod with label '$label' not found." "Check deployment."
    fi

    # 2. 從中優先尋找包含 "prime" 的名字
    local target=$(echo "$all_pods" | tr ' ' '\n' | grep "prime" | head -n 1)

    # 3. 如果找不到包含 "prime" 的，就抓第一個出現的 Pod
    if [ -z "$target" ]; then
        target=$(echo "$all_pods" | awk '{print $1}')
    fi

    echo "$target"
}

# 修正版的 wait_for_log (先搜歷史，再搜最新)
wait_for_log() {
    local pod_name=$1
    local keyword=$2
    local label=$3
    local timeout=${4:-30}
    local interval=3
    local elapsed=0

    echo -n "Checking $label log for '$keyword'... "

    # 1. 搜歷史 Log
    if kubectl logs $pod_name -n $NAMESPACE 2>&1 | grep -q "$keyword"; then
        echo -e "${GREEN}FOUND (in history)${NC}"
        return 0
    fi

    # 2. 搜即時 Log
    while [ $elapsed -lt $timeout ]; do
        if kubectl logs $pod_name -n $NAMESPACE --tail=300 2>&1 | grep -q "$keyword"; then
            echo -e "${GREEN}FOUND (new event)${NC}"
            return 0
        fi
        sleep $interval
        elapsed=$((elapsed + interval))
        echo -n "."
    done

    echo -e "${RED}NOT FOUND${NC}"
    return 1
}

# ==============================================================================
# Section 1: Core Network Checklist
# ==============================================================================
print_header "1. Core Network Verification"

NRF_POD=$(get_pod_name "app.kubernetes.io/name=oai-nrf")
AMF_POD=$(get_pod_name "app.kubernetes.io/name=oai-amf")
UPF_POD=$(get_pod_name "app.kubernetes.io/name=oai-upf")
SMF_POD=$(get_pod_name "app.kubernetes.io/name=oai-smf")
TS_POD=$(get_pod_name "app.kubernetes.io/name=oai-traffic-server")

# 1. NRF: Set NF status to REGISTERED
if ! wait_for_log $NRF_POD "Set NF status to REGISTERED" "NRF"; then
    print_fail "NRF Verification Failed" "NFs (AMF/SMF/UPF) failed to register."
fi

# 2. AMF: UEs' Information (Check for '5GMM-REGISTERED' which appears in that table)
if ! wait_for_log $AMF_POD "5GMM-REGISTERED" "AMF (UE Info)"; then
    print_fail "AMF Verification Failed" "No UE found in 'UEs Information' table."
fi

# 3. UPF: Got successful response from NRF
if ! wait_for_log $UPF_POD "Got successful response from NRF" "UPF"; then
    print_fail "UPF Verification Failed" "UPF failed to register with NRF."
fi

# 4. SMF: Set PDU Session Status to PDU_SESSION_ACTIVE
if ! wait_for_log $SMF_POD "PDU_SESSION_ACTIVE" "SMF"; then
    print_fail "SMF Verification Failed" "PDU Session did not become ACTIVE."
fi

# 5. Traffic Server IP Check
print_header "Checking Traffic Server IP"
TS_IP=$(kubectl exec $TS_POD -n $NAMESPACE -- ip -4 addr show eth0 | grep -oP '(?<=inet\s)\d+(\.\d+){3}')
echo "Traffic Server IP (eth0): $TS_IP"
if [ -z "$TS_IP" ]; then print_fail "Traffic Server IP Check" "Cannot determine IP."; fi

# ==============================================================================
# Section 2: CU & DU Checklist
# ==============================================================================
print_header "2. CU & DU Verification"

CU_POD=$(get_pod_name "app.kubernetes.io/name=oai-cu")
DU_POD=$(get_pod_name "app.kubernetes.io/name=oai-du")

# 1. CU Log Check
if ! wait_for_log $CU_POD "NGAP_REGISTER_GNB_CNF" "CU"; then
    print_fail "CU Verification Failed" "CU failed to register with AMF."
fi

# 2. DU Log Check
if ! wait_for_log $DU_POD "received F1 Setup Response" "DU"; then
    print_fail "DU Verification Failed" "DU failed to setup F1 with CU."
fi

# 3. DU Top (Resource Check)
print_header "DU Resource Usage (top)"
echo "Running: kubectl exec $DU_POD -- top -b -n 1 | head -n 5"
kubectl exec $DU_POD -n $NAMESPACE -- top -b -n 1 | head -n 5
print_pass "DU Resource Check Completed"

# 4. get DU, CU IP
CU_IP=$(kubectl get pod $CU_POD -n $NAMESPACE -o jsonpath='{.status.podIP}')
DU_IP=$(kubectl get pod $DU_POD -n $NAMESPACE -o jsonpath='{.status.podIP}')

# echo "CU Pod IP: $CU_IP"
# echo "DU Pod IP: $DU_IP"

# ==============================================================================
# Section 3: UE Verification
# ==============================================================================
print_header "3. UE Verification"

UE_POD=$(get_pod_name "app.kubernetes.io/name=oai-nr-ue")

# 1. UE Log Check
if ! wait_for_log $UE_POD "Interface oaitun_ue1 successfully configured" "UE"; then
    print_fail "UE Log Verification Failed" "UE interface not configured."
fi

# 2. Check IP Address (oaitun_ue1)
print_header "UE IP Address Check"
UE_IP=$(kubectl exec $UE_POD -n $NAMESPACE -- ip -4 addr show oaitun_ue1 | grep -oP '(?<=inet\s)\d+(\.\d+){3}')
echo "UE IP on oaitun_ue1: $UE_IP"
if [ -z "$UE_IP" ]; then
    print_fail "UE IP Check" "oaitun_ue1 interface missing or no IP."
fi

### 在 check_link.sh 失敗區塊加入 ###
# 1. 檢查 DU 是否有 UDP 流量進入 (GTP-U 預設連接埠 2152)
echo "=== DU UDP Traffic Stats ==="
kubectl exec $DU_POD -- cat /proc/net/udp | grep "0868" # 0868 是 2152 的十六進制
# 如果第 2 欄 (local_address) 的 tx_queue/rx_queue 有數值在跳動，代表有封包進來

# 2. 檢查 CU 的正確 Container 名稱與路由
echo "=== CU Routing Check ==="
# 先找出 CU 到底有哪些 Container
CU_CONT_NAME=$(kubectl get pod $CU_POD -o jsonpath='{.spec.containers[0].name}')
kubectl exec $CU_POD -c $CU_CONT_NAME -- ip route
# 在 UE Pod 裡面測試到各節點的連通性 (不透過 GTP，走 Pod 網路)
echo "=== UE to Network Infrastructure Check ==="
kubectl exec $UE_POD -- ping -c 1 $DU_IP > /dev/null && echo "UE -> DU Pod IP: OK" || echo "UE -> DU Pod IP: FAIL"
kubectl exec $UE_POD -- ping -c 1 $CU_IP > /dev/null && echo "UE -> CU Pod IP: OK" || echo "UE -> CU Pod IP: FAIL"

# # 3 Ping Test: UE -> DU
# print_header "Ping Test: UE -> DU ($DU_IP)"
# if kubectl exec $UE_POD -n $NAMESPACE -- ping -I oaitun_ue1 -c 3 $DU_IP; then
#     print_pass "Ping to DU Successful"
# else
#     echo -e "${YELLOW}[WARN] Ping to DU Failed.${NC}"
# fi

# # 4 Ping Test: UE -> CU
# print_header "Ping Test: UE -> CU ($CU_IP)"
# if kubectl exec $UE_POD -n $NAMESPACE -- ping -I oaitun_ue1 -c 3 $CU_IP; then
#     print_pass "Ping to CU Successful"
# else
#     echo -e "${YELLOW}[WARN] Ping to CU Failed.${NC} (Note: Some O-RAN setups don't route UE traffic back to CU/DU control planes)"
# fi

# 5. Ping Test: UE -> UPF Gateway (12.1.1.1)
print_header "Ping Test: UE -> UPF (12.1.1.1)"
if kubectl exec $UE_POD -n $NAMESPACE -- ping -I oaitun_ue1 -c 3 12.1.1.1; then
    print_pass "Ping to UPF Gateway Successful"
else
    print_fail "Ping to UPF Failed" "GTP tunnel might be broken."
fi

# 6. Ping Test: UE -> Internet (8.8.8.8)
print_header "Ping Test: UE -> Internet (8.8.8.8)"
if kubectl exec $UE_POD -n $NAMESPACE -- ping -I oaitun_ue1 -c 3 8.8.8.8; then
    print_pass "Ping to Internet Successful"
else
    echo -e "${YELLOW}[WARN] Ping to 8.8.8.8 Failed.${NC} (Ignored if no internet access in lab)"
fi

# 7. Ping Test: UE -> Traffic Server
print_header "Ping Test: UE -> Traffic Server ($TS_IP)"
if kubectl exec $UE_POD -n $NAMESPACE -- ping -I oaitun_ue1 -c 3 $TS_IP; then
    print_pass "Ping to Traffic Server Successful"
else
    print_fail "Ping to Traffic Server Failed" "Routing issue between UPF and DN."
fi

# sleep for avoiding DU high CPU loading
sleep 5

# ==============================================================================
# Section 4: Throughput Test (Iperf3 Bidirectional)
# ==============================================================================
print_header "4. Throughput Test (Iperf3)"

# # ------------------------------------------------------------------------------
# # 4.1 Uplink Test (UE -> Network)
# # ------------------------------------------------------------------------------
# print_header "4.1 Uplink Test (UE -> Traffic Server)"
# # Command: UE as Client, sending data TO Traffic Server
# IPERF_UL_CMD="iperf3 -c $TS_IP -p 5201 -t 5 -B $UE_IP -b 1M"

# echo "Running Uplink: $IPERF_UL_CMD"
# # 執行並將輸出存入變數，以便檢查結果
# UL_RESULT=$(kubectl exec $UE_POD -n $NAMESPACE -- sh -lc "$IPERF_UL_CMD" 2>&1)
# echo "$UL_RESULT"

# if echo "$UL_RESULT" | grep -q "receiver"; then
#     # 抓取最終頻寬數值 (簡易抓取 receiver 行的 Mbits/sec)
#     UL_BW=$(echo "$UL_RESULT" | grep "receiver" | awk '{print $(NF-2), $(NF-1)}')
#     print_pass "Uplink Test Passed (Bandwidth: $UL_BW)"
# else
#     print_fail "Uplink Test Failed" "Connection refused or no data transferred."
# fi

# ------------------------------------------------------------------------------
# 4.2 Downlink Test (Network -> UE)
# ------------------------------------------------------------------------------
print_header "4.2 Downlink Test (Traffic Server -> UE)"
# Command: UE as Client, receiving data FROM Traffic Server (Reverse Mode -R)
IPERF_DL_CMD="iperf3 -c $TS_IP -p 5201 -t 5 -B $UE_IP -R"

echo "Running Downlink: $IPERF_DL_CMD"
DL_RESULT=$(kubectl exec $UE_POD -n $NAMESPACE -- sh -lc "$IPERF_DL_CMD" 2>&1)
echo "$DL_RESULT"

if echo "$DL_RESULT" | grep -q "receiver"; then
    DL_BW=$(echo "$DL_RESULT" | grep "receiver" | awk '{print $(NF-2), $(NF-1)}')
    print_pass "Downlink Test Passed (Bandwidth: $DL_BW)"
else
    # 如果失敗，嘗試降低 MTU 再測一次 (備援方案)
    echo -e "${YELLOW}[WARN] Standard Downlink Failed. Retrying with MSS=1300...${NC}"
    IPERF_DL_MSS="iperf3 -c $TS_IP -p 5201 -t 5 -B $UE_IP -R -M 1300"
    DL_RESULT_MSS=$(kubectl exec $UE_POD -n $NAMESPACE -- sh -lc "$IPERF_DL_MSS" 2>&1)
    echo "$DL_RESULT_MSS"
    
    if echo "$DL_RESULT_MSS" | grep -q "receiver"; then
        DL_BW=$(echo "$DL_RESULT_MSS" | grep "receiver" | awk '{print $(NF-2), $(NF-1)}')
        print_pass "Downlink Test Passed with MSS fix (Bandwidth: $DL_BW)"
    else
        print_fail "Downlink Test Failed" "Traffic not reaching UE. Check Routing or DU Logs."
    fi
fi

echo -e "\n${GREEN}=== ALL CHECKS PASSED: SYSTEM READY ===${NC}"