# Probe 實驗紀錄

每次驗證放在獨立目錄，名稱使用 `YYYYMMDD-short-name/`。每份紀錄應包含目的、部署方式、採集時間、原始證據、判讀、限制與下一步。原始輸出與分析分開保存；長篇 `/v1/state` 只截取必要的 metric 或統計值。

| 日期 | 實驗 | 結果 |
| --- | --- | --- |
| 2026-10-23 | [重新部署後的輸入管線驗證](20261023-redeploy-input-pipeline/README.md) | 三個 probe 來源持續入庫；GPU、CPU 指標可讀；舊物件及 Event 使最新值表含大量 stale 資料 |
