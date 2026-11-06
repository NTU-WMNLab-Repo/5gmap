import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from decide import decide  # noqa: E402


class DecisionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario = json.loads((ROOT / "config/scenario.example.json").read_text(encoding="utf-8"))
        cls.snapshot = json.loads((ROOT / "examples/snapshot.example.json").read_text(encoding="utf-8"))

    def test_selects_two_profiles_within_uplink_budget(self):
        result = decide(self.snapshot, self.scenario)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["where"], "edge")
        self.assertEqual(set(result["who"]), {"rsu-north", "rsu-east"})
        self.assertEqual(sorted(result["how"].values()), ["high", "low"])
        self.assertEqual(result["demand"]["uplink_bps_by_ingress"], {"edge": 80_000_000})
        self.assertEqual(result["budgets"]["edge"]["input_provenance"], ["simulated"])

    def test_moves_to_other_site_when_local_cpu_is_insufficient(self):
        snapshot = copy.deepcopy(self.snapshot)
        for record in snapshot["observations"]:
            if record["site_id"] == "edge" and record["metric"] == "node_cpu_usage_cores":
                record["value"] = 7.7
        result = decide(snapshot, self.scenario)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["where"], "az")

    def test_missing_or_paginated_snapshot_never_produces_placement(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["missing"] = [{"subject_kind": "node", "metric": "node_cpu_usage_cores"}]
        snapshot["observations"] = [record for record in snapshot["observations"]
                                    if not (record["site_id"] == "edge" and
                                            record["metric"] == "node_cpu_usage_cores")]
        snapshot["total"] -= 1
        self.assertEqual(decide(snapshot, self.scenario)["status"], "input_unavailable")
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["next_offset"] = 100
        self.assertEqual(decide(snapshot, self.scenario)["status"], "input_unavailable")

    def test_network_limit_can_make_every_choice_infeasible(self):
        scenario = copy.deepcopy(self.scenario)
        scenario["network"]["uplink_capacity_bps"]["edge"] = 10_000_000
        self.assertEqual(decide(self.snapshot, scenario)["status"], "no_feasible_configuration")

    def test_gpu_demand_requires_separate_measured_budget(self):
        scenario = copy.deepcopy(self.scenario)
        scenario["candidates"][0]["profiles"][0]["gpu_units"] = 1
        with self.assertRaisesRegex(ValueError, "GPU demand is unsupported"):
            decide(self.snapshot, scenario)

    def test_effective_requests_include_init_peak_and_overhead(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["inventory"]["counts"]["pod"] = 1
        snapshot["observations"].append({
            "subject_kind": "pod", "subject_id": "pod-1", "node_uid": "example-node-edge",
            "site_id": "edge", "metric": "pod_resource_inputs", "status": "ok",
            "provenance": "simulated", "value": {
                "phase": "Running", "containers": [
                    {"cpu": "300m", "memory": "128Mi"}, {"cpu": "200m", "memory": "128Mi"}],
                "init_containers": [{"cpu": "1200m", "memory": "512Mi"}],
                "overhead": {"cpu": "100m", "memory": "64Mi"}}})
        snapshot["total"] += 1
        result = decide(snapshot, self.scenario)
        budget = result["budgets"]["edge"]
        self.assertAlmostEqual(budget["existing_pod_requests"]["cpu_cores"], 1.3)
        self.assertEqual(budget["existing_pod_requests"]["memory_bytes"], 576 * 1024**2)
        self.assertAlmostEqual(budget["scheduling_headroom"]["cpu_cores"], 6.2)
        self.assertEqual(budget["counted_pods"], 1)
        snapshot["observations"][-1]["value"]["phase"] = "Succeeded"
        self.assertEqual(decide(snapshot, self.scenario)["budgets"]["edge"]["counted_pods"], 0)

    def test_scheduler_and_runtime_are_independent_constraints(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["inventory"]["counts"]["pod"] = 1
        snapshot["observations"].append({
            "subject_kind": "pod", "subject_id": "pod-1", "node_uid": "example-node-edge",
            "site_id": "edge", "metric": "pod_resource_inputs", "status": "ok",
            "provenance": "simulated", "value": {"phase": "Running", "containers": [{"cpu": "6"}],
                                                "init_containers": [], "overhead": {}}})
        snapshot["total"] += 1
        result = decide(snapshot, self.scenario)
        self.assertEqual(result["where"], "az")
        self.assertGreater(result["budgets"]["edge"]["runtime_headroom"]["cpu_cores"], 2.5)
        self.assertLess(result["budgets"]["edge"]["scheduling_headroom"]["cpu_cores"], 2.5)
        snapshot["observations"][-1]["value"]["containers"] = [{"cpu": "100m"}]
        for record in snapshot["observations"]:
            if record.get("site_id") == "edge" and record["metric"] == "node_cpu_usage_cores":
                record["value"] = 5.4
        result = decide(snapshot, self.scenario)
        self.assertEqual(result["where"], "az")
        self.assertGreater(result["budgets"]["edge"]["scheduling_headroom"]["cpu_cores"], 2.5)
        self.assertLess(result["budgets"]["edge"]["runtime_headroom"]["cpu_cores"], 2.5)

    def test_missing_pod_resource_inputs_blocks_proposal(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["inventory"]["counts"]["pod"] = 1
        result = decide(snapshot, self.scenario)
        self.assertEqual(result["status"], "input_unavailable")
        self.assertIn("pod resource inputs", result["reason"])

    def test_memory_runtime_and_request_budgets_are_separate(self):
        snapshot = copy.deepcopy(self.snapshot)
        for record in snapshot["observations"]:
            if record.get("site_id") == "edge" and record["metric"] == "os_memavailable_bytes":
                record["value"] = 400 * 1024**2
        result = decide(snapshot, self.scenario)
        self.assertEqual(result["where"], "az")
        self.assertGreater(result["budgets"]["edge"]["scheduling_headroom"]["memory_bytes"],
                           640 * 1024**2)
        self.assertLess(result["budgets"]["edge"]["runtime_headroom"]["memory_bytes"],
                        640 * 1024**2)

        snapshot = copy.deepcopy(self.snapshot)
        snapshot["inventory"]["counts"]["pod"] = 1
        snapshot["observations"].append({
            "subject_kind": "pod", "subject_id": "pod-1", "node_uid": "example-node-edge",
            "site_id": "edge", "metric": "pod_resource_inputs", "status": "ok",
            "provenance": "simulated", "value": {"phase": "Running", "containers": [{"memory": "7600Mi"}],
                                                "init_containers": [], "overhead": {}}})
        snapshot["total"] += 1
        result = decide(snapshot, self.scenario)
        self.assertEqual(result["where"], "az")
        self.assertGreater(result["budgets"]["edge"]["runtime_headroom"]["memory_bytes"],
                           640 * 1024**2)
        self.assertLess(result["budgets"]["edge"]["scheduling_headroom"]["memory_bytes"],
                        640 * 1024**2)

    def test_sensitivity_matrix_at_lab_like_edge_cpu_budget(self):
        snapshot = copy.deepcopy(self.snapshot)
        for record in snapshot["observations"]:
            if record["site_id"] == "edge" and record["metric"] == "node_cpu_usage_cores":
                record["value"] = 5.34  # simulated edge headroom: 8 - 5.34 - 0.5 = 2.16 cores
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            process = subprocess.run(
                [sys.executable, "-B", str(ROOT / "experiments/20261106-live-snapshot/run.py"),
                 "--snapshot-file", str(path)], capture_output=True, text=True, check=True)
        lines = [line.split("\t") for line in process.stdout.strip().splitlines()]
        rows = {line[0]: dict(zip(lines[0], line)) for line in lines[1:]}
        self.assertEqual((rows["baseline"]["where"], rows["baseline"]["utility"]), ("az", "0.75"))
        self.assertEqual((rows["base_cpu_0.1"]["where"], rows["base_cpu_0.1"]["utility"]),
                         ("edge", "0.75"))
        self.assertEqual((rows["inter_edge_40mbps"]["where"],
                          rows["inter_edge_40mbps"]["inter_edge_bps"]), ("edge", "0"))
        self.assertEqual((rows["uplink_60mbps"]["where"], rows["uplink_60mbps"]["utility"]),
                         ("edge", "0.5"))
        self.assertEqual(rows["uplink_10mbps"]["status"], "no_feasible_configuration")


if __name__ == "__main__":
    unittest.main()
