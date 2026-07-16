# 5GMAP Script 使用說明

這個目錄放的是新版的一鍵部署流程，用來把原本的 `gnbsim` 流程改成 `oai-5g-ran` 的 `oai-gnb` + `oai-nr-ue`。

目前主流程是：

```text
run.sh -> deploy.sh -> start_traffic.sh -> undeploy.sh
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

執行：

```bash
cd /home/genechen/5gmap
./script/run.sh
```

流程完成 traffic test 後，script 會停在 cleanup prompt：

```text
Press ENTER to cleanup, or Ctrl-C to keep the deployment running...
```

按 Enter 會清掉本次部署的 core、gNB、NR-UE、DNN。按 `Ctrl-C` 可以保留部署結果，方便你手動查看 pod log 或 debug。

## 常用參數

參數用環境變數設定：

```bash
USECASE=zoomv3 \
NUM_USERS=1 \
NUM_SLICES=1 \
NUM_ITERATIONS=1 \
TEST_TYPE=0 \
./script/run.sh
```

常用變數：

```text
USECASE          DNN image tag 與 log use case 名稱，預設 zoomv3
NUM_USERS        每個 slice 的 UE 數量，預設 1
NUM_SLICES       slice 數量，預設 1
NUM_ITERATIONS   iperf3 測試重複次數，預設 1
TEST_TYPE        目前 OAI RAN 只支援 0，也就是 pod-level test
NAMESPACE        Kubernetes namespace，預設 oai
AUTO_CLEANUP     設成 1 時，測試結束後不詢問，直接 cleanup
DELETE_MYSQL     cleanup 時設成 1 才會刪 mysql release
```

例如測試結束後自動清理：

```bash
AUTO_CLEANUP=1 ./script/run.sh
```

使用不同 namespace：

```bash
NAMESPACE=oai-test ./script/run.sh
```

## 分段執行

如果你想分開 debug，可以手動分段跑。

只部署：

```bash
./script/deploy.sh zoomv3 1 1
```

參數順序是：

```text
deploy.sh <USECASE> <NUM_USERS> <NUM_SLICES>
```

只跑 traffic test：

```bash
./script/start_traffic.sh zoomv3 1 1 1 0
```

參數順序是：

```text
start_traffic.sh <USECASE> <NUM_USERS> <NUM_SLICES> <NUM_ITERATIONS> <TEST_TYPE>
```

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
   - `oai-gnb`
   - `oai-nr-ue`
   - `oai-dnn`
5. 設定 DNN pod 的 NAT 與到 UE data network `12.1.1.0/24` 的 route。

## Traffic test 與 log

`start_traffic.sh` 目前會先從 DNN pod ping 對應的 UE data IP：

```text
12.1.1.2
12.1.1.3
...
```

如果 DNN pod 和 NR-UE container 裡都有 `iperf3`，才會額外跑 DL/UL throughput test。

log 會寫到：

```text
5gcore/logs/<USECASE>/throughput/
```

例如：

```text
5gcore/logs/zoomv3/throughput/ping.1.log.txt
5gcore/logs/zoomv3/throughput/throughput.DL.1.log.txt
5gcore/logs/zoomv3/throughput/throughput.UL.1.log.txt
```

## 注意事項

- `deploy.sh` 會修改 `5gcore/` 和 `oai-5g-ran/` 裡面的 Helm `values.yaml` / `Chart.yaml`，這沿用原本專案的做法。
- `TEST_TYPE=1` 的 host-level test 尚未移植到 OAI RAN 流程，目前只支援 `TEST_TYPE=0`。
- MySQL 預設不會在 cleanup 時刪除，避免每次重跑都重建 subscriber database。
- 如果你保留部署結果後要手動清理，可以再跑 `./script/undeploy.sh <NUM_USERS> <NUM_SLICES>`。

## 中途失敗後如何重跑

如果部署中途失敗，例如某個 Helm values key 找不到，先依照本次執行的 users/slices 清理已經建立的 release：

```bash
cd /home/genechen/5gmap
./script/undeploy.sh 1 1
```

上面會清掉 `nrf10`、`udr10`、`udm10`、`ausf10` 等 core release，以及對應的 gNB、NR-UE、DNN。不存在的 release 會自動略過。

如果也想把 MySQL 一起刪掉：

```bash
DELETE_MYSQL=1 ./script/undeploy.sh 1 1
```

清完後重新跑：

```bash
./script/run.sh
```
