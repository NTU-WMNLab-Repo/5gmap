# 實際快照決策小驗證

- 時間：2026-11-06 03:08（台灣時間；快照 UTC 時間為 2026-11-05 19:08:11）。
- 輸入：lab receiver `/v1/snapshot` 的實際 node 觀測，加上 `config/scenario.example.json` 的模擬 RSU、工作負載與網路條件。
- 方法：將 API 回應存入 `/tmp/resource-decision-snapshot.json`，用 `src/decide.py --snapshot-file` 執行。`mode=replay` 表示從檔案讀取，不代表 node 資料是模擬值。

| 項目 | 結果 |
| --- | --- |
| `status` | `proposed`；`execution=proposal_only` |
| edge 運作中 CPU／RAM 餘量 | 2.1613 cores／54,894,166,016 bytes |
| az 運作中 CPU／RAM 餘量 | 19.1639 cores／58,042,433,536 bytes |
| who／how | `rsu-north:low`、`rsu-east:high` |
| where | `az` |
| 需求 | 2.5 cores、640 MiB RAM、edge uplink 80 Mbps、跨站 80 Mbps |
| 模擬效用 | 0.75 |

edge 的估算 CPU 餘量低於 2.5 cores，決策改選 az。這確認了實際 node 觀測可進入 who／how／where 決策；RSU 選項、效用、uplink 與跨站容量仍是模擬設定。既有 Pod requests 尚未完整彙總，`schedulability=unverified_requests_not_aggregated`；這筆提案不代表 Kubernetes 已驗證可排程。

固定同一份快照，執行情境敏感度檢查：

```bash
python3 resource-decision/experiments/20261106-live-snapshot/run.py \
  --snapshot-file /tmp/resource-decision-snapshot.json
```

腳本依序測試原始設定、降低基本 CPU 需求、限制跨站容量、限制 uplink 容量及無可行 uplink 容量。每個案例只改一個模擬參數；快照內容保持不變。使用上述同一份 `/tmp` 快照的結果如下：

| 案例 | who／how | where | 效用 | CPU 需求 |
| --- | --- | --- | ---: | ---: |
| 原始設定 | north:low、east:high | az | 0.75 | 2.5 cores |
| 基本需求降至 0.1 cores | north:low、east:high | edge | 0.75 | 2.1 cores |
| 跨站容量降至 40 Mbps | east:high | edge | 0.5 | 2.0 cores |
| edge uplink 降至 60 Mbps | east:high | edge | 0.5 | 2.0 cores |
| edge uplink 降至 10 Mbps | 無可行配置 | — | — | — |

上表的容量變化是模擬情境，不是 lab 網路重新量測。完整快照只在 lab 的 `/tmp`；回歸測試使用接近這次 CPU 餘量的模擬快照。此表由當時只檢查整機用量的第一版決策規則產生。後續版本新增 Pod requests 檢查，舊快照缺少 `pod_resource_inputs`，不能直接重播；腳本需搭配新版 probe 產生的新快照。
