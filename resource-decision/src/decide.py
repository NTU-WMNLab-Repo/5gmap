#!/usr/bin/env python3
"""Propose a resource-feasible contributor, fidelity, and site configuration."""

import argparse
import itertools
import json
import math
from pathlib import Path
import urllib.request


def quantity(value, base):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        raise ValueError(f"invalid Kubernetes quantity: {value!r}")
    suffixes = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4,
                "k": 1000, "K": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4,
                "m": 0.001, "u": 0.000001, "n": 0.000000001}
    for suffix, scale in suffixes.items():
        if value.endswith(suffix):
            return float(value[:-len(suffix)]) * scale
    return float(value)


def effective_pod_request(value, pod_id):
    if not isinstance(value, dict) or not isinstance(value.get("containers"), list) or \
            not isinstance(value.get("init_containers"), list) or \
            not isinstance(value.get("overhead"), dict):
        raise ValueError(f"pod {pod_id}: incomplete resource inputs")
    result = {}
    for resource, field in (("cpu", "cpu_cores"), ("memory", "memory_bytes")):
        def request(raw):
            if not isinstance(raw, dict):
                raise ValueError(f"pod {pod_id}: invalid {resource} request")
            return positive_number(quantity(raw.get(resource, "0"), resource),
                                   f"pod {pod_id}.{resource}")

        app_sum = sum(request(raw) for raw in value["containers"])
        init_max = max((request(raw) for raw in value["init_containers"]), default=0)
        result[field] = max(app_sum, init_max) + request(value["overhead"])
    return result


def positive_number(value, name, allow_zero=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < 0 or (not allow_zero and value == 0):
        raise ValueError(f"{name} must be {'positive' if not allow_zero else 'non-negative'}")
    return float(value)


def scenario_fields(scenario):
    if scenario.get("schema_version") != 1 or scenario.get("provenance") != "simulated":
        raise ValueError("scenario must have schema_version=1 and provenance=simulated")
    for key in ("session_id", "target_id", "serving_site"):
        if not isinstance(scenario.get(key), str) or not scenario[key]:
            raise ValueError(f"scenario.{key} is required")
    sites = scenario.get("eligible_sites")
    if not isinstance(sites, list) or not sites or any(not isinstance(s, str) or not s for s in sites):
        raise ValueError("eligible_sites must be a nonempty list")
    if len(set(sites)) != len(sites) or scenario["serving_site"] not in sites:
        raise ValueError("eligible_sites must be unique and contain serving_site")
    candidates = scenario.get("candidates")
    if not isinstance(candidates, list) or not candidates or len(candidates) > 8:
        raise ValueError("candidates must contain 1 to 8 entries")
    ids = set()
    for candidate in candidates:
        cid = candidate.get("id")
        if not isinstance(cid, str) or not cid or cid in ids:
            raise ValueError("candidate IDs must be unique nonempty strings")
        ids.add(cid)
        if not isinstance(candidate.get("ingress_site"), str) or not candidate["ingress_site"]:
            raise ValueError(f"candidate {cid}: ingress_site is required")
        profiles = candidate.get("profiles")
        if not isinstance(profiles, list) or not 1 <= len(profiles) <= 4:
            raise ValueError(f"candidate {cid}: 1 to 4 profiles are required")
        names = set()
        for profile in profiles:
            name = profile.get("id")
            if not isinstance(name, str) or not name or name in names:
                raise ValueError(f"candidate {cid}: profile IDs must be unique")
            names.add(name)
            for field in ("cpu_cores", "memory_bytes", "uplink_bps", "utility"):
                positive_number(profile.get(field), f"{cid}.{name}.{field}")
            if profile.get("gpu_units", 0) != 0:
                raise ValueError("GPU demand is unsupported until a measured GPU budget is available")
    for field in ("cpu_cores", "memory_bytes"):
        positive_number(scenario.get("base_demand", {}).get(field), f"base_demand.{field}")
        positive_number(scenario.get("extra_ran_reserve", {}).get(field),
                        f"extra_ran_reserve.{field}")
    positive_number(scenario.get("min_utility"), "min_utility")
    network = scenario.get("network", {})
    if network.get("provenance") != "simulated":
        raise ValueError("network.provenance must be simulated")
    for site in {candidate["ingress_site"] for candidate in candidates}:
        positive_number(network.get("uplink_capacity_bps", {}).get(site),
                        f"network.uplink_capacity_bps.{site}", allow_zero=False)
    positive_number(network.get("inter_edge_capacity_bps"),
                    "network.inter_edge_capacity_bps", allow_zero=False)


def node_budgets(snapshot, scenario):
    if (snapshot.get("schema_version") != 1 or
            not isinstance(snapshot.get("generated_at"), str) or
            not isinstance(snapshot.get("inventory"), dict) or
            not isinstance(snapshot.get("observations"), list) or
            not isinstance(snapshot.get("missing"), list) or
            "next_offset" not in snapshot or
            type(snapshot.get("total")) is not int):
        raise ValueError("expected a complete /v1/snapshot response")
    if snapshot["next_offset"] is not None or snapshot["total"] != len(snapshot["observations"]):
        raise ValueError("snapshot is paginated; fetch all records before deciding")
    required = ("node_ready", "node_unschedulable", "node_capacity_cpu",
                "node_allocatable_cpu", "node_allocatable_memory",
                "node_cpu_usage_cores", "os_memavailable_bytes")
    counts = snapshot["inventory"].get("counts")
    if not isinstance(counts, dict):
        raise ValueError("snapshot inventory needs object counts")
    pod_count = counts.get("pod")
    if type(pod_count) is not int or pod_count < 0:
        raise ValueError("snapshot inventory needs a pod count")
    pod_records = [record for record in snapshot["observations"]
                   if record.get("subject_kind") == "pod" and
                   record.get("metric") == "pod_resource_inputs"]
    pod_ids = [record.get("subject_id") for record in pod_records]
    if len(pod_records) != pod_count or any(not isinstance(uid, str) or not uid for uid in pod_ids) or \
            len(set(pod_ids)) != pod_count or \
            any(record.get("status") != "ok" for record in pod_records):
        raise ValueError("pod resource inputs are incomplete or duplicated")
    if any(not isinstance(record.get("value"), dict) or
           not isinstance(record["value"].get("phase"), str) for record in pod_records):
        raise ValueError("pod resource inputs have invalid values")
    if any(record["value"]["phase"] not in ("Succeeded", "Failed") and
           record.get("attributes", {}).get("node_name") and not record.get("node_uid")
           for record in pod_records):
        raise ValueError("assigned pod is missing its node UID")
    nodes = {}
    for record in snapshot["observations"]:
        if record.get("subject_kind") != "node" or record.get("metric") not in required:
            continue
        if record.get("status") != "ok":
            continue
        site, uid = record.get("site_id"), record.get("subject_id")
        if not site or not uid:
            continue
        site_nodes = nodes.setdefault(site, {})
        metrics = site_nodes.setdefault(uid, {})
        metrics[record["metric"]] = record
    result = {}
    for site in scenario["eligible_sites"]:
        site_nodes = nodes.get(site, {})
        if len(site_nodes) != 1:
            raise ValueError(f"site {site}: expected exactly one node, found {len(site_nodes)}")
        uid, metrics = next(iter(site_nodes.items()))
        absent = set(required) - set(metrics)
        if absent:
            raise ValueError(f"site {site}: missing {', '.join(sorted(absent))}")
        if metrics["node_ready"]["value"] != "True":
            raise ValueError(f"site {site}: node is not Ready")
        if metrics["node_unschedulable"]["value"] is not False:
            raise ValueError(f"site {site}: node is unschedulable")
        capacity_cpu = positive_number(quantity(metrics["node_capacity_cpu"]["value"], "cpu"),
                                       f"{site}.capacity_cpu", allow_zero=False)
        allocatable_cpu = positive_number(quantity(metrics["node_allocatable_cpu"]["value"], "cpu"),
                                          f"{site}.allocatable_cpu", allow_zero=False)
        allocatable_memory = positive_number(quantity(metrics["node_allocatable_memory"]["value"], "memory"),
                                             f"{site}.allocatable_memory", allow_zero=False)
        used_cpu = positive_number(metrics["node_cpu_usage_cores"]["value"], f"{site}.used_cpu")
        available_memory = positive_number(metrics["os_memavailable_bytes"]["value"],
                                           f"{site}.os_memavailable_bytes")
        assigned = [record for record in pod_records if record.get("node_uid") == uid and
                    record["value"].get("phase") not in ("Succeeded", "Failed")]
        requested = {"cpu_cores": 0.0, "memory_bytes": 0.0}
        for record in assigned:
            effective = effective_pod_request(record["value"], record["subject_id"])
            for field in requested:
                requested[field] += effective[field]
        reserve = scenario["extra_ran_reserve"]
        scheduling = {
            "cpu_cores": max(0, allocatable_cpu - requested["cpu_cores"] - float(reserve["cpu_cores"])),
            "memory_bytes": max(0, allocatable_memory - requested["memory_bytes"] - float(reserve["memory_bytes"])),
        }
        runtime = {
            "cpu_cores": max(0, capacity_cpu - used_cpu - float(reserve["cpu_cores"])),
            "memory_bytes": max(0, available_memory - float(reserve["memory_bytes"])),
        }
        result[site] = {"node_uid": uid,
                        "cpu_cores": min(scheduling["cpu_cores"], runtime["cpu_cores"]),
                        "memory_bytes": min(scheduling["memory_bytes"], runtime["memory_bytes"]),
                        "scheduling_headroom": scheduling, "runtime_headroom": runtime,
                        "existing_pod_requests": requested, "counted_pods": len(assigned),
                        "capacity_model": "independent_scheduling_and_runtime_checks",
                        "input_provenance": sorted({record.get("provenance", "unknown")
                                                    for record in list(metrics.values()) + assigned})}
    return result


def decide(snapshot, scenario):
    scenario_fields(scenario)
    try:
        budgets = node_budgets(snapshot, scenario)
    except ValueError as exc:
        return {"status": "input_unavailable", "reason": str(exc), "session_id": scenario["session_id"]}

    network = scenario["network"]
    best = None
    for choices in itertools.product(*([None] + candidate["profiles"] for candidate in scenario["candidates"])):
        selected = [(candidate, profile) for candidate, profile in zip(scenario["candidates"], choices)
                    if profile is not None]
        utility = sum(float(profile["utility"]) for _, profile in selected)
        if utility < scenario["min_utility"]:
            continue
        by_ingress = {}
        for candidate, profile in selected:
            ingress = candidate["ingress_site"]
            by_ingress[ingress] = by_ingress.get(ingress, 0) + float(profile["uplink_bps"])
        if any(demand > float(network["uplink_capacity_bps"][site])
               for site, demand in by_ingress.items()):
            continue
        cpu = float(scenario["base_demand"]["cpu_cores"]) + sum(
            float(profile["cpu_cores"]) for _, profile in selected)
        memory = float(scenario["base_demand"]["memory_bytes"]) + sum(
            float(profile["memory_bytes"]) for _, profile in selected)
        for site in scenario["eligible_sites"]:
            budget = budgets[site]
            if any(cpu > budget[check]["cpu_cores"] or memory > budget[check]["memory_bytes"]
                   for check in ("scheduling_headroom", "runtime_headroom")):
                continue
            inter_edge_bps = sum(float(profile["uplink_bps"]) for candidate, profile in selected
                                 if candidate["ingress_site"] != site)
            if inter_edge_bps > float(network["inter_edge_capacity_bps"]):
                continue
            local = site == scenario["serving_site"]
            # Deterministic tie-break: utility, local site, fewer contributors, lower CPU demand.
            rank = (utility, int(local), -len(selected), -cpu)
            if best is None or rank > best[0]:
                best = (rank, site, selected, cpu, memory, by_ingress, inter_edge_bps)
    base = {"schema_version": 1, "session_id": scenario["session_id"],
            "target_id": scenario["target_id"], "snapshot_generated_at": snapshot.get("generated_at"),
            "scenario_version": scenario.get("version"), "scenario_provenance": "simulated",
            "network_provenance": "simulated", "execution": "proposal_only",
            "budgets": budgets,
            "schedulability": "cpu_memory_requests_checked_other_constraints_unverified",
            "demand_assumption": "scenario_cpu_memory_are_both_new_pod_requests_and_expected_usage"}
    if best is None:
        return {**base, "status": "no_feasible_configuration", "min_utility": scenario["min_utility"]}
    _, site, selected, cpu, memory, by_ingress, inter_edge_bps = best
    return {**base, "status": "proposed", "who": [candidate["id"] for candidate, _ in selected],
            "how": {candidate["id"]: profile["id"] for candidate, profile in selected},
            "where": site, "utility": sum(float(profile["utility"]) for _, profile in selected),
            "demand": {"cpu_cores": cpu, "memory_bytes": memory,
                       "uplink_bps_by_ingress": by_ingress, "inter_edge_bps": inter_edge_bps}}


def main():
    parser = argparse.ArgumentParser(description="Propose who/how/where from a probe snapshot and scenario")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot-file", type=Path)
    source.add_argument("--snapshot-url")
    parser.add_argument("--scenario", type=Path, required=True)
    args = parser.parse_args()
    if args.snapshot_file:
        snapshot = json.loads(args.snapshot_file.read_text(encoding="utf-8"))
        mode = "replay"
    else:
        with urllib.request.urlopen(args.snapshot_url, timeout=8) as response:
            snapshot = json.load(response)
        mode = "live_query"
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    result = decide(snapshot, scenario)
    result["mode"] = mode
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
