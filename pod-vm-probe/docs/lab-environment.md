# 實驗室環境盤點

本文件記錄環境查詢結果與部署規劃；probe 與接收服務尚未部署。

## 節點與部署位置

RKE 建立的 Kubernetes 叢集包含三個裸機 Linux 節點，均為 Ready。Kubernetes 為 `v1.24.10`，OS 為 Ubuntu `22.04.5 LTS`，container runtime 為 Docker `20.10.24`。

| Node | Role | `deplocation` label | K8s CPU capacity | K8s memory capacity | 已確認的 GPU |
| --- | --- | --- | --- | --- | --- |
| `192.168.1.192` | controlplane、etcd | `monitor` | 16 cores | 32,801,356 KiB，約 31.3 GiB | GeForce RTX 2070 SUPER；PCI 裝置可見 |
| `192.168.1.240` | worker | `az` | 20 cores | 65,607,748 KiB，約 62.6 GiB | Intel AlderLake-S GT1 內顯，`i915` |
| `192.168.1.68` | worker | `edge` | 6 cores | 61,583,680 KiB，約 58.7 GiB | AMD Cezanne 內顯，`amdgpu` |

CPU capacity 是 Kubernetes 可見的邏輯 CPU 數量，memory capacity 是 OS／Kubernetes 可見容量。`deplocation` 是現有部署標記，不表示已量測地理位置或網路延遲。

控制節點有 `controlplane:NoSchedule` 及 `etcd:NoExecute` taints。一般 probe、接收服務與測試負載優先放在 worker；控制節點 CPU／RAM 可透過 kubelet 觀測，不必為此在控制節點新增 Pod。GPU 的硬體位置與一般 workload 的可排程位置必須分開處理。

## Worker 主機盤點

以下資訊透過控制節點登入兩個 worker，以 `wmnlab` 帳號唯讀查詢；未安裝套件、變更驅動或部署工作負載。

| 項目 | `az`：`192.168.1.240` | `edge`：`192.168.1.68` |
| --- | --- | --- |
| CPU | Intel Core i7-12700；12 cores、20 個 online 邏輯 CPU | AMD Ryzen 5 5600GT；6 cores、6 個 online 邏輯 CPU |
| Kernel | `6.8.0-138-generic` | `6.8.0-138-generic` |
| Hostname | `wmnlab-desktop` | `wmnlab-desktop` |
| Node UID | `50da375c-6b16-4789-8cf4-737257fa3a2b` | `87ec9f46-79b6-4993-bf84-149bb86c9fb1` |
| Docker cgroup version | `2` | `2` |
| Docker runtimes | `runc`、`io.containerd.runc.v2`、`io.containerd.runtime.v1.linux` | 同左；未列 NVIDIA runtime |
| 實體網卡 | `enp0s31f6`；Intel I219-V，`e1000e` | `enp2s0`；Realtek RTL8111/8168/8411，`r8169` |
| 網卡狀態 | UP，MTU 1500，1000 Mbit/s、full duplex | UP，MTU 1500，1000 Mbit/s、full duplex |
| IPv4／預設閘道 | `192.168.1.240/24`／`192.168.1.1` | `192.168.1.68/24`／`192.168.1.1` |
| 根檔案系統 | `/dev/nvme0n1p2`，ext4；`df -hT` 顯示總量 457G、可用 387G | `/dev/nvme0n1p2`，ext4；總量 916G、可用 823G |
| Docker 儲存位置 | `/var/lib/docker` 與根目錄同一檔案系統 | 同左 |
| 時間同步 | `NTP=yes`、`NTPSynchronized=yes` | 同左 |
| 時區 | `America/New_York` | `America/New_York` |

兩台 hostname 相同，觀測身分必須採 cluster ID／Node UID，不能只用 `hostname`。`edge` 的 6 個邏輯 CPU 是目前 OS 可見值，不推定 SMT 設定原因。容量及磁碟可用量不等於已為實驗保留的資源。

控制節點時區為 UTC，兩個 worker 為紐約時區；三台均回報 NTP 已同步。時區不同不代表時鐘偏移，送出的時間統一為 UTC 或 Unix epoch；本次未量測實際 clock offset。

網卡 counters 可讀。worker 間各執行 3 次 ICMP 探測，`az → edge` 平均 RTT 0.416 ms，`edge → az` 平均 0.290 ms，皆收到 3 個回覆、無丟包。這僅確認盤點時的連通性，不能當作延遲分布或壅塞評估。1000 Mbit/s 是乙太網路協商速率，不能當作可用頻寬或無線 uplink capacity。

## 已有監控與可用資料

| 元件／資料來源 | 盤點結果 | 用途 |
| --- | --- | --- |
| Metrics Server | `kube-system/metrics-server` 正常運作，image 為 `rancher/mirrored-metrics-server:v0.6.2` | 基本 node／container CPU、RAM 查詢及接線比對 |
| Metrics API | `v1beta1.metrics.k8s.io` Available=True | `kubectl top nodes` 與 `kubectl top pods -A --containers` 均成功 |
| kubelet `/metrics/resource` | 三個 node 均透過 Kubernetes API proxy 成功讀取，`scrape_error=0` | node／Pod／container CPU time、memory working set |
| Prometheus | 未在所查叢集的 Deployments／DaemonSets／StatefulSets／Pods 中發現 | 目前不以 Prometheus 為前置依賴；未盤點叢集外服務 |
| OpenTelemetry Collector | `otel` namespace 有兩個 agent Pod，image 為 contrib `0.82.0` | 既有 tracing 基礎設施；本次未驗證其 metrics pipeline |
| Jaeger | `jaeger` namespace 有運作中的 Pod | 既有 trace 查詢 |
| OAI workloads | `oai` namespace 存在，盤點時沒有 Pod | 第一個收集 demo 使用測試 Pod；不要求啟動完整 RAN／core |
| Persistent storage | 未發現 StorageClass、PV 或 PVC | 接收服務不能假設已有動態儲存供應器 |

Metrics Server 目前使用 `--metric-resolution=15s`，並帶有 `--kubelet-insecure-tls`。這只描述現有元件設定，不能據此推定新 probe 的 kubelet 憑證驗證已經可用。

成功讀取的指標名稱包括：

```text
node_cpu_usage_seconds_total
node_memory_working_set_bytes
pod_cpu_usage_seconds_total
pod_memory_working_set_bytes
container_cpu_usage_seconds_total
container_memory_working_set_bytes
container_start_time_seconds
```

資源樣本包含來源時間戳。CPU time 是累積 counter，須以兩次有效樣本的差值除以來源時間差取得 cores；重複的來源時間戳、counter reset 與 container restart 需單獨處理。

已驗證的是目前 `kubectl` 身分經 API proxy 存取 kubelet 的路徑。未來 probe Pod 的專用 ServiceAccount、RBAC，以及直接 kubelet HTTPS 存取仍需在部署時驗證。直接 kubelet metrics 授權和 API proxy 的授權不同，不能把兩條路徑的權限設定混用。[Kubelet authentication/authorization](https://kubernetes.io/docs/reference/access-authn-authz/kubelet-authn-authz/)。

## GPU 現況

在控制節點 `192.168.1.192` 查得：

- PCI `0a:00.0` 為 NVIDIA TU104／GeForce RTX 2070 SUPER。
- 該顯示裝置的 `Kernel driver in use` 為 `nouveau`。
- `nvidia-smi` 指令不存在。
- 此主機 Docker runtime 清單只有 runc 類型，未列 NVIDIA runtime。
- 三個 Kubernetes nodes 的 capacity／allocatable 都沒有 `nvidia.com/gpu`，也未發現 NVIDIA device plugin 或 GPU Operator 的叢集工作負載。

兩個 worker 的 PCI 清單均未發現 NVIDIA 顯示裝置，且 `nvidia-smi` 不存在；但兩者都有內顯，不能標成「無 GPU」。

| 節點 | 裝置與驅動 | 已驗證的觀測能力 | 尚未驗證／不可用項目 |
| --- | --- | --- | --- |
| `monitor` | RTX 2070 SUPER；`nouveau` | PCI 硬體存在 | NVIDIA SMI／NVML 路徑不可用 |
| `az` | PCI `0000:00:02.0`，Intel `8086:4680`；`i915` | PCI 裝置與 DRM 節點可見 | `intel_gpu_top` 不在 PATH；利用率與記憶體採集尚未驗證 |
| `edge` | PCI `0000:03:00.0`，AMD `1002:1638`；`amdgpu` | 普通使用者可讀 GPU busy、VRAM／GTT total 與 used | probe 容器掛載／讀取權限、計算 runtime 與 Pod 對應尚未驗證 |

兩個 worker 均有 `/dev/dri/card0` 與 `/dev/dri/renderD128`，群組分別為 `video`、`render`。裝置存在與主機帳號可讀 sysfs，不保證 Pod 已具備裝置存取能力或 GPU 計算能力。本次未驗證 ROCm／OpenCL 等計算環境或 GPU 工作負載排程。

### `edge` 的 AMD 實測來源

路徑：`/sys/bus/pci/devices/0000:03:00.0/`。以下為單次讀值，不代表長期負載：

| sysfs 欄位 | 讀值 | 單位 |
| --- | --- | --- |
| `gpu_busy_percent` | 0 | % |
| `mem_info_vram_total` | 4294967296 | bytes（4 GiB） |
| `mem_info_vram_used` | 37597184 | bytes |
| `mem_info_gtt_total` | 31530844160 | bytes |
| `mem_info_gtt_used` | 29630464 | bytes |

`gpu_busy_percent` 是驅動提供的 GPU 忙碌百分比，不能作為 Pod 個別使用率；記憶體欄位單位為 bytes。VRAM 與 GTT 應保留各自的 memory domain；內顯的讀值不能描述成獨立顯示卡容量，也不能直接與 OS RAM 相加。[AMDGPU busy 指標](https://docs.kernel.org/6.12/gpu/amdgpu/thermal.html)、[AMDGPU memory 指標](https://docs.kernel.org/gpu/amdgpu/driver-misc.html)。

第一版可優先用 `edge` 的 AMD sysfs 作為真實 GPU 輸入，將所需主機 sysfs 路徑唯讀掛載後驗證容器採集。每筆附來源與採集時間；無來源時間戳時不捏造 `observed_at`。`az` 與控制節點未取得的 utilization／memory 保持 unknown 並附原因，不能填 0%；上表的 0% 則是成功讀取的實測值。若裝置沒有可用 UUID，保留獨立的 `pci_bdf`，以 Node UID 加 PCI 位址在本次 inventory 中定位，不偽造 UUID；硬體拓樸變更後重新盤點。

## Plan

首次部署 probe 所用的 `python:3.12-slim` 映像在三台主機的 Docker 快取中都不存在；兩個 worker 的 Docker Hub registry 入口連線成功並回傳正常的未授權挑戰（HTTP 401），實際 image pull 尚未驗證。若拉取失敗，需指定實驗室已準備的相容 Python 映像。

1. **主要受測節點：**`edge` 與 `az` 兩個 worker，metadata 與 node resource inventory 可涵蓋全部三個 node。
2. 第一批資料：Pod metadata／health／requests／limits、node capacity／allocatable，以及已驗證的 kubelet CPU／RAM 指標。
3. 接收服務：放在 `az` worker，使用 SQLite；預先配置帶 node affinity 的靜態 local PV／PVC，或明確綁定節點的持久目錄。現有叢集不具動態 PVC 供應條件。
4. 測試負載：在 worker 上建立小型 CPU／RAM 測試 Pod，再觀察資源與 restart／health 變化；既有服務只作讀取與對照。
5. GPU：優先接入 `edge` 的 AMD sysfs；先驗證 probe Pod 能讀取，再送出 device 層級資料。Intel 與 NVIDIA 尚未取得的指標明示缺值，不作為整條 input pipeline 的阻塞條件。
6. 其餘設定：site 對照、工作負載需求、RAN 保留量、RSU 情境與假設網路條件由設定檔提供；node-probe 另補 OS available memory 與網卡 counters。

映像與 Kubernetes API／client 版本需與現有 `v1.24.10` 配合；實作時固定相容版本，不直接使用未驗證的最新 addon。

## 可重現的唯讀查詢

以下命令在具有叢集查詢權限的實驗室主機執行：

```bash
kubectl get nodes -o wide
kubectl get nodes --show-labels
kubectl get deployments,daemonsets,statefulsets -A -o wide
kubectl get apiservices
kubectl get pods -A -o wide
kubectl top nodes
kubectl top pods -A --containers
kubectl get storageclasses,persistentvolumes -A
kubectl get persistentvolumeclaims -A
kubectl get --request-timeout=15s --raw /api/v1/nodes/192.168.1.192/proxy/metrics/resource
kubectl get --request-timeout=15s --raw /api/v1/nodes/192.168.1.240/proxy/metrics/resource
kubectl get --request-timeout=15s --raw /api/v1/nodes/192.168.1.68/proxy/metrics/resource
lspci -nnk -d 10de:
nvidia-smi --query-gpu=name,uuid,driver_version,memory.total,memory.used,memory.free,utilization.gpu --format=csv
docker info --format '{{.Runtimes}}'
timedatectl show -p NTPSynchronized -p NTP -p TimeUSec
```

最後四項是執行命令所在主機的資訊，不代表全部 nodes。`nvidia-smi` 在目前三台主機均不可用。

登入各 worker 後可重現主機盤點：

```bash
hostname
uname -r
lscpu -J
lspci -nnk
free -b
docker info --format '{{.Runtimes}}'
docker info --format '{{.CgroupVersion}}'
timedatectl show -p NTPSynchronized -p NTP -p Timezone -p TimeUSec
ip -br address
ip route show default
df -hT / /var/lib/docker
ls -l /dev/dri
```

在 `az` 上執行：

```bash
command -v intel_gpu_top
cat /sys/class/net/enp0s31f6/speed /sys/class/net/enp0s31f6/duplex
ip -s link show enp0s31f6
ping -c 3 -W 2 192.168.1.68
```

在 `edge` 上執行：

```bash
cat /sys/class/net/enp2s0/speed /sys/class/net/enp2s0/duplex
ip -s link show enp2s0
ping -c 3 -W 2 192.168.1.240
head -v /sys/bus/pci/devices/0000:03:00.0/gpu_busy_percent /sys/bus/pci/devices/0000:03:00.0/mem_info_vram_total /sys/bus/pci/devices/0000:03:00.0/mem_info_vram_used /sys/bus/pci/devices/0000:03:00.0/mem_info_gtt_total /sys/bus/pci/devices/0000:03:00.0/mem_info_gtt_used
```

Pod、資源用量、磁碟空間及網路數值為盤點當下狀態，部署前需重新確認。仍待驗證 probe ServiceAccount／kubelet 存取、容器內主機視角與 sysfs 權限，以及接收端持久儲存配置。
