# 程式模組

這個目錄是 probe 與接收端的程式碼。部署腳本會把四個 `.py` 檔放入 `pod-probe-code` ConfigMap，掛載至 Pod 的 `/app`；執行環境為 Python 3.12，未使用額外 Python 套件。

| 檔案 | 執行位置 | 職責 |
| --- | --- | --- |
| `common.py` | 兩種 probe 共用 | 透過 Pod ServiceAccount 與叢集 API 通訊、建立含來源／時間／狀態的觀測紀錄、將批次送至 receiver；傳送失敗時保留最多 60 批記憶體佇列 |
| `cluster_probe.py` | 單一 `pod-probe-cluster` Deployment | 目標每 10 秒讀取 Node、Pod、Event、Service 與 Endpoints；經 API server 的 node proxy 讀 kubelet `/metrics/resource`，計算 node／Pod／container CPU cores，收集 memory working set；以 UID 關聯 Pod 和 container，並附上當次完整物件清單 |
| `node_probe.py` | 兩個 worker 各一個 `pod-probe-node` DaemonSet Pod | 每 5 秒從主機唯讀掛載的 `/proc`、`/sys` 取得 OS 可用記憶體、CPU busy、網卡 counters 與 AMD GPU 指標；每約 10 秒對另一個 worker 的 TCP 22 埠做連線探測 |
| `receiver.py` | `pod-probe-receiver` Deployment | 驗證批次、以 `probe_id + boot_id + sequence` 去重、寫入 SQLite 歷史與最新值、合併固定情境設定，依物件清單、TTL 與狀態提供決策輸入快照；不執行資源決策 |

```text
cluster_probe.py ─┐
                  ├─ common.py → POST /v1/observations → receiver.py → SQLite
node_probe.py ────┘                                   ├─ GET /v1/summary
                                                     ├─ GET /v1/state
                                                     └─ GET /v1/snapshot
```

`/v1/summary` 回傳各來源、對象類型、狀態與過期數量。`/v1/state` 回傳最新觀測；`/v1/snapshot` 依 Kubernetes 完整物件清單、TTL 與狀態篩出可用輸入，並列出缺少的核心 node 指標。接收端啟動時會從既有歷史紀錄建立最新值表，讓更新程式後沿用原本的 SQLite 資料。Event 僅在 Kubernetes `resourceVersion` 變化時再送出；重啟後會重新發送目前仍在 API 清單中的 Event。

主機樣本的 `collected_at` 為採集時間；kubelet 或 Kubernetes Event 提供來源時間時另填 `observed_at`。`status=unsupported` 表示主機有設備但沒有對應量測欄位，例如 `az` 的 Intel 內顯。Node 使用量與 Pod 使用量分層保存，不相加；TCP connect 時間不代表無線 uplink capacity。

## kubelet CPU 採集週期

`cluster_probe.py` 的查詢目標週期是 10 秒；實際週期還會受到 API 查詢耗時影響。這個設定接近實驗室目前觀察到的 kubelet **node CPU 來源時間**更新量級，不代表每次查詢都會得到新樣本。2026-10-29 在 `edge` (`192.168.1.68`) 直接向 kubelet 查詢同一項 `node_cpu_usage_seconds_total`，約每秒查一次，節錄如下（左欄為查詢時的 UTC 時間，末欄為 kubelet 回傳的 Unix 毫秒時間戳）：

```text
14:22:37  node_cpu_usage_seconds_total 630657.015 1793283755384
14:22:38  node_cpu_usage_seconds_total 630657.015 1793283755384
14:22:44  node_cpu_usage_seconds_total 630657.015 1793283755384
14:22:45  node_cpu_usage_seconds_total 630658.218 1793283765399
14:22:48  node_cpu_usage_seconds_total 630658.218 1793283765399
```

兩個不同的來源時間戳相隔 10,015 ms。檢查方式是在 controller 執行：

```bash
for i in $(seq 1 12); do
    date -u +%H:%M:%S
    kubectl get --request-timeout=5s --raw \
        /api/v1/nodes/192.168.1.68/proxy/metrics/resource \
        | grep '^node_cpu_usage_seconds_total'
    sleep 1
done
```

CPU cores 由相鄰兩次**不同來源時間**的累積 CPU 秒數差除以時間差得到。來源時間未前進時不重算；時間前進而累積值不變時會得到有效的 `0 cores`。提高查詢頻率能減少發現新值的延遲，但這次直接查詢顯示，單純每秒查一次不能讓 kubelet node CPU 每秒產生新值。Pod／container 指標可能有各自的來源時間，實驗時應分別檢查。`node_probe.py` 則獨立地每約 5 秒從裸機 `/proc/stat` 計算整機 CPU busy%，可用於較密的整機時間序列；它不提供個別 Pod CPU。
