# Resource Decision

`resource-decision/` 是資源管理決策模組，與 `pod-vm-probe/` 平行。Probe 提供目前可用的 node／Pod／container 觀測快照；本模組將快照與情境輸入結合，輸出一份 **who／how／where 建議**。現階段不呼叫 Kubernetes API 修改部署，也不觸發執行器。

```text
pod-vm-probe /v1/snapshot ─┐
                            ├─ resource-decision → JSON 建議配置
固定 RSU／需求／網路情境 ────────┘
```

## 目錄

| 路徑 | 用途 |
| --- | --- |
| `src/decide.py` | 驗證情境、整理 node 可用額度、枚舉 contributor／品質／site，輸出建議或不可判定原因 |
| `config/scenario.example.json` | 兩個 RSU、兩種資料品質與雙 site 的**模擬**情境，數值只供管線驗證 |
| `examples/snapshot.example.json` | 符合 receiver `/v1/snapshot` 格式的**模擬** node 資料，供離線重播 |
| `tests/test_decide.py` | 本地選擇、跨 site、缺值、網路限制與 GPU 需求測試 |
| `experiments/20261106-live-snapshot/` | 實際 probe 快照的小驗證與固定快照情境敏感度腳本 |

## 執行

在 `5gmap/` 執行離線範例：

```bash
python3 resource-decision/src/decide.py \
  --snapshot-file resource-decision/examples/snapshot.example.json \
  --scenario resource-decision/config/scenario.example.json
```

Probe 已部署並可從本機連線時，可以改讀 receiver：

```bash
kubectl port-forward -n oai service/pod-probe-receiver 8080:8080
# 在另一個終端執行：
python3 resource-decision/src/decide.py \
  --snapshot-url 'http://127.0.0.1:8080/v1/snapshot' \
  --scenario resource-decision/config/scenario.example.json
```

若 lab 的 node `allocatable`、用量與範例不同，輸出也會不同。範例快照的 `mode=replay` 與 `input_provenance=simulated` 不代表量到真實叢集；live 查詢會標為 `mode=live_query`。先檢查 `status`，只有 `proposed` 才有 `who`、`how`、`where`；`input_unavailable` 表示必要 node 指標缺失或快照不完整，`no_feasible_configuration` 表示在目前簡化限制下沒有達到最低效用的組合。

```bash
python3 -m unittest discover -s resource-decision/tests -v
```

## 第一版決策規則

1. 從快照讀取每個候選 site 的 `node_ready`、`node_allocatable_cpu`、`node_allocatable_memory`、`node_cpu_usage_cores`、`node_memory_working_set_bytes`。每個 site 暫定只有一個 node；多於一個或缺少指標時停止提案。
2. 以 `allocatable − node 使用量 − 額外 RAN 保留量` 計算**運作中剩餘額度**。既有 RAN 使用量已包含在 node 使用量，不再額外扣一次；`extra_ran_reserve` 只表示額外安全餘裕。
3. 從固定候選 RSU 的品質選項中選取 `who` 與 `how`，以 CPU、RAM、模擬 uplink 容量與模擬跨 site 傳輸容量篩掉不符合條件的組合；`where` 在符合條件的 site 中選擇。效用是情境檔提供的模擬分數，這裡不估計感知品質。
4. 在符合最低效用的組合中選最高效用；同分時優先服務端 site、較少 contributor、較低 CPU 需求。輸出包含需求、剩餘額度、情境版本及 `proposal_only` 標記。

這個額度**不是 Kubernetes scheduler 的可排程剩餘量**。目前沒有完整彙總所有 Pod requests、init container 與 Pod overhead，輸出明確標記 `schedulability=unverified_requests_not_aggregated`。此外，第一版尚未處理 GPU、無線容量實測、端到端延遲或 VLM 工作負載量測；若情境要求 GPU，程式會拒絕，而不將需求當作 0。任何模擬情境都不能直接當成部署決策。

## 下一步

以實際 receiver 快照重播同一份情境，核對 `az` 與 `edge` 的 node/site 對應、時間與單位。接著明列測試工作負載的 CPU／RAM requests，完成排程額度的獨立計算，再討論是否加入延遲、GPU 與實際執行器。
