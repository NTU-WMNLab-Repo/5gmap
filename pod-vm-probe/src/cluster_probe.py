import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

from common import kube_json, kube_request, observation, run_loop


CLUSTER_ID = os.environ.get("CLUSTER_ID", "lab-rke")
PREVIOUS_CPU = {}
EVENT_RESOURCE_VERSIONS = {}
METRIC_LINE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?\s+([^\s]+)(?:\s+([^\s]+))?$')
LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"\\])*)"')


def labels(raw):
    return {key: value.replace('\\"', '"').replace('\\\\', '\\') for key, value in LABEL.findall(raw or "")}


def parse_metrics(raw, node_uid, site_id, pod_uids):
    records = []
    cpu_names = {"node_cpu_usage_seconds_total", "pod_cpu_usage_seconds_total",
                 "container_cpu_usage_seconds_total"}
    memory_names = {"node_memory_working_set_bytes", "pod_memory_working_set_bytes",
                    "container_memory_working_set_bytes"}
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        match = METRIC_LINE.match(line)
        if not match:
            continue
        metric, raw_labels, value, stamp = match.groups()
        if metric not in cpu_names | memory_names:
            continue
        attrs = labels(raw_labels)
        if metric.startswith("container_"):
            namespace, pod, container = (attrs.get("namespace"), attrs.get("pod"), attrs.get("container"))
            if not all((namespace, pod, container)):
                continue
            pod_uid = pod_uids.get((namespace, pod))
            if not pod_uid:
                continue
            kind, subject = "container", f"{pod_uid}/{container}"
        elif metric.startswith("pod_"):
            namespace, pod = attrs.get("namespace"), attrs.get("pod")
            if not all((namespace, pod)):
                continue
            pod_uid = pod_uids.get((namespace, pod))
            if not pod_uid:
                continue
            kind, subject = "pod", pod_uid
        else:
            kind, subject = "node", node_uid
        try:
            numeric = float(value)
        except ValueError:
            continue
        observed_at = None
        if stamp:
            try:
                observed_at = datetime.fromtimestamp(int(stamp) / 1000, timezone.utc).isoformat()
            except (ValueError, OverflowError):
                pass
        if metric in memory_names:
            records.append(observation(kind, subject, metric, numeric, "bytes", "kubelet/metrics/resource",
                                       node_uid=node_uid, site_id=site_id, observed_at=observed_at, attributes=attrs))
            continue
        key = (metric, subject)
        now = int(stamp) / 1000 if stamp and stamp.isdigit() else time.monotonic()
        previous = PREVIOUS_CPU.get(key)
        if previous and now <= previous[1]:
            continue
        PREVIOUS_CPU[key] = (numeric, now)
        if previous and now > previous[1] and numeric >= previous[0]:
            cores = (numeric - previous[0]) / (now - previous[1])
            records.append(observation(kind, subject, metric.replace("seconds_total", "cores"),
                                       cores, "cores", "kubelet/metrics/resource",
                                       node_uid=node_uid, site_id=site_id, observed_at=observed_at, attributes=attrs))
    return records


def changed_events(events):
    records = []
    current = {}
    for event in events[-200:]:
        meta = event["metadata"]
        uid = meta["uid"]
        version = meta.get("resourceVersion")
        current[uid] = version
        if uid in EVENT_RESOURCE_VERSIONS and EVENT_RESOURCE_VERSIONS[uid] == version:
            continue
        involved = event.get("involvedObject", {})
        observed_at = (event.get("eventTime") or event.get("lastTimestamp")
                       or meta.get("creationTimestamp"))
        records.append(observation("event", uid, "event_reason", event.get("reason", "Unknown"),
                                   "state", "k8s/event", ttl_seconds=300, observed_at=observed_at,
                                   attributes={"message": event.get("message", "")[:500],
                                               "type": event.get("type"), "count": event.get("count"),
                                               "object_kind": involved.get("kind"),
                                               "object_uid": involved.get("uid")}))
    EVENT_RESOURCE_VERSIONS.clear()
    EVENT_RESOURCE_VERSIONS.update(current)
    return records


def collect():
    records = []
    nodes = kube_json("/api/v1/nodes")["items"]
    pods = kube_json("/api/v1/pods")["items"]
    events = kube_json("/api/v1/events")["items"]
    services = kube_json("/api/v1/services")["items"]
    endpoints = kube_json("/api/v1/endpoints")["items"]
    pod_uids = {(pod["metadata"]["namespace"], pod["metadata"]["name"]): pod["metadata"]["uid"] for pod in pods}
    service_uids = {(service["metadata"]["namespace"], service["metadata"]["name"]): service["metadata"]["uid"] for service in services}
    node_by_name = {}
    pod_nodes = {pod["metadata"]["uid"]: pod.get("spec", {}).get("nodeName") for pod in pods}
    for node in nodes:
        meta, spec, status = node["metadata"], node.get("spec", {}), node.get("status", {})
        uid, name = meta["uid"], meta["name"]
        site = meta.get("labels", {}).get("deplocation")
        node_by_name[name] = (uid, site)
        ready = next((c["status"] for c in status.get("conditions", []) if c["type"] == "Ready"), "Unknown")
        for metric, value, unit in (
            ("node_ready", ready, "state"),
            ("node_unschedulable", bool(spec.get("unschedulable", False)), "boolean"),
            ("node_capacity_cpu", status.get("capacity", {}).get("cpu"), "cores"),
            ("node_capacity_memory", status.get("capacity", {}).get("memory"), "k8s_quantity"),
            ("node_allocatable_cpu", status.get("allocatable", {}).get("cpu"), "cores"),
            ("node_allocatable_memory", status.get("allocatable", {}).get("memory"), "k8s_quantity"),
        ):
            if value is not None:
                records.append(observation("node", uid, metric, value, unit, "k8s/node",
                                           node_uid=uid, site_id=site, attributes={"node_name": name}))
        for condition in status.get("conditions", []):
            if condition["type"].endswith("Pressure"):
                records.append(observation("node", uid, "node_" + condition["type"].lower(),
                                           condition["status"], "state", "k8s/node",
                                           node_uid=uid, site_id=site))
        for resource in ("nvidia.com/gpu", "amd.com/gpu", "gpu.intel.com/i915"):
            for category in ("capacity", "allocatable"):
                value = status.get(category, {}).get(resource)
                if value is not None:
                    records.append(observation("node", uid, f"node_{category}_{resource}", value,
                                               "k8s_quantity", "k8s/node", node_uid=uid, site_id=site))
        try:
            path = "/api/v1/nodes/" + quote(name, safe="") + "/proxy/metrics/resource"
            records.extend(parse_metrics(kube_request(path), uid, site, pod_uids))
        except Exception as exc:
            records.append(observation("node", uid, "resource_metrics_access", None, "state", "kubelet/metrics/resource",
                                       status="error", reason=str(exc)[:160], node_uid=uid, site_id=site))
    for pod in pods:
        meta, spec, status = pod["metadata"], pod.get("spec", {}), pod.get("status", {})
        node_uid, site = node_by_name.get(spec.get("nodeName"), (None, None))
        subject = meta["uid"]
        attrs = {"namespace": meta["namespace"], "pod_name": meta["name"],
                 "node_name": spec.get("nodeName"), "owner": meta.get("ownerReferences", []),
                 "labels": meta.get("labels", {})}
        ready = next((c["status"] for c in status.get("conditions", []) if c["type"] == "Ready"), "Unknown")
        for metric, value in (("pod_phase", status.get("phase", "Unknown")), ("pod_ready", ready)):
            records.append(observation("pod", subject, metric, value, "state", "k8s/pod",
                                       node_uid=node_uid, site_id=site, attributes=attrs))
        for container in status.get("containerStatuses", []):
            container_id = f"{subject}/{container['name']}"
            records.append(observation("container", container_id, "restart_count", container.get("restartCount", 0),
                                       "count", "k8s/pod", node_uid=node_uid, site_id=site))
            records.append(observation("container", container_id, "container_ready", bool(container.get("ready", False)),
                                       "boolean", "k8s/pod", node_uid=node_uid, site_id=site))
            state = container.get("state", {})
            for phase in ("waiting", "terminated"):
                if phase in state:
                    records.append(observation("container", container_id, "container_state", phase,
                                               "state", "k8s/pod", node_uid=node_uid, site_id=site,
                                               attributes={"reason": state[phase].get("reason")}))
        for container in spec.get("containers", []):
            container_id = f"{subject}/{container['name']}"
            for category in ("requests", "limits"):
                for resource, quantity in container.get("resources", {}).get(category, {}).items():
                    records.append(observation("container", container_id, f"{category}_{resource}", quantity,
                                               "k8s_quantity", "k8s/pod", node_uid=node_uid, site_id=site))
    sites_by_service = {}
    for endpoint in endpoints:
        meta = endpoint["metadata"]
        addresses = []
        for subset in endpoint.get("subsets", []):
            for address in subset.get("addresses", []):
                target = address.get("targetRef", {})
                node_name = address.get("nodeName") or pod_nodes.get(target.get("uid"))
                site = node_by_name.get(node_name, (None, None))[1]
                addresses.append({"ip": address.get("ip"), "pod_uid": target.get("uid"),
                                  "node_name": node_name, "site_id": site})
        service_uid = service_uids.get((meta["namespace"], meta["name"]))
        if not service_uid:
            continue
        sites_by_service.setdefault(service_uid, set()).update(
            address["site_id"] for address in addresses if address["site_id"])
        records.append(observation("service", service_uid,
                                   "ready_endpoints", len(addresses), "count", "k8s/endpoints",
                                   attributes={"addresses": addresses[:100]}))
    for service in services:
        meta = service["metadata"]
        spec = service.get("spec", {})
        records.append(observation("service", meta["uid"], "service_location",
                                   sorted(sites_by_service.get(meta["uid"], set())), "sites", "k8s/endpoints",
                                   attributes={"namespace": meta["namespace"], "service_name": meta["name"],
                                               "cluster_ip": spec.get("clusterIP"),
                                               "selector": spec.get("selector", {})}))
    records.extend(changed_events(events))
    inventory = {
        "node": sorted(node["metadata"]["uid"] for node in nodes),
        "pod": sorted(pod["metadata"]["uid"] for pod in pods),
        "container": sorted(f"{pod['metadata']['uid']}/{container['name']}"
                            for pod in pods for container in pod.get("spec", {}).get("containers", [])),
        "service": sorted(service["metadata"]["uid"] for service in services),
    }
    records.append(observation("inventory", CLUSTER_ID, "k8s_object_uids", inventory,
                               "uid_sets", "k8s/list"))
    return records


if __name__ == "__main__":
    run_loop(collect, "cluster-probe:" + CLUSTER_ID, 10)
