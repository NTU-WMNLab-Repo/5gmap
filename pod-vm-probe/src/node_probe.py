import os
import socket
import time

from common import kube_json, observation, run_loop


NODE_NAME = os.environ["NODE_NAME"]
NODE_UID = None
SITE_ID = None
PREVIOUS = {}
LAST_CONNECT = 0.0


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read().strip()


def counter(name, current, unit, source, subject, attrs=None):
    now = time.monotonic()
    old = PREVIOUS.get(name)
    PREVIOUS[name] = (current, now)
    if old and now > old[1] and current >= old[0]:
        return observation("node", subject, name + "_rate", (current - old[0]) / (now - old[1]),
                           unit + "/s", source, node_uid=NODE_UID, site_id=SITE_ID, attributes=attrs)
    return None


def collect():
    global NODE_UID, SITE_ID, LAST_CONNECT
    if NODE_UID is None:
        from urllib.parse import quote
        node = kube_json("/api/v1/nodes/" + quote(NODE_NAME, safe=""))
        NODE_UID = node["metadata"]["uid"]
        SITE_ID = node["metadata"].get("labels", {}).get("deplocation")
    records = []
    attrs = {"node_name": NODE_NAME}
    meminfo = {}
    for line in read("/host/proc/meminfo").splitlines():
        key, value = line.split(":", 1)
        meminfo[key] = int(value.strip().split()[0]) * 1024
    for key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
        records.append(observation("node", NODE_UID, "os_" + key.lower() + "_bytes", meminfo[key],
                                   "bytes", "host/proc/meminfo", node_uid=NODE_UID, site_id=SITE_ID, attributes=attrs))
    cpu = read("/host/proc/stat").splitlines()[0].split()
    values = [int(item) for item in cpu[1:9]]
    idle = values[3] + values[4]
    total = sum(values)
    old = PREVIOUS.get("cpu_jiffies")
    PREVIOUS["cpu_jiffies"] = (idle, total)
    if old and total > old[1]:
        busy = 100 * (1 - (idle - old[0]) / (total - old[1]))
        records.append(observation("node", NODE_UID, "os_cpu_busy_percent", busy, "%", "host/proc/stat",
                                   node_uid=NODE_UID, site_id=SITE_ID, attributes=attrs))
    for nic in os.environ.get("HOST_NICS", "enp0s31f6,enp2s0").split(","):
        nic = nic.strip()
        base = f"/host/sys/class/net/{nic}/statistics"
        if not nic or not os.path.isdir(base):
            continue
        for name in ("rx_bytes", "tx_bytes", "rx_dropped", "tx_dropped", "rx_errors", "tx_errors"):
            value = int(read(f"{base}/{name}"))
            metric = f"net_{nic}_{name}"
            records.append(observation("node", NODE_UID, metric, value, "bytes" if name.endswith("bytes") else "count",
                                       "host/sys/class/net", node_uid=NODE_UID, site_id=SITE_ID, attributes=attrs))
            rate = counter(metric, value, "bytes" if name.endswith("bytes") else "count",
                           "host/sys/class/net", NODE_UID, attrs)
            if rate:
                records.append(rate)
    for device in os.listdir("/host/sys/bus/pci/devices"):
        base = f"/host/sys/bus/pci/devices/{device}"
        try:
            pci_class = read(f"{base}/class")
        except OSError:
            continue
        if not pci_class.startswith("0x03"):
            continue
        vendor = read(f"{base}/vendor")
        gpu_subject = f"{NODE_UID}/{device}"
        gpu_attrs = {"node_name": NODE_NAME, "pci_bdf": device, "vendor_id": vendor,
                     "memory_domain": None}
        records.append(observation("gpu", gpu_subject, "gpu_hardware_present", True, "boolean",
                                   "host/sys/pci", node_uid=NODE_UID, site_id=SITE_ID, attributes=gpu_attrs))
        busy = f"{base}/gpu_busy_percent"
        if not os.path.exists(busy):
            records.append(observation("gpu", gpu_subject, "gpu_busy_percent", None, "%",
                                       "host/sys/pci", status="unsupported", reason="driver metric unavailable",
                                       node_uid=NODE_UID, site_id=SITE_ID, attributes=gpu_attrs))
            continue
        for field, unit in (("gpu_busy_percent", "%"), ("mem_info_vram_total", "bytes"),
                            ("mem_info_vram_used", "bytes"), ("mem_info_gtt_total", "bytes"),
                            ("mem_info_gtt_used", "bytes")):
            try:
                value = int(read(f"{base}/{field}"))
                records.append(observation("gpu", gpu_subject, field, value, unit,
                                           "host/sys/amdgpu", node_uid=NODE_UID, site_id=SITE_ID,
                                           attributes={**gpu_attrs, "memory_domain": "vram" if "vram" in field else "gtt" if "gtt" in field else None}))
            except (OSError, ValueError) as exc:
                records.append(observation("gpu", gpu_subject, field, None, unit,
                                           "host/sys/amdgpu", status="error", reason=str(exc)[:160],
                                           node_uid=NODE_UID, site_id=SITE_ID, attributes=gpu_attrs))
    if time.monotonic() - LAST_CONNECT >= 10:
        LAST_CONNECT = time.monotonic()
        for target in os.environ.get("PEER_TARGETS", "192.168.1.240:22,192.168.1.68:22").split(","):
            host, port_text = target.rsplit(":", 1)
            if host == NODE_NAME:
                continue
            start = time.monotonic()
            attrs = {"destination": host, "port": int(port_text), "method": "tcp_connect"}
            link_id = f"{NODE_UID}->{host}:{port_text}"
            try:
                with socket.create_connection((host, int(port_text)), timeout=0.5):
                    pass
                records.append(observation("link", link_id, "peer_tcp_connect_ms",
                                           (time.monotonic() - start) * 1000, "ms", "tcp_connect",
                                           node_uid=NODE_UID, site_id=SITE_ID, attributes=attrs, ttl_seconds=40))
            except OSError as exc:
                records.append(observation("link", link_id, "peer_tcp_connect_ms", None, "ms",
                                           "tcp_connect", status="error", reason=str(exc)[:160],
                                           node_uid=NODE_UID, site_id=SITE_ID, attributes=attrs, ttl_seconds=40))
    return records


if __name__ == "__main__":
    run_loop(collect, "node-probe:" + NODE_NAME, 5)
