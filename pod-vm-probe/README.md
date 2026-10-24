# Pod and VM Probe

部署驗證與量測結果見[實驗紀錄](experiments/README.md)。

5gmap 的資源狀態收集工具。第一版將 Pod／節點／GPU 的資源觀測送達接收 Pod，結合拓樸、工作負載需求及資源政策設定，提供可查詢的 input snapshot。

實驗室環境為 RKE／Kubernetes `v1.24.10` 的裸機 Linux 叢集。2026-10-23 的首次部署已驗證三個 node 的 CPU／RAM 指標可讀、兩個 worker 的 node probe 可送資料，且 `edge` 的 AMD 內顯可由 Pod 讀到 GPU busy 與 VRAM／GTT 用量。`az` 的 Intel 內顯利用率目前為 unsupported；控制節點 RTX 2070 SUPER 的 NVIDIA 量測路徑尚未就緒。各程式職責見 [src 說明](src/README.md)，硬體與部署條件見 [環境盤點](docs/lab-environment.md)。

## 架構

```text
cluster-probe  ──┐
node-probe     ──┼─ HTTP JSON → Service → resource-manager Pod → 保存／查詢
配置與情境資料 ──┘                          decision／executor 介面預留
```

| 元件 | 位置 | 責任 |
| --- | --- | --- |
| cluster-probe | 每個 cluster 一個 Deployment | K8s Pod／Node metadata、health、Events、capacity／requests／limits；kubelet 資源 metrics |
| node-probe | 每個受測 node 一個 DaemonSet Pod；必要時採 node 本機程序 | 主機視角 CPU／RAM、可見 GPU、指定網卡 counters 與基本連線探測 |
| resource-manager | 一個 Deployment＋Service＋持久儲存 | 接收、驗證、去重、保存、合併配置、標示過期資料及提供查詢 |

接收端只回覆資料已收妥，不產生決策或執行資源調整。RSU 的 contributors／受援助對象使用固定情境資料，不處理影像。

## 第一批輸入

- **觀測：**Pod／container 狀態與事件、CPU／RAM 使用量、Node Ready／pressure、OS 可用 RAM、GPU 利用率與 GPU memory、指定網卡 RX／TX 與連線狀態。
- **資源與拓樸：**node capacity／allocatable、Pod requests／limits、Pod→node→site、功能角色與服務位置。
- **配置與假設：**測試工作負載需求、額外 RAN 保留量、門檻、資料 TTL、RSU 情境、尚未量測的 UL capacity／跨 edge 網路條件。

Pod 與 node 使用量分層保存，不能重複相加；VM 可見資源不能代表整台實體主機。GPU 無法映射至 Pod 時只報 device 層級。網卡流量及 ping 結果不能代表可達 uplink capacity。

## 傳送與資料品質

Probe 定期送至 `POST /v1/observations`；接收端保存後 ACK，以 `probe_id + boot_id + sequence` 去重。`GET /v1/state` 提供最新狀態及每項資料的新鮮度。

每項資料保留對象 ID、觀測時間、來源、單位、採樣時間窗與有效性；配置與假設分別標 `configured`、`simulated`，實測標 `measured`。無裝置、無權限、採集失敗與逾期需分別呈現，不能用零代替缺值。Node 心跳與 K8s Node Ready 為不同訊號。

## 部署與查看

在 `5gmap/` 執行：

```bash
./script/run.sh --pod_probe
# 或：pod_probe=1 ./script/run.sh
```

`pod_probe` 預設為 `0`，不建立 probe。旗標也可用 `--pod_probe=1` 或 `--pod-probe=1`；`deploy.sh` 支援同樣參數。啟用時，`deploy.sh` 在 RAN 部署後建立 receiver、cluster probe、兩個 worker 上的 node probe；`run.sh` 清理時同步移除。單獨清理請用 `POD_PROBE=1 ./script/undeploy.sh 1 1`。資料保存在 `az` 節點 `/var/lib/pod-vm-probe`，清理工作負載時不刪資料。

probe 使用 `python:3.12-slim` 與部署時產生的程式 ConfigMap，無需在本機建置 image。首次部署已在兩個 worker 成功取得 image；其他環境可透過 `POD_PROBE_IMAGE` 指定相容的 Python image。namespace 預設為 `oai`，與既有腳本共用 `NAMESPACE`；初版同一 cluster 只部署一份 probe，因 RBAC 名稱固定。

```bash
kubectl get deployment,daemonset,service -n oai | grep pod-probe
kubectl logs -n oai deployment/pod-probe-cluster
kubectl get pods -n oai -l app=pod-probe-node -o wide
kubectl logs -n oai pod/<node-probe-pod-name> --tail=20
kubectl port-forward -n oai service/pod-probe-receiver 8080:8080
```

Port forward 執行期間，在另一個 shell 查詢更新後的接收端：

```bash
curl http://127.0.0.1:8080/healthz
curl -s http://127.0.0.1:8080/v1/summary
curl -s 'http://127.0.0.1:8080/v1/state?kind=gpu&limit=20'
curl -s 'http://127.0.0.1:8080/v1/state?kind=node&metric=node_cpu_usage_cores&limit=20'
```

輸入格式為 `schema_version`、`probe_id`、`boot_id`、`sequence` 加 `observations` 陣列。接收端先保存再回覆，重複批次以三個發送欄位去重；`/v1/state` 提供最新記錄、stale 標記與 [固定情境設定](config/fixtures.json)，可用 `kind`、`metric`、`limit`、`offset` 篩選與分頁；不帶條件會輸出大量資料。`/v1/summary` 提供精簡的數量與非正常狀態摘要。原始紀錄保留 24 小時，過期資料由定期清理移除。有來源時間戳時以 `observed_at` 判斷資料是否過期，否則使用 `collected_at`。CPU 來源為 kubelet 累計計數器的相鄰樣本差值，最初一筆不產生 CPU cores。

第一版從 `/proc`／sysfs 讀取主機網卡 counters，並對另一個 worker 的 SSH port 做低頻 TCP connect 探測；該時間只代表此方法的連線耗時，不代表無線 UL capacity。AMD GPU 是 `edge` 的 device 層級資料，未建立 Pod 對 GPU 映射。這次部署已驗證 Pod 內 AMD sysfs 及 probe ServiceAccount 經 API proxy 讀 kubelet 的路徑；主機檔案以唯讀方式掛載。接收端 SQLite 使用固定在 `az` 節點的 hostPath。fixture 範例由實際實驗條件填入後再作推論。

### 首次部署觀察與更新

2026-10-23 部署時，兩個 node probe、cluster probe、receiver 均為 Ready，receiver 持續接受三個來源的 POST。啟動最初幾次 `Connection refused` 發生於 receiver 就緒前，記憶體佇列其後清空。`edge` 已回報 AMD `gpu_busy_percent` 與 VRAM／GTT 五個 sysfs 欄位；兩個 worker 的 TCP connect 探測均有成功紀錄。`az` 的 GPU busy 回報 unsupported。

初版在約 8 分鐘累積 43 MB SQLite 資料；檢查時 Event 有 16,400 筆歷史紀錄，但只有 219 個不同 Event UID。此次更新改為只在 Event `resourceVersion` 變化時送出，並新增最新值表、精簡查詢及較少的成功日誌。原有重複歷史紀錄仍由 24 小時保留機制清理。

本機檢查：

```bash
python3 -m unittest discover -s pod-vm-probe/tests -v
```

## 後續驗收

接下來用受控 CPU／RAM 負載、Pod 重建、probe 失聯與接收端重啟檢查數值變化、UID 關聯、資料過期與保存。先以 `/v1/summary` 確認三個來源及非正常狀態，再查具體指標；receiver 重啟前後對照 `/v1/state?kind=gpu&limit=20` 與一個 Pod UID。GPU 負載驗證需先選定此 AMD 內顯可執行的計算程式，不能只以靜置時的 0% 認定負載指標正確。決策演算法、資源配置執行與平台整合不列入此階段。
