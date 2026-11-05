import copy
import json
from pathlib import Path
import sys
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


if __name__ == "__main__":
    unittest.main()
