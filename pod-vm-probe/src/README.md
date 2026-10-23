# 程式模組

這個目錄是 probe 與接收端的程式碼。部署腳本會把四個 `.py` 檔放入 `pod-probe-code` ConfigMap，掛載至 Pod 的 `/app`；執行環境為 Python 3.12，未使用額外 Python 套件。

| 檔案 | 執行位置 | 職責 |
| --- | --- | --- |
| `common.py` | 兩種 probe 共用 | 透過 Pod ServiceAccount 與叢集 API 通訊、建立含來源／時間／狀態的觀測紀錄、將批次送至 receiver；傳送失敗時保留最多 60 批記憶體佇列 |
| `cluster_probe.py` | 單一 `pod-probe-cluster` Deployment | 每 10 秒讀取 Node、Pod、Event、Service 與 Endpoints；經 API server 的 node proxy 讀 kubelet `/metrics/resource`，計算 node／Pod／container CPU cores，收集 memory working set；以 UID 關聯 Pod 和 container |
| `node_probe.py` | 兩個 worker 各一個 `pod-probe-node` DaemonSet Pod | 每 5 秒從主機唯讀掛載的 `/proc`、`/sys` 取得 OS 可用記憶體、CPU busy、網卡 counters 與 AMD GPU 指標；每約 10 秒對另一個 worker 的 TCP 22 埠做連線探測 |
| `receiver.py` | `pod-probe-receiver` Deployment | 驗證批次、以 `probe_id + boot_id + sequence` 去重、寫入 SQLite 歷史與最新值、合併固定情境設定並提供查詢；不執行資源決策 |

```text
cluster_probe.py ─┐
                  ├─ common.py → POST /v1/observations → receiver.py → SQLite
node_probe.py ────┘                                   ├─ GET /v1/summary
                                                     └─ GET /v1/state
```

`/v1/summary` 回傳各來源、對象類型、狀態與過期數量。`/v1/state` 回傳最新觀測；可用 `kind`、`metric`、`limit`、`offset` 篩選與分頁。接收端啟動時會從既有歷史紀錄建立最新值表，讓更新程式後沿用原本的 SQLite 資料。Event 僅在 Kubernetes `resourceVersion` 變化時再送出；重啟後會重新發送目前仍在 API 清單中的 Event。

主機樣本的 `collected_at` 為採集時間；kubelet 或 Kubernetes Event 提供來源時間時另填 `observed_at`。`status=unsupported` 表示主機有設備但沒有對應量測欄位，例如 `az` 的 Intel 內顯。Node 使用量與 Pod 使用量分層保存，不相加；TCP connect 時間不代表無線 uplink capacity。
