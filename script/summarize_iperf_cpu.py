#!/usr/bin/env python3
"""Assign probe source samples to iperf phases and report CPU/RAM time series."""

import collections
import csv
from datetime import datetime
import json
from pathlib import Path
import statistics
import sys


def instant(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def read_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_tsv(path, fields, rows):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main(samples_path, phases_path, pod_map_path, output_dir):
    pod_names = {}
    with open(pod_map_path, encoding="utf-8") as handle:
        for line in handle:
            uid, name, _node = line.rstrip("\n").split("\t", 2)
            pod_names[uid] = name

    phases = read_jsonl(phases_path)
    for phase in phases:
        phase["start"] = instant(phase["started_at"])
        phase["end"] = instant(phase["ended_at"])
    phases.sort(key=lambda phase: phase["start"])
    for earlier, later in zip(phases, phases[1:]):
        if earlier["end"] > later["start"]:
            raise ValueError("overlapping phase intervals")

    # A snapshot is a query of the receiver's latest values, not a new source sample.
    unique = {}
    for sample in read_jsonl(samples_path):
        for record in sample["observations"]:
            metric = record["metric"]
            if metric not in ("os_cpu_busy_percent", "os_memory_available_bytes") and not metric.endswith(
                ("cpu_usage_cores", "memory_working_set_bytes")
            ):
                continue
            kind, subject = record["subject_kind"], record["subject_id"]
            source_time = record.get("observed_at") or record["collected_at"]
            key = (kind, subject, metric, source_time)
            unique.setdefault(key, (record, sample["generated_at"]))

    previous_time = {}
    series = []
    for (kind, subject, metric, source_time), (record, query_time) in sorted(
        unique.items(), key=lambda item: instant(item[0][3])
    ):
        point = instant(source_time)
        owner = next((phase for phase in phases if phase["start"] <= point < phase["end"]), None)
        prior = previous_time.get((kind, subject, metric))
        previous_time[(kind, subject, metric)] = point
        if owner is None or owner["phase"] == "drain":
            continue
        if kind == "node":
            label = record.get("site_id") or subject
        else:
            pod_name = pod_names.get(subject.split("/")[0], "")
            if not pod_name.startswith(("oai-nr-ue", "oai-dnn", "oai-gnb-cu", "oai-gnb-du")):
                continue
            label = pod_name + ("/" + subject.split("/", 1)[1] if "/" in subject else "")
        if metric.endswith("_bytes"):
            unit, value = "MiB", float(record["value"]) / 1048576
        elif metric == "os_cpu_busy_percent":
            unit, value = "%", float(record["value"])
        else:
            unit, value = "cores", float(record["value"])
        rate = metric.endswith("cpu_usage_cores") or metric == "os_cpu_busy_percent"
        boundary = ("unknown_window_start" if prior is None else
                    "crosses_phase_start" if prior < owner["start"] and rate else "")
        if not rate:
            boundary = ""
        series.append({"user": owner["user"], "iteration": owner["iteration"],
                       "attempt": owner["attempt"], "phase": owner["phase"],
                       "kind": kind, "name": label, "metric": metric, "unit": unit,
                       "source_time": source_time, "query_time": query_time,
                       "value": f"{value:.6f}", "window_note": boundary})

    output = Path(output_dir)
    write_tsv(output / "cpu-memory-series.tsv",
              ("user", "iteration", "attempt", "phase", "kind", "name", "metric",
               "unit", "source_time", "query_time", "value", "window_note"), series)

    groups = collections.defaultdict(list)
    for row in series:
        group = (row["user"], row["iteration"], row["phase"], row["kind"],
                 row["name"], row["metric"], row["unit"])
        groups[group].append(row)
        groups[(row["user"], "all", row["phase"], row["kind"], row["name"],
                row["metric"], row["unit"])].append(row)
    summary = []
    for group, rows in sorted(groups.items(), key=lambda item: tuple(map(str, item[0]))):
        clean = [float(row["value"]) for row in rows if not row["window_note"]]
        summary.append(dict(zip(("user", "iteration", "phase", "kind", "name", "metric", "unit"), group)) |
                       {"source_n": len(rows), "clean_n": len(clean),
                        "mean": f"{statistics.mean(clean):.3f}" if clean else "",
                        "min": f"{min(clean):.3f}" if clean else "",
                        "max": f"{max(clean):.3f}" if clean else ""})
    write_tsv(output / "cpu-memory-summary.tsv",
              ("user", "iteration", "phase", "kind", "name", "metric", "unit",
               "source_n", "clean_n", "mean", "min", "max"), summary)


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit("usage: summarize_iperf_cpu.py samples.jsonl phases.jsonl pods.tsv output_dir")
    main(*sys.argv[1:])
