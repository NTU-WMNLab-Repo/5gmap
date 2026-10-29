#!/usr/bin/env python3
"""Plot node and RAN Pod CPU source samples against the recorded traffic phases."""

import csv
from datetime import datetime
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


HERE = Path(__file__).resolve().parent


def moment(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


phases = [json.loads(line) for line in (HERE / "phases.jsonl").read_text(encoding="utf-8").splitlines()]
with (HERE / "cpu-memory-series.tsv").open(encoding="utf-8", newline="") as handle:
    samples = list(csv.DictReader(handle, delimiter="\t"))
origin = moment(phases[0]["started_at"])


def minute(value):
    return (moment(value) - origin).total_seconds() / 60


fig, axes = plt.subplots(3, 1, figsize=(13, 9), sharex=True, constrained_layout=True)
colors = {"az": "#277da1", "edge": "#d1495b", "UE": "#2a9d8f",
          "gNB DU": "#7b2cbf", "DNN": "#e9a23b"}

for axis in axes:
    for phase in phases:
        if phase["phase"] in ("dl", "ul"):
            axis.axvspan(minute(phase["started_at"]), minute(phase["ended_at"]),
                         color="#dce9f8" if phase["phase"] == "dl" else "#fff0d4", zorder=0)
    axis.grid(axis="y", color="#dddddd", linewidth=0.7)


def draw(axis, selected, label):
    selected = sorted(selected, key=lambda row: moment(row["source_time"]))
    if not selected:
        return
    color = colors[label]
    clean = [row for row in selected if not row["window_note"]]
    boundary = [row for row in selected if row["window_note"]]
    axis.plot([minute(row["source_time"]) for row in clean],
              [float(row["value"]) for row in clean], "-o", markersize=3,
              linewidth=1.1, color=color, label=label)
    axis.scatter([minute(row["source_time"]) for row in boundary],
                 [float(row["value"]) for row in boundary], marker="x", s=25,
                 color=color, alpha=0.65)


for site in ("az", "edge"):
    draw(axes[0], [row for row in samples if row["kind"] == "node"
                   and row["metric"] == "node_cpu_usage_cores" and row["name"] == site], site)
    draw(axes[1], [row for row in samples if row["kind"] == "node"
                   and row["metric"] == "os_cpu_busy_percent" and row["name"] == site], site)
for prefix, label in (("oai-nr-ue10", "UE"), ("oai-gnb-du10", "gNB DU"), ("oai-dnn10", "DNN")):
    draw(axes[2], [row for row in samples if row["kind"] == "pod"
                   and row["metric"] == "pod_cpu_usage_cores"
                   and row["name"].startswith(prefix)], label)

axes[0].set_ylabel("Node CPU (cores)")
axes[1].set_ylabel("Host CPU busy (%)")
axes[2].set_ylabel("Pod CPU (cores)")
axes[2].set_xlabel("Minutes since first baseline (2026-10-29 14:41:35 UTC)")
for axis in axes:
    axis.legend(loc="upper left", ncol=3)
axes[0].set_title("Three iperf3 rounds: DL shaded blue, UL shaded orange; x = boundary window")
fig.savefig(HERE / "cpu-time.png", dpi=160)
