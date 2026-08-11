# pyright: reportMissingImports=false
import os
from dataclasses import dataclass

from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    TraceFlags,
    TraceState,
    set_span_in_context,
)
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor


@dataclass(frozen=True)
class TraceIdentity:
    trace_id: str
    span_id: str


class LifecycleTraceEmitter:
    """Exports an immediate root and terminal summary for matched UE lifecycles."""

    def __init__(self, service_name: str) -> None:
        provider = TracerProvider(
            resource=Resource.create({"service.name": service_name})
        )
        if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))
        else:
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        self._tracer = provider.get_tracer(service_name)
        self._roots: dict[str, TraceIdentity] = {}

    def start(
        self,
        ue_correlation_id: str,
        start_time_ns: int,
        bound_time_ns: int,
        linked_protocols: list[str],
    ) -> TraceIdentity:
        span = self._tracer.start_span("UE lifecycle", start_time=start_time_ns)
        span.set_attribute("ue.correlation_id", ue_correlation_id)
        span.set_attribute("ue.lifecycle.root", True)
        span.set_attribute("ue.lifecycle.phase", "binding")
        span.set_attribute("ue.online.state", "matched")
        span.set_attribute("ue.linked_protocols", ",".join(linked_protocols))
        span.set_attribute("ue.lifecycle.started_unix_ns", start_time_ns)
        span.set_attribute("ue.lifecycle.bound_unix_ns", bound_time_ns)
        context = span.get_span_context()
        identity = TraceIdentity(
            trace_id=f"{context.trace_id:032x}",
            span_id=f"{context.span_id:016x}",
        )
        # Ending triggers SimpleSpanProcessor export before the identity returns.
        span.end(end_time=max(bound_time_ns, start_time_ns + 1))
        self._roots[ue_correlation_id] = identity
        return identity

    def finish(
        self,
        ue_correlation_id: str,
        state: str,
        close_reason: str | None,
        linked_protocols: list[str],
        start_time_ns: int,
        end_time_ns: int,
    ) -> None:
        root = self._roots.pop(ue_correlation_id, None)
        if root is None:
            return
        span = self._tracer.start_span(
            "UE lifecycle summary",
            context=self._root_context(root),
            start_time=end_time_ns,
        )
        span.set_attribute("ue.correlation_id", ue_correlation_id)
        span.set_attribute("ue.lifecycle.summary", True)
        span.set_attribute("ue.online.state", state)
        span.set_attribute("ue.linked_protocols", ",".join(linked_protocols))
        span.set_attribute("ue.lifecycle.started_unix_ns", start_time_ns)
        span.set_attribute("ue.lifecycle.ended_unix_ns", end_time_ns)
        span.set_attribute(
            "ue.lifecycle.observed_duration_ms",
            max(0, end_time_ns - start_time_ns) / 1_000_000,
        )
        if close_reason:
            span.set_attribute("ue.close_reason", close_reason)
        span.end(end_time=end_time_ns + 1)

    @staticmethod
    def _root_context(identity: TraceIdentity):
        root = SpanContext(
            trace_id=int(identity.trace_id, 16),
            span_id=int(identity.span_id, 16),
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
            trace_state=TraceState(),
        )
        return set_span_in_context(NonRecordingSpan(root))
