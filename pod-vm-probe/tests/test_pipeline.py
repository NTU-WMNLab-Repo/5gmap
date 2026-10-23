import json
import pathlib
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import closing


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import cluster_probe
import receiver
from common import observation


class PipelineTest(unittest.TestCase):
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
                bad = dict(body, sequence=2, observations=[dict(record, collected_at="2020-01-01")])
                request = urllib.request.Request(base + "/v1/observations",
                                                 data=json.dumps(bad).encode(), method="POST")
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request)
                self.assertEqual(raised.exception.code, 400)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
