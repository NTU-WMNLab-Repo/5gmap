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

from proxies.udp.relay import ForwardedDatagram


@dataclass
class TraceJob:
    event: ForwardedDatagram
    enqueue_monotonic_ns: int


def configure_tracer(service_name: str) -> trace.Tracer:
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    else:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


class AsyncDatagramTraceWorker:
    """Decode and export UDP spans only after the relay has forwarded a datagram."""

    def __init__(
        self,
        service_name: str,
        protocol_name: str,
        queue_size: int,
        decoder: Optional[Any] = None,
        transaction_correlator: Optional[Any] = None,
    ) -> None:
        self.protocol_name = protocol_name
        self.decoder = decoder
        self.transaction_correlator = transaction_correlator
        self.queue: queue.Queue[TraceJob] = queue.Queue(maxsize=queue_size)
        self.tracer = configure_tracer(service_name)
        self.dropped = 0
        self._thread = threading.Thread(target=self._run, name="udp-trace-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def submit(self, event: ForwardedDatagram) -> None:
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
                job = self.queue.get(timeout=0.1)
            except queue.Empty:
                self._expire_transaction_contexts()
                continue
            try:
                self._export(job)
            except Exception:
                logging.exception("UDP trace worker failed to export event")
            finally:
                self.queue.task_done()
                self._expire_transaction_contexts()

    def _export(self, job: TraceJob) -> None:
        worker_start_ns = time.monotonic_ns()
        decoded_messages = self._decode(job.event)
        decoder_done_ns = time.monotonic_ns()
        queue_delay_ms = (worker_start_ns - job.enqueue_monotonic_ns) / 1_000_000.0
        decoder_duration_ms = (decoder_done_ns - worker_start_ns) / 1_000_000.0

        for decoded in decoded_messages:
            transaction_decision = self._observe_transaction(decoded, job.event)
            self._export_message(
                job=job,
                decoded=decoded,
                queue_delay_ms=queue_delay_ms,
                decoder_duration_ms=decoder_duration_ms,
                transaction_decision=transaction_decision,
            )

    def _decode(self, event: ForwardedDatagram) -> list[Any]:
        if self.decoder is None:
            return [self._raw_message(event.direction)]

        try:
            decoded_messages = self.decoder.decode_datagram(event.payload, event.direction)
        except Exception as exc:
            logging.exception("UDP protocol decoder raised an exception")
            return [self._decode_exception(event.direction, str(exc))]

        if decoded_messages:
            return list(decoded_messages)
        return [self._decode_exception(event.direction, "decoder returned no messages")]

    def _export_message(
        self,
        job: TraceJob,
        decoded: Any,
        queue_delay_ms: float,
        decoder_duration_ms: float,
        transaction_decision: Optional[Any] = None,
    ) -> None:
        event = job.event
        span_name = f"{self.protocol_name.upper()} {event.direction} {decoded.message_name}"
        parent_context = getattr(transaction_decision, "parent_context", None)
        if parent_context is None:
            span = self.tracer.start_span(span_name, start_time=event.recv_time_ns)
        else:
            span = self.tracer.start_span(
                span_name,
                context=parent_context,
                start_time=event.recv_time_ns,
            )
        try:
            span.set_attribute("network.protocol.name", self.protocol_name)
            span.set_attribute("network.transport", "udp")
            span.set_attribute(f"{self.protocol_name}.direction", event.direction)
            span.set_attribute(f"{self.protocol_name}.pdu.type", decoded.pdu_type)
            span.set_attribute(f"{self.protocol_name}.procedure.name", decoded.procedure_name)
            span.set_attribute(f"{self.protocol_name}.message.name", decoded.message_name)
            span.set_attribute(
                f"{self.protocol_name}.payload.size",
                self._message_size(decoded, event.payload_size),
            )
            span.set_attribute(f"{self.protocol_name}.datagram.size", event.payload_size)
            span.set_attribute("proxy.forward.duration_ms", event.forward_duration_ms)
            span.set_attribute("tracing.queue_delay_ms", queue_delay_ms)
            span.set_attribute("tracing.dropped_events", self.dropped)

            if self.decoder is not None:
                span.set_attribute("decoder.queue_delay_ms", queue_delay_ms)
                span.set_attribute("decoder.duration_ms", decoder_duration_ms)
                span.set_attribute("decoder.dropped_events", self.dropped)

            if decoded.procedure_code is not None:
                span.set_attribute(f"{self.protocol_name}.procedure.code", decoded.procedure_code)

            for key, value in event.udp.items():
                span.set_attribute(f"udp.{key}", value)

            for key, value in decoded.fields.items():
                if isinstance(value, (bool, int, float, str)):
                    span.set_attribute(key, value)
                else:
                    span.set_attribute(key, repr(value))

            if transaction_decision is not None:
                for key, value in transaction_decision.attributes.items():
                    span.set_attribute(key, value)

            if decoded.decode_error:
                span.set_attribute("decoder.error", decoded.decode_error)
        finally:
            end_time = max(event.send_done_time_ns, event.recv_time_ns + 1)
            span.end(end_time=end_time)
            self._finish_transaction(transaction_decision, end_time)

    def _observe_transaction(self, decoded: Any, event: ForwardedDatagram) -> Optional[Any]:
        if self.transaction_correlator is None:
            return None

        try:
            return self.transaction_correlator.observe(
                decoded,
                event,
                self._message_payload(decoded, event.payload),
            )
        except Exception:
            logging.exception("UDP transaction correlator failed to observe message")
            return None

    def _finish_transaction(
        self,
        transaction_decision: Optional[Any],
        end_time_ns: int,
    ) -> None:
        if self.transaction_correlator is None:
            return

        try:
            self.transaction_correlator.finish(transaction_decision, end_time_ns)
        except Exception:
            logging.exception("UDP transaction correlator failed to finish message")

    def _expire_transaction_contexts(self) -> None:
        if self.transaction_correlator is None:
            return

        try:
            self.transaction_correlator.expire()
        except Exception:
            logging.exception("UDP transaction correlator failed to expire state")

    def _message_payload(self, decoded: Any, payload: bytes) -> bytes:
        fields = getattr(decoded, "fields", {})
        offset = fields.get(f"{self.protocol_name}.message.offset")
        size = fields.get(f"{self.protocol_name}.message.size")
        if (
            isinstance(offset, int)
            and isinstance(size, int)
            and offset >= 0
            and size > 0
            and offset + size <= len(payload)
        ):
            return payload[offset : offset + size]
        return payload

    def _raw_message(self, direction: str) -> Any:
        return SimpleNamespace(
            protocol=self.protocol_name,
            direction=direction,
            pdu_type="raw_datagram",
            procedure_code=None,
            procedure_name="raw_datagram",
            message_name="raw_datagram",
            fields={
                "decoder.strategy": "raw",
                f"{self.protocol_name}.decode.enabled": False,
            },
            decode_error=None,
        )

    def _decode_exception(self, direction: str, error: str) -> Any:
        return SimpleNamespace(
            protocol=self.protocol_name,
            direction=direction,
            pdu_type="decode_exception",
            procedure_code=None,
            procedure_name="decode_exception",
            message_name="decode_exception",
            fields={
                "decoder.strategy": "exception",
                f"{self.protocol_name}.decode.enabled": True,
            },
            decode_error=error,
        )

    def _message_size(self, decoded: Any, datagram_size: int) -> int:
        value = decoded.fields.get(f"{self.protocol_name}.message.size")
        if isinstance(value, int) and value > 0:
            return value
        return datagram_size


class AsyncRawTraceWorker(AsyncDatagramTraceWorker):
    """Compatibility wrapper for callers that intentionally export raw UDP spans."""

    def __init__(self, service_name: str, protocol_name: str, queue_size: int) -> None:
        super().__init__(
            service_name=service_name,
            protocol_name=protocol_name,
            queue_size=queue_size,
            decoder=None,
        )
