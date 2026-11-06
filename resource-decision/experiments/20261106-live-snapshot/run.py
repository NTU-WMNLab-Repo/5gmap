#!/usr/bin/env python3
"""Run a small scenario sensitivity check against one fixed receiver snapshot."""

import argparse
import copy
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from decide import decide  # noqa: E402


def cases(base):
    changes = {
        "baseline": lambda s: None,
        "base_cpu_0.1": lambda s: s["base_demand"].update(cpu_cores=0.1),
        "inter_edge_40mbps": lambda s: s["network"].update(inter_edge_capacity_bps=40_000_000),
        "uplink_60mbps": lambda s: s["network"]["uplink_capacity_bps"].update(edge=60_000_000),
        "uplink_10mbps": lambda s: s["network"]["uplink_capacity_bps"].update(edge=10_000_000),
    }
    for name, change in changes.items():
        scenario = copy.deepcopy(base)
        change(scenario)
        scenario["version"] = f"{base['version']}/{name}"
        yield name, scenario


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-file", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, default=ROOT / "config/scenario.example.json")
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot_file.read_text(encoding="utf-8"))
    base = json.loads(args.scenario.read_text(encoding="utf-8"))
    print("case\tstatus\twho\thow\twhere\tutility\tcpu_demand\tuplink_bps\tinter_edge_bps")
    for name, scenario in cases(base):
        result = decide(snapshot, scenario)
        demand = result.get("demand", {})
        print("\t".join(str(value) for value in (
            name, result["status"], ",".join(result.get("who", [])),
            ",".join(f"{key}:{value}" for key, value in result.get("how", {}).items()),
            result.get("where", ""), result.get("utility", ""), demand.get("cpu_cores", ""),
            sum(demand["uplink_bps_by_ingress"].values()) if demand else "",
            demand.get("inter_edge_bps", ""))))


if __name__ == "__main__":
    main()
