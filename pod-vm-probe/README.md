# Pod and VM Probe

此工具是 5gmap 的基礎設施觀測模組，負責提供 Pod、VM／節點的健康狀態，以及 CPU、RAM、GPU／GPU memory 使用量，作為後續 who/how/where 決策器的輸入。

目前僅建立資料夾與用途說明，尚未實作 probe。採集來源、部署位置、輸出格式與實作語言留待下一步討論。

## 預定觀測範圍

- Pod／container：狀態、readiness、重啟次數、終止原因與相關事件；CPU／RAM 使用量及 requests／limits。
- VM／節點：可達性與健康訊號、CPU／RAM 容量與使用量。
- GPU：可見裝置、GPU 利用率、GPU memory 容量與使用量；Pod 歸屬取決於實際部署是否能提供可靠映射。
- 量測資訊：觀測對象 ID、時間戳、單位、來源及有效性；無權限、無裝置或採集失敗應明示，不能記成使用量為零。

Pod 與 VM／節點是不同觀測層級，不能將兩者使用量重複相加；VM 內可見資源也不等於實體主機的全部資源。節點網卡 throughput、無線 uplink capacity、跨 edge latency 等網路指標需另外確認資料來源，不能由 CPU／RAM／GPU 使用量直接推得。

## 在 5gmap 中的位置

```text
5gmap/
  src/                    既有 HTTP/SBA tracing
  control-plane-tracing/  既有 F1AP、NGAP、PFCP tracing
  pod-vm-probe/           Pod／VM 健康狀態與資源觀測
```

本工具提供觀測結果，決策器據此產生 who/how/where。先直接取得環境可提供的資料，後續再以 adapter 對接 IEEE1935 的 VIM、平台管理或 inventory 介面。

