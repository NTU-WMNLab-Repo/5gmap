# RAN iperf3 流量與 CPU／RAM 採樣

## 目的與環境

- 實驗時間：2026-10-28 16:16–16:18 UTC（台灣時間 2026-10-29 00:16–00:18）。以下詳細時間均為 UTC。
- 目的：確認 DL／UL iperf3 流量經 UE data tunnel，並檢查 probe 快照能否在流量前、流量中與恢復期記錄 node／Pod／container 的 CPU 與 RAM 變化。
- 從輸出可確認一組 UE/DNN、一次迭代、20 秒 DL 與 20 秒 UL、啟用 probe 採樣。
- git hash: 1e8d7d3
- 拓樸：NR UE、gNB CU、gNB DU 位於 `edge` (`192.168.1.68`)；DNN 位於 `az` (`192.168.1.240`)。Pod 名稱與 UID 見 [pods.tsv](pods.tsv)。

## 原始資料

下列檔案直接從 controller 複製：

| 檔案 | 內容 |
| --- | --- |
| [samples.jsonl](samples.jsonl) | 18 次 probe 快照的精簡量測、階段標籤、來源時間、物件清單與缺值資訊；約 1.2 MB |
| [cpu-memory-summary.tsv](cpu-memory-summary.tsv) | 腳本依階段、來源時間篩選及去重後產生的 CPU／RAM 平均值與有效樣本數 |
| [throughput.DL.1.1.txt](throughput.DL.1.1.txt)、[throughput.UL.1.1.txt](throughput.UL.1.1.txt) | DL／UL iperf3 每秒與整段傳輸結果 |
| [ping.1.txt](ping.1.txt) | UE tunnel 到 DNN 的 ICMP 測試 |
| [pods.tsv](pods.tsv) | 採樣開始時的 Pod UID、名稱與節點 |

## 流量與輸入管線驗證

UE 以 `oaitun_ue1` 的 `12.1.1.2` ping DNN `10.42.2.158`，3/3 封包成功，平均 RTT 8.519 ms。DL 與 UL iperf3 的 `local` 位址也都是 `12.1.1.2`；因此這輪的 UE 端流量使用 data tunnel 的來源位址，而不是 `10.42.x.x` 的 Pod 網路位址。

當次沒有保存 `ip route get` 或封包擷取，路徑判定以介面綁定 ping 與 iperf3 來源位址為依據。表中的吞吐量是這輪達成的速率，不能直接當成可用 uplink capacity。

| 方向 | iperf3 模式 | 20 秒接收端吞吐量 | 傳送端重傳 |
| --- | --- | ---: | ---: |
| DL | UE 發起 reverse mode，DNN 傳送 | 154 Mbit/s | 239 |
| UL | UE 綁定 `12.1.1.2`，向 DNN 傳送 | 99.2 Mbit/s | 0 |

`samples.jsonl` 含 18 次成功快照：baseline 3 次、DL 4 次、DL 恢復 3 次、UL 5 次、UL 恢復 3 次。每次的 `missing` 都是空陣列，且 `observations` 非空；`missing` 僅檢查 receiver 定義的核心 node 指標，不代表所有 Pod 指標齊全。第一份快照的 Kubernetes 清單為 3 個 node、42 個 Pod、61 個 container、24 個 service。第一個查詢時間為 16:16:47.078，最後一個為 16:18:17.862。

## CPU／RAM 摘要判讀

下表摘錄原始 `cpu-memory-summary.tsv` 的 node CPU；數值為 cores，括號內是**來源時間位於該階段且去重後**的樣本數。完整 Pod、container 與 RAM 數值見 TSV。

| Node | Baseline | DL | DL 恢復 | UL | UL 恢復 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `az` | 0.366 (1) | 0.589 (1) | 0.496 (1) | 1.005 (1) | 無樣本 |
| `edge` | 3.313 (1) | 3.815 (1) | 3.995 (1) | 4.111 (2) | 3.628 (1) |
| `monitor` | 0.247 (1) | 0.156 (1) | 0.153 (1) | 0.139 (2) | 0.141 (1) |

數值呈現 `az` 與 `edge` 在部分流量階段高於 baseline 的跡象，但單一來源樣本不能估計變異，也不能據此歸因於 iperf3。`edge` node memory working set 由 baseline 6572.629 MiB、DL 6577.324 MiB，到 UL 6584.619 MiB；各階段也只有 1、1、2 個有效來源樣本。UE container 的 baseline CPU 沒有有效樣本，故不能由此 TSV 計算 UE CPU 增量。Node、Pod 與 container 屬不同觀測層級，不可相加。

採樣器每 5 秒查詢一次快照，但 `edge` 的 kubelet CPU 來源時間約每 10 秒更新；查詢與來源時間差約 3–11 秒。同一來源值可能出現在多次查詢。現有摘要只保留來源時間不早於**查詢時所標記階段**起點的資料，因此階段尾端產生、在下一階段才被查到的數值可能被排除。這也是 DL、恢復期只有 0–1 個有效值的原因之一。每個 CPU 值本身還是相鄰累計計數器的差值，時間窗可能橫跨階段邊界。本次結果足以驗證流量路徑與採樣管線，尚不足以量化流量造成的 CPU／RAM 變化。

## 下一步

1. **修正階段對齊。** 在腳本另存各階段的開始與結束時間；摘要先對 `(對象、指標、來源時間)` 全域去重，再依來源時間分配到實際階段，而不是依查詢時的階段標籤判定。保留階段邊界附近可能混合的 CPU 差值樣本標記，並在最後一段流量後延長採集，接住晚到的 kubelet 樣本。
2. **增加有效來源樣本。** 維持 `POD_PROBE=1` 與同一 UE/DNN 拓樸，將 baseline 設為至少 30 秒，DL／UL 各 60 秒，兩段恢復期各 30 秒，做至少 3 輪。每階段報告獨立來源樣本數、平均、範圍及各輪結果；若仍不足，再檢查 kubelet 更新週期或延長階段。全程保留 iperf3 的來源 IP、吞吐量與重傳數。
3. **再往資源決策輸入前進。** 取得可重複的 CPU／RAM 變化後，填入一個具體工作負載的 CPU／RAM 需求與 RAN 保留量，將現有 `node_allocatable`、requests、實測用量及模擬網路容量分開標記，先檢查 headroom 計算，再定義 who/how/where 規則。VLM 與實際資源配置不屬於此步驟。
