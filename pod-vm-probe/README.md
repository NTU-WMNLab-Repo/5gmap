# Pod and VM Probe

5gmap 的資源狀態收集工具。初期目標是在兩週內將 Pod／VM／GPU 與基本網路觀測送達資源管理接收 Pod，結合拓樸、工作負載需求及資源政策，提供可查詢的 input snapshot。目前為設計文件，尚未實作採集程式或接收服務。

## 架構

```text
cluster-probe  ──┐
node-probe     ──┼─ HTTP JSON → Service → resource-manager Pod → 保存／查詢
配置與情境資料 ──┘                          decision／executor 介面預留
```

| 元件 | 位置 | 責任 |
| --- | --- | --- |
| cluster-probe | 每個 cluster 一個 Deployment | K8s Pod／Node metadata、health、Events、capacity／requests／limits；kubelet 資源 metrics |
| node-probe | 每個受測 node 一個 DaemonSet Pod；必要時採 VM 本機程序 | 主機視角 CPU／RAM、可見 GPU、指定網卡 counters 與基本連線探測 |
| resource-manager | 一個 Deployment＋Service＋持久儲存 | 接收、驗證、去重、保存、合併配置、標示過期資料及提供查詢 |

接收端只回覆資料已收妥，不產生決策或執行資源調整。RSU 的 contributors／受援助對象使用固定情境資料，不處理影像。

## 第一批輸入

- **觀測：**Pod／container 狀態與事件、CPU／RAM 使用量、Node Ready／pressure、OS 可用 RAM、GPU 利用率與 GPU memory、指定網卡 RX／TX 與連線狀態。
- **資源與拓樸：**node capacity／allocatable、Pod requests／limits、Pod→node→site、功能角色與服務位置。
- **配置與假設：**測試工作負載需求、額外 RAN 保留量、門檻、資料 TTL、RSU 情境、尚未量測的 UL capacity／跨 edge 網路條件。

Pod 與 node 使用量分層保存，不能重複相加；VM 可見資源不能代表整台實體主機。GPU 無法映射至 Pod 時只報 device 層級。網卡流量及 ping 結果不能代表可達 uplink capacity。

## 傳送與資料品質

Probe 定期送至 `POST /v1/observations`；接收端保存後 ACK，以 `probe_id + boot_id + sequence` 去重。`GET /v1/state` 提供最新狀態及每項資料的新鮮度。

每項資料保留對象 ID、觀測時間、來源、單位、採樣時間窗與有效性；配置與假設分別標 `configured`、`simulated`，實測標 `measured`。無裝置、無權限、採集失敗與逾期需分別呈現，不能用零代替缺值。Node 心跳與 K8s Node Ready 為不同訊號。

## 交付範圍

提供可部署的 probes、接收 Pod、設定範例、欄位文件，以及受控 CPU／RAM 負載、Pod 重建、probe 失聯與接收端重啟的紀錄。GPU 依實際設備能力驗證。決策演算法、資源配置執行與平台整合不列入此階段。
