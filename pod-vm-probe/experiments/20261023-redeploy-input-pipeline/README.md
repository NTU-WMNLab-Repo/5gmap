# 重新部署後的輸入管線驗證

## 目的與環境

- 日期：2026-10-23；以下時間皆為 UTC，台灣時間加 8 小時。
- 目的：確認更新後的 probe 部署、資料傳送、最新值查詢、Event 去重與 GPU／CPU 採集。
- 部署指令：

  ```bash
  RanProxy=1 CrossProtocolCorrelate=1 RUN_MODE=rfsim DeployUE=1 pod_probe=1 DELETE_MYSQL=1 ./script/run.sh
  ```

- Kubernetes：RKE v1.24.10；`oai` namespace。Receiver 與 cluster probe 在 `az` (`192.168.1.240`)，node probe 分別在 `az` 與 `edge` (`192.168.1.68`)。固定情境資料版本為 `lab-initial-1`。
- 這次重新部署沿用 `az` 主機 `/var/lib/pod-vm-probe` 的 SQLite；資料庫包含本次部署前的紀錄。
- git hash: 169bbe2

## 原始資料

- [user-capture.raw.txt](user-capture.raw.txt)：11:24:37–11:24:55 UTC 的 `/v1/summary`、GPU state 與 node CPU state。
- [live-check.raw.txt](live-check.raw.txt)：11:28–11:29 UTC 從實驗室唯讀擷取的 Pod 狀態、summary、SQLite 聚合統計、資料庫大小及 probe 資源使用量。查詢均限制在統計值或 probe Pod，未匯出整份 state。

當時可重現的精簡查詢：

```bash
kubectl get deployment,daemonset,service -n oai | grep pod-probe
kubectl get --raw /api/v1/namespaces/oai/services/http:pod-probe-receiver:8080/proxy/v1/summary
kubectl top pods -n oai --containers | grep pod-probe
```

## 結果

1. Receiver、cluster probe、兩個 node probe 均為 `Running`、`1/1 Ready`、`0` restart。Cluster Deployment 為 1/1，node DaemonSet 為 2/2。Receiver 重新啟動期間，cluster probe 曾有四次 `Connection refused`；之後 `pending=0, dropped=0`。Node probe 亦恢復傳送。SQLite 的 batch 表記錄三個來源持續入庫。
2. 11:24 summary 顯示 1,363 個最新值：`ok=1,362`、`unsupported=1`，來源為 cluster 1,319、az node 20、edge node 24。唯一 unsupported 是 az Intel iGPU 的 `gpu_busy_percent`，理由為 `driver metric unavailable`，不是採集失敗。
3. GPU state 有 8 個最新值：edge AMD iGPU 提供 busy、VRAM total/used、GTT total/used 及設備存在；az Intel iGPU 提供設備存在，busy 標為 unsupported。這只證明 AMD sysfs 在目前 Pod 中可讀，尚未在負載下驗證 GPU busy 變化，也不表示 Kubernetes 可把 GPU 分配給工作負載。
4. Node CPU 查詢回傳 monitor、az、edge 三個 node 的 `node_cpu_usage_cores`，分別約為 0.154、0.315、3.273 cores（11:24:39–11:24:49 的來源樣本）。三筆在查詢時皆為 `stale=false`。這些是當下用量樣本，不能單獨當作可排程餘量。
5. 11:28 的 summary 仍為 1,363 個最新值，但 stale 從 717 增至 805。用 `collected_at` 計算超過 45 秒的紀錄分布為 container 224、pod 110、service 30、Event 441；其餘 node、GPU、link 都在 45 秒內。Event 的 TTL 是 300 秒，且 stale 判斷優先用來源 `observed_at`，所以 Event 在 `/v1/summary` 中過期屬預期現象。舊 Pod／container／service 仍留在 `latest` 表，則會污染決策器的候選狀態，需處理物件刪除與查詢篩選。
6. Event 歷史表有 40,622 筆，包含先前部署的重複寫入；最近 15 分鐘只有 222 筆，最近 5 分鐘為 0 筆。重啟時重新發送現有 Event 後，沒有再每 10 秒寫入同一批 Event，符合以 `resourceVersion` 去重的預期。現有 441 個 Event 最新值多數仍是歷史事件，不代表此刻發生 441 件異常。
7. Receiver 資料庫檔案約 175 MiB，涵蓋 09:45 UTC 起的多次部署，不能視為此次 7 分鐘實驗的新增容量。11:29 左右四個 probe 容器資源約為 cluster 4m/18Mi、az node 1m/14Mi、edge node 1m/14Mi、receiver 9m/19Mi。這是一次 `kubectl top` 快照，並非長時間額外負擔估計。

## 判定與限制

輸入管線、接收端去重與短時查詢已可運作；資料的 `status=ok` 不代表仍可供決策使用。現在的 `/v1/state` 會同時包含已刪除工作負載、歷史 Event 和即時資源；下游必須檢查 `stale`，且目前還沒有明確的「目前存在物件」邊界。Fixture 中 `workload_requests` 為空，RSU contributors／assisted target 為空，網路容量與延遲皆為 `null`；此實驗尚不能產生具體的 who/how/where 資源決策。

## 下一步實驗順序

1. **建立可用的決策輸入快照。** 定義每個 kind 的存活規則。Pod／container／service 以目前 Kubernetes 清單為準，Event 與歷史紀錄留在歷史查詢；給決策器的 snapshot 只交付未過期且屬目前物件的紀錄，另回報缺值、unsupported 與來源時間。驗證刪除 Pod 後不再出現在可用快照，Event 數量不影響資源候選集合。
2. **做受控負載驗證。** 在 az 與 edge 各跑短時 CPU／RAM 負載，記錄負載前、期間、恢復後的 node、Pod、container 用量與 timestamp，對照 `kubectl top`；再測試 Pod 重建、receiver 重啟後來源恢復與 TTL。不要用 RAN 工作負載的現有波動替代受控測試。
3. **補齊可計算的情境輸入。** 為單一 RSU 案例填入工作需求、RAN 保留量、模擬的 uplink／跨 edge 容量與延遲，以及預先指定的 contributors／受援目標；每項標記 `configured` 或 `simulated`，不得把 TCP connect 時間當成網路容量。確認數值單位、來源與缺值行為後，再接 who/how/where 決策邏輯。

先完成第 1 項，使下游讀到的資源集合可信，再做負載及情境比較。VLM 與實際執行器不在這一輪驗證範圍。
