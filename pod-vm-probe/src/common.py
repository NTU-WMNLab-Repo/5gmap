import json
import os
import time
import urllib.request
import uuid
from collections import deque
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def kube_request(path):
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    host = os.environ["KUBERNETES_SERVICE_HOST"]
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    import ssl

    with open(token_path, encoding="utf-8") as handle:
        token = handle.read().strip()
    context = ssl.create_default_context(cafile=ca_path)
    url = f"https://{host}:{port}{path}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, context=context, timeout=8) as response:
        return response.read().decode("utf-8")


def kube_json(path):
    return json.loads(kube_request(path))


class Sender:
    def __init__(self, probe_id):
        self.probe_id = probe_id
        self.boot_id = str(uuid.uuid4())
        self.sequence = 0
        self.pending = deque(maxlen=60)
        self.dropped_batches = 0
        self.endpoint = os.environ.get("RECEIVER_URL", "http://pod-probe-receiver:8080/v1/observations")

    def enqueue(self, observations):
        self.sequence += 1
        if len(self.pending) == self.pending.maxlen:
            self.pending.popleft()
            self.dropped_batches += 1
            print(f"send queue full; dropped_batches={self.dropped_batches}", flush=True)
        self.pending.append(json.dumps({
            "schema_version": 1,
            "probe_id": self.probe_id,
            "boot_id": self.boot_id,
            "sequence": self.sequence,
            "observations": observations,
        }, separators=(",", ":")).encode("utf-8"))

    def flush(self):
        while self.pending:
            payload = self.pending[0]
            request = urllib.request.Request(
                self.endpoint, data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                if response.status != 200:
                    raise RuntimeError(f"receiver returned {response.status}")
            self.pending.popleft()


def observation(subject_kind, subject_id, metric, value, unit, source,
                *, status="ok", reason=None, node_uid=None, site_id=None,
                observed_at=None, ttl_seconds=45, attributes=None):
    return {
        "subject_kind": subject_kind, "subject_id": subject_id,
        "node_uid": node_uid, "site_id": site_id,
        "metric": metric, "value": value, "unit": unit, "source": source,
        "status": status, "reason": reason, "provenance": "measured",
        "observed_at": observed_at, "collected_at": utc_now(),
        "ttl_seconds": ttl_seconds, "attributes": attributes or {},
    }


def run_loop(collect, probe_id, interval):
    sender = Sender(probe_id)
    last_report = 0.0
    while True:
        started = time.monotonic()
        count = 0
        try:
            records = collect()
            count = len(records)
            sender.enqueue(records)
        except Exception as exc:
            print(f"collection failed: {exc}", flush=True)
        try:
            sender.flush()
            if time.monotonic() - last_report >= 60:
                print(f"{probe_id}: collected={count}, pending=0, dropped={sender.dropped_batches}", flush=True)
                last_report = time.monotonic()
        except Exception as exc:
            print(f"send failed: {exc}; pending={len(sender.pending)}", flush=True)
        time.sleep(max(1, interval - (time.monotonic() - started)))
