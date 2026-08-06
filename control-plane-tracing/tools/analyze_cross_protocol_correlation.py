#!/usr/bin/env python3
"""Offline F1AP/NGAP UE lifecycle correlation from Jaeger raw JSON.

This tool is intentionally offline-only. It proves whether the span attributes
already emitted by the F1AP and NGAP SCTP proxies contain enough evidence to
group both protocols into the same UE control-plane lifecycle.

Correlation logic:

1. Build one F1AP lifecycle per `f1ap.ue.correlation_id`.
2. Build one NGAP lifecycle per `ngap.ue.correlation_id`.
3. Score every F1AP/NGAP pair with independent evidence:
   - F1AP CU UE F1AP ID equals NGAP RAN UE NGAP ID.
     This is strong in OAI, but treated as implementation evidence rather than
     a portable 3GPP guarantee.
   - F1AP `InitialULRRCMessageTransfer` precedes NGAP `InitialUEMessage`
     within a short window.
   - The two lifecycles overlap in time, allowing a small slack.
   - Release-complete events appear on both protocols within a short window,
     or both lifecycles remain active at capture end.
   - Exact cell identity strings match when both sides emit comparable values.
4. Select one-to-one matches greedily from the highest scores. Low-scoring
   candidates are left unmatched instead of forcing a suspicious mapping.

Online plan:

To draw F1AP and NGAP spans in the same Jaeger trace, a future online
implementation needs a shared UE-session state visible to both proxies.
The shared state can be keyed by the same evidence used here: CU/RAN ID,
F1AP InitialULRRCMessageTransfer -> NGAP InitialUEMessage timing, and lifecycle
generation/release state.

For true same-trace rendering, the proxy worker must know the selected trace ID
before exporting each span. Because Jaeger cannot retroactively move already
exported spans into a different trace, an online design has three options:

- export with a shared trace ID once the match is known;
- buffer decoded UE spans briefly until enough evidence is available;
- export uncertain early spans with OpenTelemetry links, then place later spans
  in the shared trace after the match becomes confident.

A "trace" should represent one UE control-plane lifecycle, not a permanent
subscriber identity. Start a new trace for the next attach/session when release
is complete on both observed protocols, when a protocol-local generation is
incremented because an ID is reused, when an association/CU restart invalidates
state, or when an idle timeout closes a lifecycle that never emitted a complete
release sequence.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


F1AP_PROTOCOL = "f1ap"
NGAP_PROTOCOL = "ngap"


@dataclass(frozen=True)
class SpanRecord:
    protocol: str
    trace_id: str
    span_id: str
    operation_name: str
    start_us: int
    duration_us: int
    tags: dict[str, Any]

    @property
    def end_us(self) -> int:
        return self.start_us + self.duration_us

    @property
    def message_name(self) -> str:
        return str(self.tags.get(f"{self.protocol}.message.name") or "-")

    @property
    def direction(self) -> str:
        return str(self.tags.get(f"{self.protocol}.direction") or "-")


@dataclass
class Lifecycle:
    protocol: str
    correlation_id: str
    spans: list[SpanRecord] = field(default_factory=list)
    messages: Counter[str] = field(default_factory=Counter)
    ids: dict[str, set[int]] = field(default_factory=lambda: defaultdict(set))
    strings: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    released: bool = False

    def add_span(self, span: SpanRecord) -> None:
        self.spans.append(span)
        self.messages.update([span.message_name])
        self.released = self.released or bool(
            span.tags.get(f"{self.protocol}.ue.binding_released")
        )

    def finish(self) -> None:
        self.spans.sort(key=lambda span: span.start_us)
        if self.protocol == F1AP_PROTOCOL:
            self._collect_ints("cu_id", "f1ap.ue.cu_id", "f1ap.gnb.cu.ue.f1ap.id")
            self._collect_ints("du_id", "f1ap.ue.du_id", "f1ap.gnb.du.ue.f1ap.id")
            self._collect_ints("c_rnti", "f1ap.ue.c_rnti")
            self._collect_strings("c_rnti_hex", "f1ap.ue.c_rnti.hex")
            self._collect_strings("nr_cgi", "f1ap.nr.cgi")
        else:
            self._collect_ints("ran_id", "ngap.ue.ran_id", "ngap.ran.ue.ngap.id")
            self._collect_ints("amf_id", "ngap.ue.amf_id", "ngap.amf.ue.ngap.id")
            self._collect_ints("generation", "ngap.ue.context_generation")
            self._collect_strings("nr_cgi", "ngap.nr.cgi")
            self._collect_strings("tai", "ngap.tai")

    @property
    def first_us(self) -> int:
        return self.spans[0].start_us

    @property
    def last_us(self) -> int:
        return max(span.end_us for span in self.spans)

    def first_message_us(self, message_name: str) -> int | None:
        for span in self.spans:
            if span.message_name == message_name:
                return span.start_us
        return None

    def last_message_us(self, message_name: str) -> int | None:
        for span in reversed(self.spans):
            if span.message_name == message_name:
                return span.start_us
        return None

    def delay_values(self, tag_key: str) -> list[float]:
        values: list[float] = []
        for span in self.spans:
            value = span.tags.get(tag_key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))
        return values

    def _collect_ints(self, label: str, *tag_keys: str) -> None:
        for span in self.spans:
            for key in tag_keys:
                value = parse_int(span.tags.get(key))
                if value is not None:
                    self.ids[label].add(value)

    def _collect_strings(self, label: str, *tag_keys: str) -> None:
        for span in self.spans:
            for key in tag_keys:
                value = span.tags.get(key)
                if value is not None:
                    self.strings[label].add(str(value))


@dataclass
class MatchCandidate:
    f1ap: Lifecycle
    ngap: Lifecycle
    score: int
    confidence: str
    evidence: list[str]
    warnings: list[str]
    initial_gap_ms: float | None
    release_gap_ms: float | None
    window_gap_ms: float


def load_spans(path: Path, expected_protocol: str) -> list[SpanRecord]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    spans: list[SpanRecord] = []
    for trace in data.get("data", []):
        trace_id = str(trace.get("traceID") or "")
        for span in trace.get("spans", []):
            tags = {tag["key"]: tag.get("value") for tag in span.get("tags", [])}
            protocol = str(tags.get("network.protocol.name") or expected_protocol)
            if protocol != expected_protocol:
                continue
            spans.append(
                SpanRecord(
                    protocol=protocol,
                    trace_id=trace_id,
                    span_id=str(span.get("spanID") or ""),
                    operation_name=str(span.get("operationName") or ""),
                    start_us=int(span.get("startTime") or 0),
                    duration_us=int(span.get("duration") or 0),
                    tags=tags,
                )
            )
    spans.sort(key=lambda span: span.start_us)
    return spans


def build_lifecycles(
    spans: Iterable[SpanRecord], protocol: str
) -> tuple[list[Lifecycle], int]:
    grouped: dict[str, Lifecycle] = {}
    uncorrelated = 0
    key = f"{protocol}.ue.correlation_id"

    for span in spans:
        correlation_id = span.tags.get(key)
        if not isinstance(correlation_id, str) or not correlation_id:
            uncorrelated += 1
            continue
        lifecycle = grouped.setdefault(
            correlation_id,
            Lifecycle(protocol=protocol, correlation_id=correlation_id),
        )
        lifecycle.add_span(span)

    lifecycles = list(grouped.values())
    for lifecycle in lifecycles:
        lifecycle.finish()
    lifecycles.sort(key=lambda lifecycle: lifecycle.first_us)
    return lifecycles, uncorrelated


def score_candidate(
    f1ap: Lifecycle,
    ngap: Lifecycle,
    initial_gap_ms: float,
    window_slack_ms: float,
    release_gap_ms: float,
) -> MatchCandidate:
    score = 0
    evidence: list[str] = []
    warnings: list[str] = []

    f1_cu_ids = f1ap.ids.get("cu_id", set())
    ngap_ran_ids = ngap.ids.get("ran_id", set())
    shared_cu_ran = sorted(f1_cu_ids.intersection(ngap_ran_ids))
    if shared_cu_ran:
        score += 40
        evidence.append(
            "F1AP CU UE F1AP ID equals NGAP RAN UE NGAP ID: "
            + ",".join(str(value) for value in shared_cu_ran)
        )
        warnings.append("CU/RAN ID equality is OAI implementation evidence, not a standard guarantee")

    initial_gap = directed_gap_ms(
        f1ap.first_message_us("InitialULRRCMessageTransfer"),
        ngap.first_message_us("InitialUEMessage"),
    )
    if initial_gap is not None:
        if 0 <= initial_gap <= initial_gap_ms:
            score += 35
            evidence.append(
                "F1AP InitialULRRCMessageTransfer precedes NGAP InitialUEMessage "
                f"by {initial_gap:.3f} ms"
            )
        elif -200.0 <= initial_gap < 0:
            score += 10
            warnings.append(
                "NGAP InitialUEMessage appears before F1AP InitialULRRCMessageTransfer "
                f"by {abs(initial_gap):.3f} ms"
            )
        else:
            warnings.append(
                "Initial message gap is outside the configured window: "
                f"{initial_gap:.3f} ms"
            )
    else:
        warnings.append("Missing F1AP InitialULRRCMessageTransfer or NGAP InitialUEMessage")

    window_gap = lifecycle_gap_ms(f1ap, ngap)
    if window_gap == 0.0:
        score += 10
        evidence.append("F1AP and NGAP lifecycles overlap in time")
    elif window_gap <= window_slack_ms:
        score += 6
        evidence.append(
            f"F1AP and NGAP lifecycles are within {window_gap:.3f} ms of each other"
        )
    else:
        warnings.append(f"Lifecycle windows are separated by {window_gap:.3f} ms")

    release_gap = release_alignment_ms(f1ap, ngap)
    if release_gap is not None:
        if release_gap <= release_gap_ms:
            score += 10
            evidence.append(
                f"F1AP and NGAP release-complete events align within {release_gap:.3f} ms"
            )
        else:
            warnings.append(
                f"Release-complete events are separated by {release_gap:.3f} ms"
            )
    elif not f1ap.released and not ngap.released:
        score += 5
        evidence.append("Both lifecycles are still active at capture end")
    elif f1ap.released != ngap.released:
        warnings.append("Only one protocol emitted release-complete during the capture")

    shared_cells = sorted(f1ap.strings.get("nr_cgi", set()).intersection(ngap.strings.get("nr_cgi", set())))
    if shared_cells:
        score += 5
        evidence.append("Exact NR CGI attribute string matches on both protocols")

    score = min(score, 100)
    confidence = classify_confidence(score, shared_cu_ran, initial_gap, initial_gap_ms)
    return MatchCandidate(
        f1ap=f1ap,
        ngap=ngap,
        score=score,
        confidence=confidence,
        evidence=evidence,
        warnings=warnings,
        initial_gap_ms=initial_gap,
        release_gap_ms=release_gap,
        window_gap_ms=window_gap,
    )


def choose_matches(
    candidates: list[MatchCandidate],
    min_score: int,
) -> tuple[list[MatchCandidate], list[MatchCandidate]]:
    selected: list[MatchCandidate] = []
    rejected: list[MatchCandidate] = []
    used_f1ap: set[str] = set()
    used_ngap: set[str] = set()

    candidates = sorted(
        candidates,
        key=lambda item: (
            item.score,
            -(abs(item.initial_gap_ms) if item.initial_gap_ms is not None else 1_000_000),
        ),
        reverse=True,
    )
    for candidate in candidates:
        f1_id = candidate.f1ap.correlation_id
        ngap_id = candidate.ngap.correlation_id
        if candidate.score < min_score:
            rejected.append(candidate)
            continue
        if f1_id in used_f1ap or ngap_id in used_ngap:
            rejected.append(candidate)
            continue
        selected.append(candidate)
        used_f1ap.add(f1_id)
        used_ngap.add(ngap_id)
    return selected, rejected


def classify_confidence(
    score: int,
    shared_cu_ran: list[int],
    initial_gap: float | None,
    initial_gap_ms: float,
) -> str:
    has_initial_bridge = initial_gap is not None and 0 <= initial_gap <= initial_gap_ms
    if score >= 80 and shared_cu_ran and has_initial_bridge:
        return "high"
    if score >= 60 and (shared_cu_ran or has_initial_bridge):
        return "medium"
    if score >= 45:
        return "low"
    return "none"


def directed_gap_ms(first_us: int | None, second_us: int | None) -> float | None:
    if first_us is None or second_us is None:
        return None
    return (second_us - first_us) / 1000.0


def lifecycle_gap_ms(left: Lifecycle, right: Lifecycle) -> float:
    if left.last_us < right.first_us:
        return (right.first_us - left.last_us) / 1000.0
    if right.last_us < left.first_us:
        return (left.first_us - right.last_us) / 1000.0
    return 0.0


def release_alignment_ms(f1ap: Lifecycle, ngap: Lifecycle) -> float | None:
    f1_release = f1ap.last_message_us("UEContextReleaseComplete")
    ngap_release = ngap.last_message_us("UEContextReleaseComplete")
    if f1_release is None or ngap_release is None:
        return None
    return abs(f1_release - ngap_release) / 1000.0


def parse_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return None
    return None


def utc_time(start_us: int) -> str:
    return datetime.fromtimestamp(start_us / 1_000_000, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )[:-3]


def format_set(values: Iterable[Any]) -> str:
    items = sorted(str(value) for value in values)
    return ",".join(items) if items else "-"


def metric_summary(values: list[float]) -> str:
    if not values:
        return "no data"
    return (
        f"count={len(values)} min={min(values):.6f} "
        f"avg={statistics.mean(values):.6f} max={max(values):.6f}"
    )


def merged_timeline(f1ap: Lifecycle, ngap: Lifecycle) -> list[SpanRecord]:
    return sorted([*f1ap.spans, *ngap.spans], key=lambda span: span.start_us)


def print_lifecycle_summary(label: str, lifecycle: Lifecycle) -> None:
    if lifecycle.protocol == F1AP_PROTOCOL:
        id_text = (
            f"cu={format_set(lifecycle.ids.get('cu_id', []))} "
            f"du={format_set(lifecycle.ids.get('du_id', []))} "
            f"rnti={format_set(lifecycle.strings.get('c_rnti_hex', []))}"
        )
    else:
        id_text = (
            f"ran={format_set(lifecycle.ids.get('ran_id', []))} "
            f"amf={format_set(lifecycle.ids.get('amf_id', []))} "
            f"gen={format_set(lifecycle.ids.get('generation', []))}"
        )
    print(
        f"{label}: {lifecycle.correlation_id} spans={len(lifecycle.spans)} "
        f"{id_text} released={str(lifecycle.released).lower()} "
        f"window={utc_time(lifecycle.first_us)} -> {utc_time(lifecycle.last_us)}"
    )


def print_text_report(
    f1ap_path: Path,
    ngap_path: Path,
    f1ap_spans: list[SpanRecord],
    ngap_spans: list[SpanRecord],
    f1ap_lifecycles: list[Lifecycle],
    ngap_lifecycles: list[Lifecycle],
    uncorrelated_f1ap: int,
    uncorrelated_ngap: int,
    selected: list[MatchCandidate],
    unmatched_f1ap: list[Lifecycle],
    unmatched_ngap: list[Lifecycle],
    show_timeline: bool,
) -> None:
    print("Cross-Protocol UE Correlation Report")
    print(f"f1ap_raw: {f1ap_path}")
    print(f"ngap_raw: {ngap_path}")
    print(
        f"f1ap_spans={len(f1ap_spans)} f1ap_lifecycles={len(f1ap_lifecycles)} "
        f"f1ap_uncorrelated_spans={uncorrelated_f1ap}"
    )
    print(
        f"ngap_spans={len(ngap_spans)} ngap_lifecycles={len(ngap_lifecycles)} "
        f"ngap_uncorrelated_spans={uncorrelated_ngap}"
    )
    print(f"matches={len(selected)}")
    print()
    print("Logic")
    print(
        "  Uses one-to-one scoring across protocol-local UE lifecycles. Strong "
        "evidence is F1AP CU UE ID == NGAP RAN UE ID plus F1AP "
        "InitialULRRCMessageTransfer preceding NGAP InitialUEMessage. The ID "
        "equality is treated as OAI implementation evidence, not a portable "
        "3GPP guarantee."
    )
    print(
        "  An online same-trace version needs shared UE-session state before "
        "span export. Close the trace on release from the observed protocols, "
        "generation/ID reuse, association reset, or idle timeout; the next attach "
        "starts a new trace."
    )

    for index, match in enumerate(selected, start=1):
        ue_correlation_id = f"ue-offline-{index:04d}"
        print()
        print(f"Match {index}: {ue_correlation_id} score={match.score} confidence={match.confidence}")
        print_lifecycle_summary("  F1AP", match.f1ap)
        print_lifecycle_summary("  NGAP", match.ngap)
        if match.initial_gap_ms is not None:
            print(f"  initial_gap_ms={match.initial_gap_ms:.3f}")
        else:
            print("  initial_gap_ms=-")
        if match.release_gap_ms is not None:
            print(f"  release_gap_ms={match.release_gap_ms:.3f}")
        else:
            print("  release_gap_ms=-")
        print(f"  window_gap_ms={match.window_gap_ms:.3f}")
        print(
            "  f1ap_delays decoder.queue="
            f"{metric_summary(match.f1ap.delay_values('decoder.queue_delay_ms'))} "
            "decoder.duration="
            f"{metric_summary(match.f1ap.delay_values('decoder.duration_ms'))} "
            "forward="
            f"{metric_summary(match.f1ap.delay_values('proxy.forward.duration_ms'))}"
        )
        print(
            "  ngap_delays decoder.queue="
            f"{metric_summary(match.ngap.delay_values('decoder.queue_delay_ms'))} "
            "decoder.duration="
            f"{metric_summary(match.ngap.delay_values('decoder.duration_ms'))} "
            "forward="
            f"{metric_summary(match.ngap.delay_values('proxy.forward.duration_ms'))}"
        )
        print("  evidence:")
        for item in match.evidence:
            print(f"    - {item}")
        if match.warnings:
            print("  warnings:")
            for item in match.warnings:
                print(f"    - {item}")
        if show_timeline:
            print("  timeline:")
            for span in merged_timeline(match.f1ap, match.ngap):
                print(
                    "    "
                    f"{utc_time(span.start_us)} {span.protocol.upper()} "
                    f"{span.direction} {span.message_name}"
                )

    if unmatched_f1ap:
        print()
        print("Unmatched F1AP lifecycles")
        for lifecycle in unmatched_f1ap:
            print_lifecycle_summary("  F1AP", lifecycle)

    if unmatched_ngap:
        print()
        print("Unmatched NGAP lifecycles")
        for lifecycle in unmatched_ngap:
            print_lifecycle_summary("  NGAP", lifecycle)


def to_json_report(
    f1ap_path: Path,
    ngap_path: Path,
    f1ap_spans: list[SpanRecord],
    ngap_spans: list[SpanRecord],
    f1ap_lifecycles: list[Lifecycle],
    ngap_lifecycles: list[Lifecycle],
    uncorrelated_f1ap: int,
    uncorrelated_ngap: int,
    selected: list[MatchCandidate],
    unmatched_f1ap: list[Lifecycle],
    unmatched_ngap: list[Lifecycle],
) -> dict[str, Any]:
    return {
        "f1ap_raw": str(f1ap_path),
        "ngap_raw": str(ngap_path),
        "f1ap_span_count": len(f1ap_spans),
        "ngap_span_count": len(ngap_spans),
        "f1ap_lifecycle_count": len(f1ap_lifecycles),
        "ngap_lifecycle_count": len(ngap_lifecycles),
        "f1ap_uncorrelated_span_count": uncorrelated_f1ap,
        "ngap_uncorrelated_span_count": uncorrelated_ngap,
        "matches": [match_to_dict(index, match) for index, match in enumerate(selected, start=1)],
        "unmatched_f1ap": [lifecycle_to_dict(item) for item in unmatched_f1ap],
        "unmatched_ngap": [lifecycle_to_dict(item) for item in unmatched_ngap],
        "online_trace_policy": {
            "start": "first UE-associated F1AP/NGAP control message with enough decoded evidence",
            "same_trace_requirement": "shared UE-session trace ID must be selected before span export",
            "close": [
                "release complete observed on all participating protocols",
                "protocol-local generation increments because an ID is reused",
                "SCTP association or CU/proxy restart invalidates local state",
                "idle timeout closes a lifecycle with missing release evidence",
            ],
        },
    }


def match_to_dict(index: int, match: MatchCandidate) -> dict[str, Any]:
    return {
        "ue_correlation_id": f"ue-offline-{index:04d}",
        "score": match.score,
        "confidence": match.confidence,
        "initial_gap_ms": match.initial_gap_ms,
        "release_gap_ms": match.release_gap_ms,
        "window_gap_ms": match.window_gap_ms,
        "evidence": match.evidence,
        "warnings": match.warnings,
        "f1ap": lifecycle_to_dict(match.f1ap),
        "ngap": lifecycle_to_dict(match.ngap),
    }


def lifecycle_to_dict(lifecycle: Lifecycle) -> dict[str, Any]:
    return {
        "protocol": lifecycle.protocol,
        "correlation_id": lifecycle.correlation_id,
        "span_count": len(lifecycle.spans),
        "window_start_utc": utc_time(lifecycle.first_us),
        "window_end_utc": utc_time(lifecycle.last_us),
        "ids": {key: sorted(values) for key, values in lifecycle.ids.items()},
        "strings": {key: sorted(values) for key, values in lifecycle.strings.items()},
        "released": lifecycle.released,
        "messages": dict(lifecycle.messages),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline F1AP/NGAP UE lifecycle correlation from Jaeger raw JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--f1ap", type=Path, required=True, help="F1AP Jaeger /api/traces raw JSON")
    parser.add_argument("--ngap", type=Path, required=True, help="NGAP Jaeger /api/traces raw JSON")
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="report output format",
    )
    parser.add_argument(
        "--timeline",
        action="store_true",
        help="include merged F1AP/NGAP message timelines for each match",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=55,
        help="minimum score required for a one-to-one match",
    )
    parser.add_argument(
        "--initial-gap-ms",
        type=float,
        default=1000.0,
        help="max F1AP InitialULRRC -> NGAP InitialUE gap for strong evidence",
    )
    parser.add_argument(
        "--window-slack-ms",
        type=float,
        default=5000.0,
        help="allowed lifecycle separation before window evidence is rejected",
    )
    parser.add_argument(
        "--release-gap-ms",
        type=float,
        default=5000.0,
        help="allowed F1AP/NGAP release-complete separation",
    )
    args = parser.parse_args()

    f1ap_spans = load_spans(args.f1ap, F1AP_PROTOCOL)
    ngap_spans = load_spans(args.ngap, NGAP_PROTOCOL)
    f1ap_lifecycles, uncorrelated_f1ap = build_lifecycles(f1ap_spans, F1AP_PROTOCOL)
    ngap_lifecycles, uncorrelated_ngap = build_lifecycles(ngap_spans, NGAP_PROTOCOL)

    candidates = [
        score_candidate(
            f1ap,
            ngap,
            initial_gap_ms=args.initial_gap_ms,
            window_slack_ms=args.window_slack_ms,
            release_gap_ms=args.release_gap_ms,
        )
        for f1ap in f1ap_lifecycles
        for ngap in ngap_lifecycles
    ]
    selected, _ = choose_matches(candidates, min_score=args.min_score)
    matched_f1ap = {match.f1ap.correlation_id for match in selected}
    matched_ngap = {match.ngap.correlation_id for match in selected}
    unmatched_f1ap = [
        lifecycle for lifecycle in f1ap_lifecycles if lifecycle.correlation_id not in matched_f1ap
    ]
    unmatched_ngap = [
        lifecycle for lifecycle in ngap_lifecycles if lifecycle.correlation_id not in matched_ngap
    ]

    if args.format == "json":
        print(
            json.dumps(
                to_json_report(
                    args.f1ap,
                    args.ngap,
                    f1ap_spans,
                    ngap_spans,
                    f1ap_lifecycles,
                    ngap_lifecycles,
                    uncorrelated_f1ap,
                    uncorrelated_ngap,
                    selected,
                    unmatched_f1ap,
                    unmatched_ngap,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    print_text_report(
        args.f1ap,
        args.ngap,
        f1ap_spans,
        ngap_spans,
        f1ap_lifecycles,
        ngap_lifecycles,
        uncorrelated_f1ap,
        uncorrelated_ngap,
        selected,
        unmatched_f1ap,
        unmatched_ngap,
        show_timeline=args.timeline,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
