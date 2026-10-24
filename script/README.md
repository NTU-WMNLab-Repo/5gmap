## Pod／VM 資源收集

`pod_probe` 預設為 `0`。加上旗標時，`run.sh` 會在 RAN 部署後建立 `pod-vm-probe` 的 receiver、cluster probe 與 node probe；清理時同步移除 Pod 和 RBAC，保留 `az` 主機上的 SQLite 資料。

```bash
./script/run.sh --pod_probe
pod_probe=1 ./script/run.sh
./script/deploy.sh zoomv3 1 1 --pod_probe
POD_PROBE=1 ./script/undeploy.sh 1 1
```

未提供旗標時不建立 probe。可用 `--pod_probe=0` 明確關閉。部署與查詢方式見 [Pod and VM Probe](../pod-vm-probe/README.md)。

## Experimental RanProxy Flag

**Warning: `RanProxy=1` is experimental. It enables the F1AP/F1-C, NGAP/N2,
and PFCP tracing proxies. They forward control messages unchanged and export
spans, but production hardening and complete procedure-level correlation are
not finished yet. The PFCP proxy currently emits raw UDP datagram spans only;
it does not decode PFCP or correlate PFCP transactions.**

Use `RanProxy=1` to insert experimental tracing proxies into the control-plane
paths:

- `f1proxy<user>` between each DU and CU for F1AP/F1-C.
- `ngapproxy<user>` between each CU and AMF for NGAP/N2.
- `pfcpproxy<slice>` between each SMF and UPF for PFCP/N4.

```bash
RanProxy=1 ./script/run.sh
```

Cross-protocol correlation is controlled separately and is disabled by
default. Enable it only together with the RAN proxies:

```bash
RanProxy=1 CrossProtocolCorrelate=1 ./script/run.sh
```

Equivalent CLI forms:

```bash
./script/run.sh --RanProxy 1
./script/run.sh --RanProxy 1 --CrossProtocolCorrelate 1
./script/deploy.sh zoomv3 1 1 rfsim 1 1 1
./script/deploy.sh zoomv3 1 1 --RanProxy 1
./script/deploy.sh zoomv3 1 1 --RanProxy 1 --CrossProtocolCorrelate 1
```

When `RanProxy=1`, `deploy.sh` deploys one `ngapproxy<user>` and one
`f1proxy<user>` per RAN user, plus one `pfcpproxy<slice>` per core slice. It
points the CU AMF target to `ngapproxy<user>`, the DU F1-C target to
`f1proxy<user>`, and renders the SMF's static UPF endpoint as the
`pfcpproxy<slice>` ClusterIP/FQDN. It also makes the UPF advertise
`pfcpproxy<slice>` as its PFCP Node ID FQDN, so response-driven PFCP traffic
continues through the proxy. The PFCP proxy forwards to the real
`oai-spgwu-tiny<slice>-svc` endpoint.

When `RanProxy=0`, the CU connects directly to the AMF, the DU connects
directly to the CU, `pfcpproxy<slice>` is removed, SMF UPF discovery is
re-enabled, its static UPF endpoint is cleared, and the UPF Node ID FQDN is
restored to `oai-spgwu-tiny<slice>-svc`. This restores the original direct
SMF-UPF PFCP path.

The F1AP and NGAP proxy Deployments use `RAN_LOC`. PFCP is a core-side proxy,
so `pfcpproxy<slice>` uses `CORE_LOC`, which defaults to `az`.

When `CrossProtocolCorrelate=1`, `deploy.sh` also deploys one shared
`control-plane-correlator` and enables its client in every F1AP and NGAP proxy.
UE-related spans are then eligible to share one cross-protocol trace ID. When
`CrossProtocolCorrelate=0`, the correlator is removed and both proxy manifests
are rendered with `ONLINE_CORRELATION_ENABLED=0` and an empty endpoint, which
preserves the previous protocol-local tracing behavior.

`CrossProtocolCorrelate=1` requires `RanProxy=1`; the scripts reject the
otherwise unusable combination.

Useful image variables:

```text
RAN_PROXY_F1AP_IMAGE     Default: docker.io/genechen0203/f1ap-sctp-proxy:latest
RAN_PROXY_NGAP_IMAGE     Default: docker.io/genechen0203/ngap-sctp-proxy:latest
RAN_PROXY_PFCP_IMAGE     Default: docker.io/genechen0203/pfcp-udp-proxy:latest
RAN_PROXY_F1C_PORT       Default: 38472
RAN_PROXY_NGAP_PORT      Default: 38412
RAN_PROXY_PFCP_PORT      Default: 8805
RAN_PROXY_OTEL_ENDPOINT  Default: http://opentelemetry-collector.otel.svc.cluster.local:4317
RAN_PROXY_OTEL_INSECURE  Default: true
CORE_LOC                 Default: az; node selector for PFCP proxy deployments
CROSS_PROTOCOL_CORRELATOR_IMAGE     Default: docker.io/genechen0203/control-plane-correlator:latest
CROSS_PROTOCOL_CORRELATOR_ENDPOINT  Default: http://control-plane-correlator:8080
```

`undeploy.sh` always attempts to remove `f1proxy<user>`, `ngapproxy<user>`,
`pfcpproxy<slice>`, and the shared `control-plane-correlator` resources, so it
is safe to run cleanup after either flag combination.

# 5GMAP Script 使用說明

這個目錄放的是新版的一鍵部署流程，用來把原本的 `gnbsim` 流程改成 `oai-5g-ran` 的 `oai-gnb-cu` + `oai-gnb-du` + `oai-nr-ue`。

目前主流程是：

```text
run.sh -> deploy.sh -> start_iperf_cpu_test.sh -> undeploy.sh
```

## 可以從哪裡執行

不一定要在 `~/5gmap` 目錄底下執行。

這些 script 會用 `BASH_SOURCE` 找到 `script/` 的實際位置，再推回 repo root，所以只要 repo 結構沒有變，就可以從任意目錄執行：

```bash
/home/genechen/5gmap/script/run.sh
```

如果你想用相對路徑執行，才需要先進到 repo root：

```bash
cd /home/genechen/5gmap
./script/run.sh
```

不建議把單一 script 複製到其他目錄執行，因為它們會依賴相對於 repo root 的這些資料夾：

```text
5gcore/
oai-5g-ran/
script/
```

## 前置需求

執行前請確認目前 shell 可以操作 Kubernetes cluster，並且已安裝：

```bash
kubectl
helm
sed
awk
grep
```

也請確認 cluster 內有 `deplocation` node label，因為部署腳本預設會用：

```text
edge
az
```

預設 namespace 是 `oai`。如果不存在，`deploy.sh` 會自動建立。

## 一鍵執行

預設會部署：

- use case: `zoomv3`
- users: `1`
- slices: `1`
- test iterations: `1`
- test type: `0`，也就是 pod-level traffic test
- run mode: `rfsim`
- DeployUE: `1`，也就是會部署 NR-UE 與 DNN

執行：

```bash
cd /home/genechen/5gmap
./script/run.sh
```

流程完成 traffic test 後，script 會停在 cleanup prompt：

```text
Press ENTER to cleanup, or Ctrl-C to keep the deployment running...
```

按 Enter 會清掉本次部署的 core、CU、DU、NR-UE、DNN。按 `Ctrl-C` 可以保留部署結果，方便你手動查看 pod log 或 debug。

如果 `DeployUE=0`，`run.sh` 只會部署到 CU/DU，並跳過 traffic test，因為 NR-UE 與 DNN 不會被部署。

## 常用參數

參數用環境變數設定：

```bash
USECASE=zoomv3 \
NUM_USERS=1 \
NUM_SLICES=1 \
NUM_ITERATIONS=1 \
TEST_TYPE=0 \
RUN_MODE=rfsim \
DeployUE=1 \
./script/run.sh
```

常用變數：

```text
USECASE          DNN image tag 與 log use case 名稱，預設 zoomv3
NUM_USERS        每個 slice 的 UE 數量，預設 1
NUM_SLICES       slice 數量，預設 1
NUM_ITERATIONS   iperf3 測試重複次數，預設 1
TEST_TYPE        目前 OAI RAN 只支援 0，也就是 pod-level test
RUN_MODE         RAN 執行模式，預設 rfsim；可設 rfsim、usrp 或 usrpb210
DeployUE         是否部署 NR-UE 與 DNN，預設 1；可設 0 或 1
NAMESPACE        Kubernetes namespace，預設 oai
AUTO_CLEANUP     設成 1 時，測試結束後不詢問，直接 cleanup
DELETE_MYSQL     cleanup 時設成 1 才會刪 mysql release
```

`DeployUE` 也可以寫成 `DEPLOY_UE`，CLI 參數也支援 `--DeployUE`、`--deploy_ue`、`--deploy-ue`。

例如測試結束後自動清理：

```bash
AUTO_CLEANUP=1 ./script/run.sh
```

使用不同 namespace：

```bash
NAMESPACE=oai-test ./script/run.sh
```

使用 USRP B210/B200 系列：

```bash
./script/run.sh --run_mode usrpb210
```

也可以用 `usrp` 作為 `usrpb210` 的 alias：

```bash
./script/run.sh --runmode usrp
```

也可以用環境變數：

```bash
RUN_MODE=usrpb210 ./script/run.sh
```

`run_mode` 預設是 `rfsim`，所以平常 RF simulator 測試不用特別加參數。

只部署到 DU、不部署 NR-UE/DNN：

```bash
RUN_MODE=usrp DeployUE=0 ./script/run.sh
```

這個情境不需要部署 DNN。DNN 是給 UE attach 後的資料面 traffic test 使用；如果沒有部署 NR-UE，就沒有 UE data IP，也沒有需要連線的 DNN endpoint。

## 常用情境範例

USRP 模式，只部署到 DU，不部署 UE/DNN，cleanup 時清掉 MySQL：

```bash
RUN_MODE=usrp \
DeployUE=0 \
DELETE_MYSQL=1 \
./script/run.sh
```

同一個情境也可以用 CLI 參數：

```bash
DELETE_MYSQL=1 ./script/run.sh --runmode usrp --DeployUE 0
```

RF simulator 模式，部署 UE/DNN，cleanup 時清掉 MySQL：

```bash
RUN_MODE=rfsim \
DeployUE=1 \
DELETE_MYSQL=1 \
./script/run.sh
```

同一個情境也可以用 CLI 參數：

```bash
DELETE_MYSQL=1 ./script/run.sh --runmode rfsim --DeployUE 1
```

如果想跑完後自動 cleanup，可以加上 `AUTO_CLEANUP=1`：

```bash
AUTO_CLEANUP=1 DELETE_MYSQL=1 ./script/run.sh --runmode rfsim --DeployUE 1
```

## 分段執行

如果你想分開 debug，可以手動分段跑。

只部署：

```bash
./script/deploy.sh zoomv3 1 1
```

參數順序是：

```text
deploy.sh <USECASE> <NUM_USERS> <NUM_SLICES> [RUN_MODE] [DeployUE] [RanProxy] [CrossProtocolCorrelate]
```

例如只部署 USRP B210/B200 模式：

```bash
./script/deploy.sh zoomv3 1 1 usrpb210
```

例如只部署 USRP 模式的 core、CU、DU，不部署 NR-UE/DNN：

```bash
./script/deploy.sh zoomv3 1 1 usrp 0
```

也可以用 named arguments：

```bash
./script/deploy.sh zoomv3 1 1 --runmode usrp --DeployUE 0
```

只跑 traffic test：

```bash
./script/start_traffic.sh zoomv3 1 1 1 0
```

只跑 iperf3 與 probe CPU／RAM 採樣：

```bash
POD_PROBE=1 bash ./script/start_iperf_cpu_test.sh zoomv3 1 1 3 0
```

`run.sh` 目前呼叫 `start_iperf_cpu_test.sh`。`start_traffic.sh` 保留供舊流程單獨使用。新腳本先 ping DNN，再以每輪 15 秒基線、20 秒 DL、15 秒 DL 恢復、20 秒 UL、15 秒 UL 恢復的順序執行；有 probe 時每 5 秒查詢一次 `/v1/snapshot`。輸出在 `5gcore/logs/<usecase>/iperf-cpu/<UTC時間>-<PID>/`：`samples.jsonl` 保留每次採樣與來源時間，`cpu-memory-summary.tsv` 列出 node 及 UE／DNN／gNB 的各階段平均 CPU cores、RAM MiB，另有 ping、iperf3 原始輸出及 Pod UID 對照。`POD_PROBE=0` 時只跑流量，不做採樣。

摘要以 `observed_at`（若無則 `collected_at`）判斷來源樣本是否在該階段開始後產生，並對同一階段、同一指標、同一來源時間去重。原始 `samples.jsonl` 仍保留每次查詢結果；kubelet CPU 差值的時間窗可能跨越階段邊界，因此短階段的平均值仍需搭配來源時間判讀。

UL iperf3 用 `-B <UE data IP>` 綁定 `oaitun_ue1` 的來源位址；實驗室的 UE 路由表會把該來源位址的封包導向 `oaitun_ue1`。檢查 UL 原始輸出的 `local` 欄位應為 `12.1.1.x` 等 UE data IP；若顯示 `10.42.x.x` 的 Pod IP，該輪流量走的是 Pod 網路，不能用來評估 RAN uplink。

參數順序是：

```text
start_traffic.sh <USECASE> <NUM_USERS> <NUM_SLICES> <NUM_ITERATIONS> <TEST_TYPE>
```

`start_traffic.sh` 需要 NR-UE 與 DNN 都存在，所以只適合 `DeployUE=1` 的部署。如果前面用 `DeployUE=0`，請不要單獨跑 traffic test。

只清理：

```bash
./script/undeploy.sh 1 1
```

參數順序是：

```text
undeploy.sh <NUM_USERS> <NUM_SLICES>
```

如果連 MySQL 也要刪：

```bash
DELETE_MYSQL=1 ./script/undeploy.sh 1 1
```

## 部署內容

`deploy.sh` 會做幾件事：

1. 確認 namespace 存在。
2. 如果 `mysql` release 不存在，就部署 `5gcore/mysql`。
3. 依 slice 部署 core network functions：
   - NRF
   - UDR
   - UDM
   - AUSF
   - AMF
   - SMF
   - UPF
4. 依 user 部署：
   - `oai-gnb-cu`
   - `oai-gnb-du`
   - `oai-nr-ue`
   - `oai-dnn`
5. 設定 DNN pod 的 NAT 與到 UE data network `12.1.1.0/24` 的 route。

如果 `DeployUE=0`，第 4 步只會部署 `oai-gnb-cu` 和 `oai-gnb-du`，並跳過 `oai-nr-ue`、`oai-dnn` 以及第 5 步的 DNN route/NAT 設定。

## Traffic test 與 log

`start_traffic.sh` 會先從 NR-UE 的 `oaitun_ue1` ping DNN pod IP。UE data IP 會從 `oaitun_ue1` 動態讀取，不再假設一定是：

```text
12.1.1.2
12.1.1.3
...
```

接著會從 NR-UE 的 `oaitun_ue1` ping `8.8.8.8` 作為外部連線診斷；如果實驗環境沒有外網，這個 ping 失敗時不會中斷測試。

如果 DNN pod 和 NR-UE container 裡都有 `iperf3`，才會額外跑 throughput test。UL 方向是 NR-UE -> DNN；DL 方向參考建翰學長提供的 `oai-v2.1.0-12/check_link.sh` 驗證流程，由 NR-UE 發起 `iperf3 -c <DNN_IP> -B <UE_IP> -R`，DNN 再往 UE 送 downlink data。

log 會寫到：

```text
5gcore/logs/<USECASE>/throughput/
```

例如：

```text
5gcore/logs/zoomv3/throughput/ping.UL.1.log.txt
5gcore/logs/zoomv3/throughput/ping.INET.1.log.txt
5gcore/logs/zoomv3/throughput/throughput.DL.1.log.txt
5gcore/logs/zoomv3/throughput/throughput.UL.1.log.txt
```

## USRP DU 啟動成功判斷

如果使用 `RUN_MODE=usrp DeployUE=0` 只部署到 DU，可以用 DU pod log 確認 USRP 是否真的被 OAI DU 使用：

```bash
kubectl logs <oai-gnb-du-pod> -n oai
```

例如：

```bash
kubectl logs oai-gnb-du10-7f6f496dbb-8dtgk -n oai
```

看到下面幾類訊息時，代表 DU 已經連到 CU，並且 UHD/OAI 已成功偵測與啟動 B210/B200 系列 USRP：

```text
CMDLINE: "/opt/oai-gnb/bin/nr-softmodem" ... "--continuous-tx" ...
[MAC]    I received F1 Setup Response from CU oai-gnb-cu10-usrp
[HW]     I Found USRP b200
[INFO] [B200] Detected Device: B210
[INFO] [B200] Operating over USB 3.
[HW]     I Actual RX sample rate: 46.080000MSps...
[HW]     I Actual TX sample rate: 46.080000MSps...
[HW]     I [RAU] has loaded USRP B200 device.
[PHY]    I RU 0 rf device ready
[PHY]    I RU 0 RF started cpu_meas_enabled 0
```

這裡的 `received F1 Setup Response from CU` 表示 DU/CU 的 F1 interface 已建立；`Detected Device: B210`、`Operating over USB 3.` 和 `RU 0 RF started` 則表示 DU container 已經透過 UHD 找到並啟動實體 USRP。

## 注意事項

- `deploy.sh` 會修改 `5gcore/` 和 `oai-5g-ran/` 裡面的 Helm `values.yaml` / `Chart.yaml`，這沿用原本專案的做法。
- `oai-gnb-cu` 和 `oai-gnb-du` 會開啟 `mountConfig`，並掛載 `gnb.conf` 到 `/opt/oai-gnb/etc`，因為目前使用的 `oaisoftwarealliance/oai-gnb:develop` image 啟動時需要這個設定檔。
- `RUN_MODE=usrpb210` 或 `RUN_MODE=usrp` 目前只完成 script/chart 設定，會讓 DU/UE 使用 B210/B200 系列的 `b2xx` 設定並掛載 host `/dev/bus/usb/`。如果只有一台 USRP，請使用 `DeployUE=0` 先部署到 DU。
- `TEST_TYPE=1` 的 host-level test 尚未移植到 OAI RAN 流程，目前只支援 `TEST_TYPE=0`。
- MySQL 預設不會在 cleanup 時刪除，避免每次重跑都重建 subscriber database。
- 如果你保留部署結果後要手動清理，可以再跑 `./script/undeploy.sh <NUM_USERS> <NUM_SLICES>`。

## 中途失敗後如何重跑

如果部署中途失敗，例如某個 Helm values key 找不到，先依照本次執行的 users/slices 清理已經建立的 release：

```bash
cd /home/genechen/5gmap
./script/undeploy.sh 1 1
```

上面會清掉 `nrf10`、`udr10`、`udm10`、`ausf10` 等 core release，以及對應的 CU、DU、NR-UE、DNN。不存在的 release 會自動略過；如果前面是 `DeployUE=0`，沒有部署的 NR-UE/DNN 也會被自動略過。

如果也想把 MySQL 一起刪掉：

```bash
DELETE_MYSQL=1 ./script/undeploy.sh 1 1
```

清完後重新跑：

```bash
./script/run.sh
```
