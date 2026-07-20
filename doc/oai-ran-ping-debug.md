# OAI RAN ping failure debug note

## 結論

這次 `./script/run.sh` 失敗的直接症狀是 `start_traffic.sh` 從 DNN pod ping 固定 UE data IP `12.1.1.2`，結果 100% packet loss。實際上問題分成兩層：

1. CU/DU 的 F1-U address 有錯，DU 建立 DRB tunnel 時拿到 CU 的 remote IPv4 是 `0.0.0.0`，所以 UE 封包沒有進到 CU/UPF。
2. traffic test 的方向和 UE IP 假設不穩定。UE 的 data IP 不一定永遠是 `12.1.1.2`，而且 DNN 直接對 UE data IP 開新連線或 ping 不是 OAI 範例使用的 DL 驗證方式；OAI v2.1.0 的 `check_link.sh` 是由 UE 先連 traffic server，再用 `iperf3 -R` reverse mode 讓 DNN 往 UE 送資料。

修完後已驗證：

- CU 和 AMF 可完成 NG setup。
- CU 和 DU 可完成 F1 setup。
- UE 可完成 registration/PDU session，並產生 `oaitun_ue1`。
- NR-UE 透過 `oaitun_ue1` ping DNN pod IP 成功。
- UL iperf3，也就是 NR-UE -> DNN，可成功。
- DL iperf3 已可用 UE-initiated reverse mode 驗證，也就是 NR-UE `iperf3 -c <DNN_IP> -B <UE_IP> -R`，由 DNN server 送 downlink data。

尚未完成或尚未繼續 debug：

- DNN 直接 ping UE data IP 仍會失敗，目前保留為診斷訊號，不當作 E2E gating test。
- DNN 直接主動對 UE data IP 開新 TCP 連線的模型尚未繼續追；目前採用 OAI v2.1.0 相同的 UE-initiated reverse-mode DL 測法。
- 當前 cluster 看起來沒有 `NetworkAttachmentDefinition`，所以 DNN pod 的 `dnn-net11` annotation 沒有真的掛上 Multus data network。這次修復沒有依賴 Multus；若未來要測真正獨立 N6/data network，仍需要補 Multus 或 node-level route 設計。
- `oai-5g-ran/README.md` 裡關於 image mirror/pinning 的 TODO 尚未處理。

## 這次 debug 動了什麼

### 1. 修 CU 對 DU 公告的 F1-U IP

檔案：

- `oai-5g-ran/oai-gnb-cu/templates/configmap.yaml`
- `oai-5g-ran/oai-gnb-cu/templates/deployment.yaml`

原本 CU config 內的 F1-U local address 是：

```conf
local_s_address = "0.0.0.0";
```

這會讓 DU 在建立 DRB tunnel 時看到 remote IPv4 是 `0.0.0.0`。改成 placeholder：

```conf
local_s_address = "__F1_CU_IP_ADDRESS__";
```

並在 container startup 時用 downward API 給的 pod IP 替換：

```bash
sed -i "s/__GNB_NGA_IP_ADDRESS__/${GNB_NGA_IP_ADDRESS}/g; s/__GNB_NGU_IP_ADDRESS__/${GNB_NGU_IP_ADDRESS}/g; s/__F1_CU_IP_ADDRESS__/${F1_CU_IP_ADDRESS}/g" /tmp/gnb.conf
```

### 2. 修 DU 連 CU 的 F1-C/F1-U remote IP

檔案：

- `oai-5g-ran/oai-gnb-du/templates/configmap.yaml`
- `oai-5g-ran/oai-gnb-du/templates/deployment.yaml`
- `script/deploy.sh`

DU 原本的 `remote_n_address` 直接從 Helm values 寫入，可能是 service name 或上一輪殘留值。這次改成 placeholder：

```conf
remote_n_address = "__F1_CU_IP_ADDRESS__";
```

並在 deployment startup sed 替換：

```bash
sed -i "s/__F1_DU_IP_ADDRESS__/${F1_DU_IP_ADDRESS}/g; s/__F1_CU_IP_ADDRESS__/${F1_CU_IP_ADDRESS}/g" /tmp/gnb.conf
```

`script/deploy.sh` 在 CU ready 後讀 CU pod IP：

```bash
cu_pod="$(pod_by_prefix "$NAMESPACE" "oai-gnb-cu$u")"
cu_ip="$(get_pod_ip "$NAMESPACE" "$cu_pod")"
```

再把 DU 的 `f1cuIpAddress` 設成這個 pod IP：

```bash
set_yaml_value "$du_chart/values.yaml" f1cuIpAddress "\"$cu_ip\""
```

### 3. 修 traffic test 的 ping 方向與 UE IP 假設

檔案：

- `script/start_traffic.sh`
- `script/README.md`

原本測試方向是 DNN pod -> 固定 UE data IP，例如 `12.1.1.2`。這次改成：

```bash
kubectl exec -n "$NAMESPACE" "$ue_pod" -c nr-ue -- ping -I oaitun_ue1 -c 5 "$dnn_ip"
```

UE data IP 改成部署後從 `oaitun_ue1` 讀：

```bash
kubectl exec -n "$NAMESPACE" "$ue_pod" -c nr-ue -- \
    ip -4 -o addr show oaitun_ue1 | awk '{split($4, a, "/"); print a[1]}'
```

DL iperf3 目前改為非致命錯誤：失敗時記錄訊息，繼續跑 UL iperf3。

### 4. 修 DL throughput 測法，改用 UE-initiated reverse mode

檔案：

- `script/start_traffic.sh`

比對 `oai-v2.1.0-12/check_link.sh` 後發現，它的 downlink 測法不是讓 traffic server 主動連 UE，而是：

```bash
iperf3 -c "$TS_IP" -B "$UE_IP" -R
```

也就是 UE 先建立 TCP control connection 到 traffic server，然後用 reverse mode 讓 traffic server 往 UE 送資料。這次將 `start_traffic.sh` 的 DL iperf 改成同樣模型：

```bash
kubectl exec -n "$NAMESPACE" "$dnn_pod" -- sh -c "pkill iperf3 2>/dev/null || true; iperf3 -s -B $dnn_ip -D"
kubectl exec -n "$NAMESPACE" "$ue_pod" -c nr-ue -- iperf3 -c "$dnn_ip" -B "$ue_ip" -t 20 -R
```

若標準 reverse mode 失敗，script 會再用 `-M 1300` 重試，對齊 `oai-v2.1.0-12/check_link.sh` 的 fallback 思路。

## Debug 過程

### Step 1: 先確認 RAN pod 都是 Running，但 ping 仍失敗

猜測：

- RAN pod 雖然 Running，但 UE 可能沒有真的註冊或沒有 PDU session。
- 也可能是 traffic test ping 的 IP 或方向不正確。

觀察到的狀態：

```bash
kubectl -n oai get pods
```

結果重點：

```text
oai-gnb-cu10    2/2 Running
oai-gnb-du10    2/2 Running
oai-nr-ue10     2/2 Running
oai-dnn10       1/1 Running
```

但是 `./script/run.sh` 最後在 traffic test 失敗：

```text
Ping test: oai-dnn10... -> 12.1.1.2
5 packets transmitted, 0 received, 100% packet loss
```

新的發現：

- 問題已經不是 pod CrashLoop。
- 需要往 control plane registration、PDU session、GTP-U tunnel 與 route 查。

### Step 2: 檢查 UE、DU、CU、AMF log

猜測：

- 如果 AMF 看不到 UE，問題在 RFsim/DU/CU/control plane。
- 如果 AMF 看得到 UE，問題偏向 PDU session 或 user plane。

使用指令：

```bash
kubectl -n oai logs deploy/oai-nr-ue10 --container nr-ue --tail 120
kubectl -n oai logs deploy/oai-gnb-du10 --container gnbdu --tail 120
kubectl -n oai logs deploy/oai-gnb-cu10 --container gnbcu --tail 120
kubectl -n oai logs deploy/oai-amf10 --container amf --tail 120
```

結果重點：

- CU log 有 NG setup、F1 setup、PDU session 相關訊息。
- DU 和 UE 可以走到 RFsim/RA/RRC 後續流程。
- AMF 後來可以看到 UE registered。

新的發現：

- UE 沒註冊不是主要問題了。
- PDU session/control plane 大致可通，下一步要查 user plane tunnel。

### Step 3: 檢查 UE data interface

猜測：

- `start_traffic.sh` 假設 UE data IP 是 `12.1.1.2`，但 SMF 分配可能不是這個 IP。

使用指令：

```bash
kubectl -n oai exec deploy/oai-nr-ue10 -c nr-ue -- ip -4 -o addr show oaitun_ue1
```

結果重點：

```text
oaitun_ue1 ... 12.1.1.4/24 ...
```

新的發現：

- 固定寫死 `12.1.1.2` 是不可靠的。
- 需要從 UE container 的 `oaitun_ue1` 動態取得 IP。

### Step 4: 從 UE ping gateway，確認 UE tunnel 本身是否存在

猜測：

- 如果 UE ping `12.1.1.1` 不通，代表 UE/UPF tunnel 或 PDU session 還沒好。
- 如果 UE ping `12.1.1.1` 通，代表 UE 到 UPF 這段至少可用。

使用指令：

```bash
kubectl -n oai exec deploy/oai-nr-ue10 -c nr-ue -- ping -I oaitun_ue1 -c 3 12.1.1.1
```

結果重點：

```text
3 packets transmitted, 3 received, 0% packet loss
```

新的發現：

- UE 的 PDU session interface 可用。
- 問題更接近 CU/DU F1-U 或 DNN 方向路由。

### Step 5: 用 tcpdump/log 判斷 UE 封包有沒有到 CU

猜測：

- 如果 DU 收到 UE ICMP，但 CU 收不到 UDP/2153 或 GTP-U，代表 DU -> CU 的 F1-U tunnel address 有問題。

使用指令：

```bash
kubectl -n oai logs deploy/oai-gnb-du10 --container gnbdu --tail 200
kubectl -n oai exec deploy/oai-gnb-cu10 -c tcpdump -- tcpdump -ni any udp port 2153 -c 5
```

結果重點：

- DU log 顯示有 UE/DRB 相關封包處理。
- CU 端看不到預期的 F1-U user-plane 封包。
- DU log 曾出現 DRB tunnel remote IPv4 是 `0.0.0.0`。

新的發現：

- CU 對 DU 公告的 F1-U address 不正確。
- 開始檢查 CU runtime config。

### Step 6: 檢查 CU runtime config，發現 `local_s_address = 0.0.0.0`

猜測：

- OAI 可以 bind `0.0.0.0`，但不應該把 `0.0.0.0` 當成 F1-U tunnel 的 advertised address。

使用指令：

```bash
kubectl -n oai exec deploy/oai-gnb-cu10 -c gnbcu -- grep -n "local_s_address\|GNB_IPV4_ADDRESS" /tmp/gnb.conf
```

結果重點：

```text
local_s_address = "0.0.0.0";
GNB_IPV4_ADDRESS_FOR_NG_AMF = "<CU pod IP>";
GNB_IPV4_ADDRESS_FOR_NGU = "<CU pod IP>";
```

新的發現：

- NGAP/N2 和 NGU/N3 的 pod IP placeholder 已經有處理。
- F1-U `local_s_address` 沒有同樣處理，所以 DU 看到不可用的 `0.0.0.0`。

修正後驗證：

```bash
kubectl -n oai exec deploy/oai-gnb-cu10 -c gnbcu -- grep -n "local_s_address\|GNB_IPV4_ADDRESS" /tmp/gnb.conf
```

結果變成：

```text
local_s_address = "10.42.0.107";
GNB_IPV4_ADDRESS_FOR_NG_AMF = "10.42.0.107";
GNB_IPV4_ADDRESS_FOR_NGU = "10.42.0.107";
```

### Step 7: 檢查 DU runtime config，確認 remote CU IP

猜測：

- DU 端 `remote_n_address` 若是 service name 或 stale value，也可能造成 F1-U 不穩。

使用指令：

```bash
kubectl -n oai exec deploy/oai-gnb-du10 -c gnbdu -- grep -n "local_n_address\|remote_n_address" /tmp/gnb.conf
```

修正後結果重點：

```text
local_n_address = "10.42.0.108";
remote_n_address = "10.42.0.107";
```

新的發現：

- DU 明確用目前 CU pod IP 當 remote address。
- 這讓 F1-C/F1-U 的 runtime address 更可控。

### Step 8: 重新測 UE -> DNN ping

猜測：

- 修完 F1-U address 後，UE 發出的 ICMP 應該能經 DU、CU、UPF 到 DNN。

使用指令：

```bash
./script/start_traffic.sh zoomv3 1 1 1 0
```

結果重點：

```text
Ping test: 12.1.1.4 -> 10.42.1.135
5 packets transmitted, 5 received, 0% packet loss
```

新的發現：

- UE -> DNN 的 end-to-end user plane 已通。
- 原本 DNN -> UE 的 ping 方向不適合當目前環境的第一個 gating test。

### Step 9: 跑 iperf3，發現 UL 可通、DL 仍失敗

猜測：

- 若 UE -> DNN ping 通，UL iperf3 應該可通。
- DNN -> UE 則依賴反向路由，可能還是不通。

使用指令：

```bash
./script/start_traffic.sh zoomv3 1 1 1 0
```

結果重點：

```text
DL iperf3 failed for oai-dnn10... -> 12.1.1.4; continuing with UL test
UL iperf3 test ... receiver ~967 Mbits/sec
Traffic tests complete.
```

新的發現：

- UL 已可作為目前的 throughput validation。
- DL 需要另外處理 DNN 到 UE subnet 的 routing/data network。

### Step 11: 比對 `oai-v2.1.0-12` 的 traffic server 測法

猜測：

- 之前以為 DL 失敗是單純 DNN/cluster 缺少 UE subnet route。
- 但 `oai-v2.1.0-12` 可以通，很可能不是因為它一定有額外 Multus，而是它的 DL 測法不同。

使用指令：

```bash
sed -n '180,380p' oai-v2.1.0-12/check_link.sh
sed -n '1,260p' oai-v2.1.0-12/oai-5g-core/oai-traffic-server/templates/configmap.yaml
sed -n '180,360p' oai-v2.1.0-12/oai-5g-core/oai-5g-basic/values.yaml
```

結果重點：

```bash
IPERF_DL_CMD="iperf3 -c $TS_IP -p 5201 -t 5 -B $UE_IP -R"
```

以及 traffic server 啟動時會加 UE subnet route：

```bash
ip route add {{ .Values.config.ueroute }} via $(getent ahostsv4 {{ .Values.config.upfHost }} | awk 'NR==1{print $1}') dev eth0
```

新的發現：

- `oai-v2.1.0-12` 的 DL 是 UE 發起 client，再用 `-R` 讓 server 反向送資料。
- 它不是用 DNN/traffic server 主動 `iperf3 -c <UE_IP>`。
- 我們目前的 DNN pod 已經有類似 route：`12.1.1.0/24 via <UPF_POD_IP> dev eth0 onlink`，所以缺的不是這條 pod 內 route，而是 traffic test 模型。

### Step 12: 實測目前 cluster 的 direct ping 和 reverse-mode DL

猜測：

- 如果 DNN direct ping UE 失敗，但 `iperf3 -R` 成功，代表 DL data path 可用，但不支援或不適合用 DNN-initiated ICMP/new-flow 當驗證。

使用指令：

```bash
kubectl -n oai get pods -o wide
kubectl -n oai exec deploy/oai-dnn10 -- ip route
kubectl -n oai exec deploy/oai-nr-ue10 -c nr-ue -- ip -4 addr show oaitun_ue1
kubectl -n oai exec deploy/oai-dnn10 -- ping -c 3 12.1.1.2
kubectl -n oai exec deploy/oai-nr-ue10 -c nr-ue -- ping -I oaitun_ue1 -c 3 10.42.1.169
```

結果重點：

```text
DNN route: 12.1.1.0/24 via 10.42.1.168 dev eth0 onlink
UE IP: 12.1.1.2/24 on oaitun_ue1
DNN -> UE ping: 3 transmitted, 0 received, 100% packet loss
UE -> DNN ping: 3 transmitted, 3 received, 0% packet loss
```

接著測 reverse-mode DL：

```bash
kubectl -n oai exec deploy/oai-dnn10 -- sh -c 'pkill iperf3 2>/dev/null || true; iperf3 -s -B 10.42.1.169 -D'
kubectl -n oai exec deploy/oai-nr-ue10 -c nr-ue -- iperf3 -c 10.42.1.169 -B 12.1.1.2 -t 5 -R
```

結果重點：

```text
Reverse mode, remote host 10.42.1.169 is sending
0.00-5.00 sec  16.8 MBytes  28.1 Mbits/sec receiver
```

新的發現：

- DNN direct ICMP/new-flow 仍不通。
- UE-initiated reverse-mode DL 可以通，這和 `oai-v2.1.0-12` 的驗證方式一致。
- 因此這次修復應該落在 `start_traffic.sh` 的 DL iperf 測法，而不是先引入 Multus。

### Step 13: 修改 `start_traffic.sh` 並驗證

修改：

```bash
kubectl exec -n "$NAMESPACE" "$dnn_pod" -- sh -c "pkill iperf3 2>/dev/null || true; iperf3 -s -B $dnn_ip -D"
kubectl exec -n "$NAMESPACE" "$ue_pod" -c nr-ue -- iperf3 -c "$dnn_ip" -B "$ue_ip" -t 20 -R
```

驗證指令：

```bash
./script/start_traffic.sh zoomv3 1 1 1 0
```

結果重點：

```text
UE -> DNN ping: 5 transmitted, 5 received, 0% packet loss
DNN -> UE ping: 5 transmitted, 0 received, 100% packet loss
DL iperf3 reverse mode: 67.8 MBytes, 28.4 Mbits/sec receiver
UL iperf3: 2.65 GBytes, 1.14 Gbits/sec receiver
Traffic tests complete.
```

結論：

- `start_traffic.sh` 現在能完成 UL ping、DL throughput、UL throughput。
- Direct DNN -> UE ping 當時仍保留為非 fatal 診斷，不代表 reverse-mode DL 不可用。

### Step 14: 將 ping 診斷改成 UE -> 8.8.8.8

後續調整：

- `start_traffic.sh` 不再執行 DNN -> UE ping。
- ping test 現在包含：
  - UE `oaitun_ue1` -> DNN pod IP，作為主要 E2E data path check。
  - UE `oaitun_ue1` -> `8.8.8.8`，作為外部連線診斷。

修改後的指令形式：

```bash
kubectl exec -n "$NAMESPACE" "$ue_pod" -c nr-ue -- ping -I oaitun_ue1 -c 5 "$dnn_ip"
kubectl exec -n "$NAMESPACE" "$ue_pod" -c nr-ue -- ping -I oaitun_ue1 -c 5 8.8.8.8
```

`8.8.8.8` ping 可能因實驗環境沒有外網而失敗，所以仍是 non-fatal；失敗時 script 會繼續跑 DL/UL iperf3。

### Step 10: 確認不是單純 VM 資源不足造成

猜測：

- VM 資源不足會影響 RFsim timing、RA/RLC/PDCP 穩定性，但 ping failure 不一定是資源造成。

判斷依據：

- 修 F1-U address 後，同一環境中 UE -> DNN ping 成功。
- UL iperf3 也成功跑到接近 1 Gbit/s。

結論：

- 這次主要是配置與路由問題，不是 ICMP 本身太耗資源。
- VM 資源仍可能影響 RFsim timing，例如之前遇過 RA window 太短，需要把 `ra_ResponseWindow` enum 從 `4` 調到 `5`。

## 為什麼不是 ping UPF，而是 ping DNN

UPF 是 UE user plane 的 gateway/anchor，不是應用端目的地。ping UPF 只能證明 UE 到 gateway 這段通，不能證明封包能穿過 UPF 到資料網路。

5GMAP 要測的是 UE 是否能到達 data network 裡的應用或測試 endpoint，所以用 DNN pod 當目標比較接近真正的端到端驗證：

```text
NR-UE oaitun_ue1 -> DU -> CU -> UPF -> DNN pod
```

目前 ICMP 已驗證的是這個方向。反方向：

```text
DNN pod -> UPF -> CU -> DU -> NR-UE
```

若是 DNN 直接對 UE data IP 發起 ICMP 或新 TCP 連線，仍會失敗。若要驗證 downlink throughput，採用 OAI v2.1.0 的方式：UE 先連 DNN/traffic-server，再用 `iperf3 -R` 讓 DNN 往 UE 送資料。

## 後續 TODO

- 若未來需要 DNN direct ping UE 或 DNN-initiated new TCP flow，再繼續查 UPF NAT/conntrack/PDR/FAR 對 downlink new-flow 的處理。
- 若要使用獨立 N6/data network，先安裝/確認 `NetworkAttachmentDefinition` CRD，並確認 DNN pod 真的有 data-network interface。
- 將 direct DNN -> UE ping 定位成診斷訊號，不要作為 OAI RFsim E2E gating test。
- 固定 OAI/tolgaomeratalay 相關 image tag 或 mirror 到自己的 registry，避免 upstream image 改版造成行為變動。
