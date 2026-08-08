# pyright: reportMissingImports=false
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Optional

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    TraceFlags,
    TraceState,
    set_span_in_context,
)

from correlator.online.client import (
    OnlineCorrelatorClient,
    build_online_event,
    is_online_ue_candidate,
)

from proxies.sctp.relay import ForwardedPacket


@dataclass
class TraceJob:
    event: ForwardedPacket
    enqueue_monotonic_ns: int


@dataclass
class ProcessedTraceEvent:
    job: TraceJob
    decoded: Any
    correlation_fields: dict[str, bool | int | float | str]
    queue_delay_ms: float
    decoder_duration_ms: float
    online_event: Optional[dict[str, Any]] = None
    online_response: Optional[dict[str, Any]] = None
    buffer_timeout: bool = False
    buffer_started_monotonic_ns: Optional[int] = None


@dataclass
class BufferedTraceEvent:
    processed: ProcessedTraceEvent
    deadline_monotonic_ns: int


def configure_tracer(service_name: str) -> trace.Tracer:
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    else:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


class AsyncTraceWorker:
    def __init__(
        self,
        service_name: str,
        protocol_name: str,
        decoder: Any,
        queue_size: int,
        correlator: Any = None,
        online_correlator: Optional[OnlineCorrelatorClient] = None,
        online_buffer_ms: Optional[float] = None,
    ) -> None:
        self.service_name = service_name
        self.protocol_name = protocol_name
        self.decoder = decoder
        self.correlator = correlator
        self.online_correlator = online_correlator
        if online_buffer_ms is None:
            online_buffer_ms = float(os.getenv("ONLINE_TRACE_BUFFER_MS", "1000"))
        self.online_buffer_ns = int(max(0.0, online_buffer_ms) * 1_000_000)
        self.online_buffer_max_events = int(os.getenv("ONLINE_TRACE_BUFFER_MAX_EVENTS", "256"))
        self.queue: queue.Queue[TraceJob] = queue.Queue(maxsize=queue_size)
        self.tracer = configure_tracer(service_name)
        self.dropped = 0
        self._buffer: list[BufferedTraceEvent] = []
        self._thread = threading.Thread(target=self._run, name="trace-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def submit(self, event: ForwardedPacket) -> None:
        try:
            self.queue.put_nowait(
                TraceJob(event=event, enqueue_monotonic_ns=time.monotonic_ns())
            )
        except queue.Full:
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 100 == 0:
                logging.warning("Trace queue full; dropped %d trace events", self.dropped)

    def _run(self) -> None:
        while True:
            try:
                job = self.queue.get(timeout=self._queue_timeout_seconds())
            except queue.Empty:
                self._flush_expired_buffered_events()
                continue

            try:
                self._process(job)
            except Exception:
                logging.exception("Trace worker failed to process event")
            finally:
                self.queue.task_done()
                self._flush_expired_buffered_events()

    def _process(self, job: TraceJob) -> None:
        worker_start_ns = time.monotonic_ns()
        decoder_start_ns = worker_start_ns
        try:
            decoded = self.decoder.decode(job.event.payload, job.event.direction)
        except Exception as exc:
            logging.exception("Protocol decoder raised an exception")
            decoded = SimpleNamespace(
                protocol=self.protocol_name,
                direction=job.event.direction,
                pdu_type="decode_exception",
                procedure_code=None,
                procedure_name="decode_exception",
                message_name="decode_exception",
                fields={"decoder.strategy": "exception"},
                decode_error=str(exc),
            )
        decoder_done_ns = time.monotonic_ns()

        queue_delay_ms = (worker_start_ns - job.enqueue_monotonic_ns) / 1_000_000.0
        decoder_duration_ms = (decoder_done_ns - decoder_start_ns) / 1_000_000.0
        correlation_fields = self._correlate(decoded, job.event.recv_time_ns)

        processed = ProcessedTraceEvent(
            job=job,
            decoded=decoded,
            correlation_fields=correlation_fields,
            queue_delay_ms=queue_delay_ms,
            decoder_duration_ms=decoder_duration_ms,
        )
        self._handle_online_correlation(processed)

    def _handle_online_correlation(self, processed: ProcessedTraceEvent) -> None:
        if self.online_correlator is None:
            self._export(processed)
            return

        attributes = self._combined_decoded_attributes(processed)
        decoded = processed.decoded
        if not is_online_ue_candidate(decoded.protocol, attributes):
            self._export(processed)
            return

        online_event = build_online_event(
            service_name=self.service_name,
            protocol=decoded.protocol,
            direction=processed.job.event.direction,
            message_name=decoded.message_name,
            procedure_name=decoded.procedure_name,
            event_time_ns=processed.job.event.recv_time_ns,
            attributes=attributes,
        )
        processed.online_event = online_event
        processed.online_response = self.online_correlator.correlate(online_event)

        if self._should_buffer(processed):
            self._buffer_event(processed)
            return

        self._export(processed)
        trace_id = processed.online_response.get("trace_id") if processed.online_response else None
        if isinstance(trace_id, str) and trace_id:
            self._flush_buffered_events_for_trace(trace_id)

    def _export(self, processed: ProcessedTraceEvent) -> None:
        job = processed.job
        decoded = processed.decoded
        span_name = f"{decoded.protocol.upper()} {job.event.direction} {decoded.message_name}"
        parent_context = self._online_parent_context(processed.online_response)
        span = self.tracer.start_span(
            span_name,
            context=parent_context,
            start_time=job.event.recv_time_ns,
        )
        try:
            span.set_attribute("network.protocol.name", decoded.protocol)
            span.set_attribute("network.transport", "sctp")
            span.set_attribute(f"{decoded.protocol}.direction", job.event.direction)
            span.set_attribute(f"{decoded.protocol}.pdu.type", decoded.pdu_type)
            span.set_attribute(f"{decoded.protocol}.procedure.name", decoded.procedure_name)
            span.set_attribute(f"{decoded.protocol}.message.name", decoded.message_name)
            span.set_attribute(f"{decoded.protocol}.payload.size", len(job.event.payload))
            span.set_attribute("proxy.forward.duration_ms", job.event.forward_duration_ms)
            span.set_attribute("decoder.queue_delay_ms", processed.queue_delay_ms)
            span.set_attribute("decoder.duration_ms", processed.decoder_duration_ms)
            span.set_attribute("decoder.dropped_events", self.dropped)

            if decoded.procedure_code is not None:
                span.set_attribute(f"{decoded.protocol}.procedure.code", decoded.procedure_code)

            for key, value in job.event.sctp.items():
                span.set_attribute(f"sctp.{key}", value)

            for key, value in decoded.fields.items():
                if isinstance(value, (bool, int, float, str)):
                    span.set_attribute(key, value)
                else:
                    span.set_attribute(key, repr(value))

            for key, value in processed.correlation_fields.items():
                span.set_attribute(key, value)

            for key, value in self._online_attributes(processed).items():
                span.set_attribute(key, value)

            if decoded.decode_error:
                span.set_attribute("decoder.error", decoded.decode_error)
        finally:
            end_time = max(job.event.send_done_time_ns, job.event.recv_time_ns + 1)
            span.end(end_time=end_time)

    def _should_buffer(self, processed: ProcessedTraceEvent) -> bool:
        if self.online_buffer_ns <= 0:
            return False
        response = processed.online_response or {}
        if response.get("error"):
            return False
        state = response.get("state")
        confidence = response.get("confidence")
        return state == "pending" and confidence != "cross_protocol"

    def _buffer_event(self, processed: ProcessedTraceEvent) -> None:
        now_ns = time.monotonic_ns()
        processed.buffer_started_monotonic_ns = now_ns
        self._buffer.append(
            BufferedTraceEvent(
                processed=processed,
                deadline_monotonic_ns=now_ns + self.online_buffer_ns,
            )
        )
        if len(self._buffer) > self.online_buffer_max_events:
            oldest = self._buffer.pop(0)
            oldest.processed.buffer_timeout = True
            self._refresh_online_response(oldest.processed)
            self._export(oldest.processed)

    def _flush_buffered_events_for_trace(self, trace_id: str) -> None:
        remaining = []
        for item in self._buffer:
            self._refresh_online_response(item.processed)
            response = item.processed.online_response or {}
            if response.get("trace_id") == trace_id or not self._should_buffer(item.processed):
                self._export(item.processed)
            else:
                remaining.append(item)
        self._buffer = remaining

    def _flush_expired_buffered_events(self) -> None:
        if not self._buffer:
            return
        now_ns = time.monotonic_ns()
        remaining = []
        for item in self._buffer:
            if item.deadline_monotonic_ns > now_ns:
                remaining.append(item)
                continue
            item.processed.buffer_timeout = True
            self._refresh_online_response(item.processed)
            self._export(item.processed)
        self._buffer = remaining

    def _refresh_online_response(self, processed: ProcessedTraceEvent) -> None:
        if self.online_correlator is None or processed.online_event is None:
            return
        processed.online_response = self.online_correlator.resolve(processed.online_event)

    def _queue_timeout_seconds(self) -> float:
        if not self._buffer:
            return 0.1
        now_ns = time.monotonic_ns()
        next_deadline = min(item.deadline_monotonic_ns for item in self._buffer)
        return max(0.001, min(0.1, (next_deadline - now_ns) / 1_000_000_000.0))

    def _combined_decoded_attributes(self, processed: ProcessedTraceEvent) -> dict[str, Any]:
        attributes: dict[str, Any] = {}
        attributes.update(processed.decoded.fields)
        attributes.update(processed.correlation_fields)
        return attributes

    @staticmethod
    def _online_parent_context(response: Optional[dict[str, Any]]) -> Optional[Any]:
        if not response:
            return None
        trace_id_hex = response.get("trace_id")
        parent_span_id_hex = response.get("parent_span_id")
        if not valid_trace_id(trace_id_hex) or not valid_span_id(parent_span_id_hex):
            return None
        parent = SpanContext(
            trace_id=int(trace_id_hex, 16),
            span_id=int(parent_span_id_hex, 16),
            is_remote=True,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
            trace_state=TraceState(),
        )
        return set_span_in_context(NonRecordingSpan(parent))

    def _online_attributes(self, processed: ProcessedTraceEvent) -> dict[str, bool | int | float | str]:
        response = processed.online_response
        if not response:
            return {}

        attrs: dict[str, bool | int | float | str] = {
            "ue.online.enabled": True,
            "ue.online.state": str(response.get("state") or "unknown"),
            "ue.online.confidence": str(response.get("confidence") or "unknown"),
        }
        for response_key, attr_key in (
            ("trace_id", "ue.trace_id"),
            ("parent_span_id", "ue.parent_span_id"),
            ("ue_correlation_id", "ue.correlation_id"),
            ("close_reason", "ue.close_reason"),
            ("local_correlation_id", "ue.local_correlation_id"),
        ):
            value = response.get(response_key)
            if value is not None:
                attrs[attr_key] = str(value)

        linked_protocols = response.get("linked_protocols")
        if isinstance(linked_protocols, list):
            attrs["ue.linked_protocols"] = ",".join(str(item) for item in linked_protocols)

        if processed.buffer_timeout:
            attrs["ue.online.buffer.timeout"] = True
        if processed.buffer_started_monotonic_ns is not None:
            attrs["ue.online.buffer.duration_ms"] = (
                time.monotonic_ns() - processed.buffer_started_monotonic_ns
            ) / 1_000_000.0
        if response.get("error"):
            attrs["ue.online.error"] = str(response["error"])
        return attrs

    def _correlate(
        self,
        decoded: Any,
        event_time_ns: int,
    ) -> dict[str, bool | int | float | str]:
        if self.correlator is None:
            return {}

        try:
            return self.correlator.correlate(decoded, event_time_ns)
        except Exception:
            logging.exception("Correlator failed to process event")
            return {"correlation.error": "correlator_exception"}


def valid_trace_id(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 32:
        return False
    if value == "0" * 32:
        return False
    try:
        int(value, 16)
        return True
    except ValueError:
        return False


def valid_span_id(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 16:
        return False
    if value == "0" * 16:
        return False
    try:
        int(value, 16)
        return True
    except ValueError:
        return False
