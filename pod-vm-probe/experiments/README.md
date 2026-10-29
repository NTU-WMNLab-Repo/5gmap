# Probe 實驗紀錄

每次驗證放在獨立目錄，名稱使用 `YYYYMMDD-short-name/`。每份紀錄應包含目的、部署方式、採集時間、原始證據、判讀、限制與下一步。原始輸出與分析分開保存；長篇 `/v1/state` 只截取必要的 metric 或統計值。

| 日期 | 實驗 | 結果 |
| --- | --- | --- |
| 2026-10-23 | [重新部署後的輸入管線驗證](20261023-redeploy-input-pipeline/README.md) | 三個 probe 來源持續入庫；GPU、CPU 指標可讀；舊物件及 Event 使最新值表含大量 stale 資料 |
| 2026-10-28 UTC／29 台灣時間 | [RAN iperf3 流量與 CPU／RAM 採樣](20261028-iperf-cpu-memory/README.md) | DL 154 Mbit/s、UL 99.2 Mbit/s；18 次快照完整，CPU 摘要受來源樣本數與時間落後限制 |
| 2026-10-29 | [三輪 RAN iperf3 CPU／RAM 採樣](20261029-repeated-iperf-cpu-memory/README.md) | 修正來源時間歸屬後完成三輪 60 秒 DL／UL；129 次快照，整機與 Pod CPU 階段變化可重複觀察 |
