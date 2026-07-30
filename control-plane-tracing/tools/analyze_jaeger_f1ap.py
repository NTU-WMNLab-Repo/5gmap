#!/usr/bin/env python3
import argparse
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_spans(path: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    spans = []
    for trace in data.get("data", []):
        for span in trace.get("spans", []):
            tags = {tag["key"]: tag.get("value") for tag in span.get("tags", [])}
            spans.append((span, tags))
    spans.sort(key=lambda item: item[0].get("startTime", 0))
    return spans


def utc_time(start_time_us: int) -> str:
    return datetime.fromtimestamp(start_time_us / 1_000_000, tz=timezone.utc).strftime(
        "%H:%M:%S.%f"
    )[:-3]


def attr(tags: dict[str, Any], key: str) -> str:
    value = tags.get(key)
    if value is None:
        return "-"
    return str(value)


def hex_attr(tags: dict[str, Any], hex_key: str, int_key: str) -> str:
    value = tags.get(hex_key)
    if value is not None:
        return str(value)
    int_value = tags.get(int_key)
    if isinstance(int_value, int):
        return f"0x{int_value:04x}"
    return "-"


def numeric_values(items: list[tuple[dict[str, Any], dict[str, Any]]], key: str) -> list[float]:
    values = []
    for _, tags in items:
        value = tags.get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def print_metric(items: list[tuple[dict[str, Any], dict[str, Any]]], key: str) -> None:
    values = numeric_values(items, key)
    if not values:
        print(f"  {key}: no data")
        return
    print(
        f"  {key}: count={len(values)} "
        f"min={min(values):.6f} avg={statistics.mean(values):.6f} max={max(values):.6f}"
    )


def summarize_group(
    correlation_id: str,
    items: list[tuple[dict[str, Any], dict[str, Any]]],
    show_timeline: bool,
) -> None:
    first_span = items[0][0]
    last_span = items[-1][0]
    names = Counter(attr(tags, "f1ap.message.name") for _, tags in items)
    du_ids = Counter(attr(tags, "f1ap.gnb.du.ue.f1ap.id") for _, tags in items)
    cu_ids = Counter(attr(tags, "f1ap.gnb.cu.ue.f1ap.id") for _, tags in items)
    c_rntis = Counter(attr(tags, "f1ap.ue.c_rnti") for _, tags in items)
    c_rnti_hex = Counter(
        hex_attr(tags, "f1ap.ue.c_rnti.hex", "f1ap.ue.c_rnti") for _, tags in items
    )
    released = sum(1 for _, tags in items if tags.get("f1ap.ue.binding_released") is True)

    print(f"\n{correlation_id}")
    print(f"  spans: {len(items)}")
    print(f"  window_utc: {utc_time(first_span['startTime'])} -> {utc_time(last_span['startTime'])}")
    print(f"  du_ids: {dict(du_ids)}")
    print(f"  cu_ids: {dict(cu_ids)}")
    print(f"  c_rnti: {dict(c_rntis)}")
    print(f"  c_rnti_hex: {dict(c_rnti_hex)}")
    print(f"  release_complete_spans: {released}")
    print(f"  messages: {dict(names)}")
    print_metric(items, "decoder.queue_delay_ms")
    print_metric(items, "decoder.duration_ms")
    print_metric(items, "proxy.forward.duration_ms")

    if not show_timeline:
        return

    print("  timeline:")
    for span, tags in items:
        released_marker = " released" if tags.get("f1ap.ue.binding_released") is True else ""
        print(
            "    "
            f"{utc_time(span['startTime'])} "
            f"{attr(tags, 'f1ap.direction')} "
            f"{attr(tags, 'f1ap.message.name')} "
            f"du={attr(tags, 'f1ap.gnb.du.ue.f1ap.id')} "
            f"cu={attr(tags, 'f1ap.gnb.cu.ue.f1ap.id')} "
            f"rnti={attr(tags, 'f1ap.ue.c_rnti')} "
            f"rnti_hex={hex_attr(tags, 'f1ap.ue.c_rnti.hex', 'f1ap.ue.c_rnti')}"
            f"{released_marker}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize f1proxy Jaeger raw JSON by F1AP correlation ID."
    )
    parser.add_argument("raw_json", type=Path, help="Jaeger /api/traces raw JSON file")
    parser.add_argument(
        "--no-timeline",
        action="store_true",
        help="only print per-correlation summaries",
    )
    args = parser.parse_args()

    spans = load_spans(args.raw_json)
    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    uncorrelated = 0
    message_names = Counter()

    for span, tags in spans:
        message_names.update([attr(tags, "f1ap.message.name")])
        correlation_id = tags.get("f1ap.ue.correlation_id")
        if isinstance(correlation_id, str) and correlation_id:
            grouped[correlation_id].append((span, tags))
        else:
            uncorrelated += 1

    print(f"file: {args.raw_json}")
    print(f"span_count: {len(spans)}")
    print(f"correlated_span_count: {sum(len(items) for items in grouped.values())}")
    print(f"uncorrelated_span_count: {uncorrelated}")
    print(f"correlation_id_count: {len(grouped)}")
    print(f"message_counts: {dict(message_names)}")
    print_metric(spans, "decoder.queue_delay_ms")
    print_metric(spans, "decoder.duration_ms")
    print_metric(spans, "proxy.forward.duration_ms")

    for correlation_id, items in grouped.items():
        summarize_group(correlation_id, items, show_timeline=not args.no_timeline)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
