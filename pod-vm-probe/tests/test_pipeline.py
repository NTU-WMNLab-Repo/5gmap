import json
import pathlib
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from datetime import datetime, timezone
from unittest.mock import patch


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import cluster_probe
import receiver
from common import observation


class PipelineTest(unittest.TestCase):
    def test_service_location_uses_ready_endpoint_site(self):
        responses = {
            "/api/v1/nodes": {"items": [{"metadata": {"uid": "node-1", "name": "worker-1",
                                                       "labels": {"deplocation": "edge"}},
                                           "status": {}}]},
            "/api/v1/pods": {"items": [{"metadata": {"uid": "pod-1", "name": "du-1",
                                                      "namespace": "oai"},
                                          "spec": {"nodeName": "worker-1", "containers": []},
                                          "status": {}}]},
            "/api/v1/events": {"items": []},
            "/api/v1/services": {"items": [{"metadata": {"uid": "svc-1", "name": "du",
                                                          "namespace": "oai"}, "spec": {}}]},
            "/api/v1/endpoints": {"items": [{"metadata": {"name": "du", "namespace": "oai"},
                                             "subsets": [{"addresses": [{"ip": "10.0.0.1",
                                                                         "targetRef": {"uid": "pod-1"}}]}]}]},
        }
        with patch.object(cluster_probe, "kube_json", side_effect=lambda path: responses[path]), \
             patch.object(cluster_probe, "kube_request", return_value=""):
            records = cluster_probe.collect()
        locations = [item for item in records if item["metric"] == "service_location"]
        self.assertEqual(locations[0]["value"], ["edge"])
        self.assertEqual(locations[0]["unit"], "sites")
        inventory = next(item for item in records if item["metric"] == "k8s_object_uids")
        self.assertEqual(inventory["value"], {"node": ["node-1"], "pod": ["pod-1"],
                                              "container": [], "service": ["svc-1"]})

    def test_events_emit_only_when_resource_version_changes(self):
        cluster_probe.EVENT_RESOURCE_VERSIONS.clear()
        event = {"metadata": {"uid": "event-1", "resourceVersion": "10",
                              "creationTimestamp": "2026-10-23T00:00:00Z"},
                 "reason": "Started", "involvedObject": {"kind": "Pod", "uid": "pod-1"}}
        first = cluster_probe.changed_events([event])
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["observed_at"], "2026-10-23T00:00:00Z")
        self.assertFalse(cluster_probe.changed_events([event]))
        event["metadata"]["resourceVersion"] = "11"
        self.assertEqual(len(cluster_probe.changed_events([event])), 1)

    def test_metrics_use_pod_uid_and_source_time(self):
        cluster_probe.PREVIOUS_CPU.clear()
        pod_uids = {("oai", "du-a"): "uid-a"}
        first = ('pod_cpu_usage_seconds_total{namespace="oai",pod="du-a"} 10 1000000\n'
                 'pod_memory_working_set_bytes{namespace="oai",pod="du-a"} 4096 1000000\n')
        second = 'pod_cpu_usage_seconds_total{namespace="oai",pod="du-a"} 12 1010000\n'
        records = cluster_probe.parse_metrics(first, "node-1", "edge", pod_uids)
        self.assertEqual([r["subject_id"] for r in records], ["uid-a"])
        records = cluster_probe.parse_metrics(second, "node-1", "edge", pod_uids)
        self.assertEqual(records[0]["subject_id"], "uid-a")
        self.assertAlmostEqual(records[0]["value"], 0.2)
        self.assertEqual(records[0]["observed_at"], "1970-01-01T00:16:50+00:00")
        self.assertFalse(cluster_probe.parse_metrics(second, "node-1", "edge", pod_uids))

    def test_receiver_stores_deduplicates_and_marks_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            receiver.DB_PATH = str(pathlib.Path(temp) / "test.sqlite3")
            receiver.CONFIG_PATH = str(pathlib.Path(temp) / "fixtures.json")
            pathlib.Path(receiver.CONFIG_PATH).write_text('{"version":"test"}', encoding="utf-8")
            with closing(receiver.connect()):
                pass
            server = receiver.ThreadingHTTPServer(("127.0.0.1", 0), receiver.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                record = observation("node", "node-1", "os_cpu_busy_percent", 12.5, "%", "test")
                record["collected_at"] = "2020-01-01T00:00:00+00:00"
                body = {"schema_version": 1, "probe_id": "test", "boot_id": "boot-1",
                        "sequence": 1, "observations": [record]}
                for expected_duplicate in (False, True):
                    request = urllib.request.Request(base + "/v1/observations",
                                                     data=json.dumps(body).encode(), method="POST")
                    with urllib.request.urlopen(request) as response:
                        self.assertEqual(json.load(response)["duplicate"], expected_duplicate)
                with urllib.request.urlopen(base + "/v1/state") as response:
                    state = json.load(response)
                self.assertEqual(len(state["observations"]), 1)
                self.assertTrue(state["observations"][0]["stale"])
                self.assertEqual(state["fixtures"]["version"], "test")
                older = dict(body, sequence=2, observations=[dict(record, value=99.0,
                                                                  collected_at="2019-01-01T00:00:00+00:00")])
                request = urllib.request.Request(base + "/v1/observations",
                                                 data=json.dumps(older).encode(), method="POST")
                with urllib.request.urlopen(request) as response:
                    self.assertTrue(json.load(response)["stored"])
                with urllib.request.urlopen(base + "/v1/summary") as response:
                    summary = json.load(response)
                self.assertEqual(summary["total"], 1)
                self.assertEqual(summary["by_kind"], {"node": 1})
                self.assertEqual(summary["fixtures_version"], "test")
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(base + "/v1/snapshot")
                self.assertEqual(raised.exception.code, 503)
                inventory = observation("inventory", "lab-rke", "k8s_object_uids",
                                        {"node": ["node-1"], "pod": [], "container": [],
                                         "service": []}, "uid_sets", "k8s/list")
                request = urllib.request.Request(base + "/v1/observations",
                                                 data=json.dumps(dict(body, sequence=4,
                                                                      observations=[inventory])).encode(),
                                                 method="POST")
                with urllib.request.urlopen(request):
                    pass
                with urllib.request.urlopen(base + "/v1/snapshot") as response:
                    snapshot = json.load(response)
                self.assertEqual(snapshot["total"], 0)
                self.assertEqual(snapshot["excluded"]["stale"], 1)
                self.assertEqual(len(snapshot["missing"]), len(receiver.REQUIRED_NODE_METRICS))
                with urllib.request.urlopen(base + "/v1/state?kind=node&limit=1") as response:
                    state = json.load(response)
                self.assertEqual(state["total"], 1)
                self.assertEqual(state["observations"][0]["value"], 12.5)
                with urllib.request.urlopen(base + "/v1/state?kind=gpu") as response:
                    self.assertEqual(json.load(response)["observations"], [])
                bad = dict(body, sequence=3, observations=[dict(record, collected_at="2020-01-01")])
                request = urllib.request.Request(base + "/v1/observations",
                                                 data=json.dumps(bad).encode(), method="POST")
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request)
                self.assertEqual(raised.exception.code, 400)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_source_timestamp_controls_freshness(self):
        record = observation("node", "node-1", "memory", 1, "bytes", "kubelet",
                             observed_at="2020-01-01T00:00:00Z")
        self.assertTrue(receiver.is_stale(record, datetime.now(timezone.utc)))

    def test_snapshot_excludes_retired_events_and_reports_unavailable(self):
        now = datetime.now(timezone.utc)
        members = {"node": ["node-1"], "pod": ["pod-new"],
                   "container": ["pod-new/app"], "service": ["service-1"]}
        inventory = observation("inventory", "lab-rke", "k8s_object_uids",
                                members, "uid_sets", "k8s/list")
        ready = observation("node", "node-1", "node_ready", "True", "state", "k8s/node")
        old_pod = observation("pod", "pod-old", "pod_ready", "True", "state", "k8s/pod")
        current_pod = observation("pod", "pod-new", "pod_ready", "True", "state", "k8s/pod")
        stale_container = observation("container", "pod-new/app", "container_ready", True,
                                      "boolean", "k8s/pod")
        stale_container["collected_at"] = "2020-01-01T00:00:00+00:00"
        event = observation("event", "event-1", "event_reason", "Started", "state", "k8s/event")
        unsupported = observation("gpu", "node-1/pci-1", "gpu_busy_percent", None, "%",
                                  "host/sys/pci", status="unsupported", node_uid="node-1")
        records = [inventory, ready, old_pod, current_pod, stale_container, event, unsupported]
        snapshot = receiver.decision_snapshot([(json.dumps(record), record["collected_at"])
                                               for record in records], now)
        self.assertEqual({item["subject_id"] for item in snapshot["observations"]},
                         {"node-1", "pod-new"})
        self.assertEqual(snapshot["excluded"], {"event": 1, "other": 1, "retired": 1,
                                                 "stale": 1, "non_ok": 1})
        self.assertEqual(snapshot["unavailable"][0]["metric"], "gpu_busy_percent")
        self.assertIn({"subject_kind": "node", "subject_id": "node-1",
                       "metric": "node_cpu_usage_cores"}, snapshot["missing"])
        inventory["collected_at"] = "2020-01-01T00:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "inventory missing or stale"):
            receiver.decision_snapshot([(json.dumps(inventory), inventory["collected_at"])], now)

    def test_existing_database_backfills_latest(self):
        with tempfile.TemporaryDirectory() as temp:
            receiver.DB_PATH = str(pathlib.Path(temp) / "old.sqlite3")
            record = observation("gpu", "node-1/pci-1", "gpu_busy_percent", 7, "%", "old")
            with closing(receiver.connect()) as db, db:
                db.execute("""INSERT INTO observations
                    (probe_id, boot_id, sequence, subject_kind, subject_id, metric,
                     collected_at, received_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    ("old-probe", "old-boot", 1, "gpu", "node-1/pci-1", "gpu_busy_percent",
                     record["collected_at"], record["collected_at"], json.dumps(record)))
            receiver.initialize()
            with closing(receiver.connect()) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM latest").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
