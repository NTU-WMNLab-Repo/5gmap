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
| `src/decide.py` | 驗證情境、分別計算排程與運行餘量、枚舉 contributor／品質／site，輸出建議或不可判定原因 |
| `config/scenario.example.json` | 兩個 RSU、兩種資料品質與雙 site 的**模擬**情境，數值只供管線驗證 |
| `examples/snapshot.example.json` | 符合 receiver `/v1/snapshot` 格式的**模擬** node 資料，供離線重播 |
| `tests/test_decide.py` | 選擇、跨 site、Pod requests、缺值、網路限制與 GPU 需求測試 |
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

在 lab controller 的 `~/5gmap` 可直接經 Kubernetes API proxy 取得完整快照；更新 probe 後先等下一輪採集，再執行：

```bash
kubectl get --raw /api/v1/namespaces/oai/services/http:pod-probe-receiver:8080/proxy/v1/snapshot \
  > /tmp/resource-decision-snapshot.json
python3 resource-decision/src/decide.py \
  --snapshot-file /tmp/resource-decision-snapshot.json \
  --scenario resource-decision/config/scenario.example.json
```

若 lab 的 node `allocatable`、用量與範例不同，輸出也會不同。範例快照的 `mode=replay` 與 `input_provenance=simulated` 不代表量到真實叢集；live 查詢會標為 `mode=live_query`。先檢查 `status`，只有 `proposed` 才有 `who`、`how`、`where`；`input_unavailable` 表示必要 node 指標缺失或快照不完整，`no_feasible_configuration` 表示在目前簡化限制下沒有達到最低效用的組合。

```bash
python3 -m unittest discover -s resource-decision/tests -v
```

## 第一版決策規則

1. 從快照讀取每個候選 site 的 `node_ready`、`node_unschedulable`、CPU capacity／allocatable／整機用量、memory allocatable／裸機 `MemAvailable`，以及所有仍在清單內的 `pod_resource_inputs`。每個 site 暫定只有一個 node；多於一個、缺少必要指標或 Pod request 清單不完整時停止提案。
2. **排程餘量**為 `allocatable − 已指派且未結束 Pod 的有效 requests − 額外 RAN 保留量`。有效 request 對每項資源分別取「一般 containers requests 的總和」與「最大 init container request」的較大值，再加 Pod overhead。缺少 request 的欄位按 Kubernetes API 中的零值處理。只統計仍在清單中的 Pod，並用 Pod 數量檢查採集完整性。
3. **運行餘量**的 CPU 為 `node capacity − 整機 CPU 用量 − 額外 RAN 保留量`；RAM 為 `host MemAvailable − 額外 RAN 保留量`。兩道檢查分開輸出；`budgets.cpu_cores`／`memory_bytes` 顯示兩者較小值。此處的 `extra_ran_reserve` 只表示尚未出現在 requests 或用量中的未來需求，避免重複扣掉現有 RAN。
4. 從固定候選 RSU 的品質選項中選取 `who` 與 `how`，CPU／RAM 需求必須同時通過排程與運行餘量，且符合模擬 uplink 與跨 site 傳輸容量；`where` 在符合條件的 site 中選擇。情境檔的 CPU／RAM 數字暫時同時代表新 Pod 預計宣告的 request 和預期用量；效用仍是模擬分數。
5. 在符合最低效用的組合中選最高效用；同分時優先服務端 site、較少 contributor、較低 CPU 需求。輸出包含兩道餘量、需求、情境版本及 `proposal_only` 標記。

Pod requests 及 node allocatable 的關係依 [Kubernetes 資源管理](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)；init container 的有效 request 與 [Pod overhead](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-overhead/) 另行計入。`schedulability=cpu_memory_requests_checked_other_constraints_unverified` 表示已檢查 CPU／RAM requests，**並非完整模擬 Kubernetes scheduler**：尚未檢查 affinity、taints／tolerations、儲存、Pod 數上限、網路與其他擴充資源。整機 CPU 是時間窗內的用量，`MemAvailable` 是 OS 的可用記憶體估計，均非未來負載保證。第一版也尚未處理 GPU、無線容量實測、端到端延遲或 VLM 工作負載量測；若情境要求 GPU，程式會拒絕，而不將需求當作 0。

## 下一步

更新 probe 後，以新鮮 receiver 快照核對各 node 的有效 requests、排程餘量和運行餘量，並與 `kubectl describe node` 的 requests 摘要比較。舊快照缺少 `pod_resource_inputs`，會回傳 `input_unavailable`，不能套用新規則回推舊實驗。再量測具體工作負載的 CPU／RAM 需求並設定對應 Pod requests。
