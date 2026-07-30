# pyright: reportMissingImports=false
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from proxies.sctp.relay import ForwardedPacket


@dataclass
class TraceJob:
    event: ForwardedPacket
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


class AsyncTraceWorker:
    def __init__(
        self,
        service_name: str,
        protocol_name: str,
        decoder: Any,
        queue_size: int,
        correlator: Any = None,
    ) -> None:
        self.protocol_name = protocol_name
        self.decoder = decoder
        self.correlator = correlator
        self.queue: queue.Queue[TraceJob] = queue.Queue(maxsize=queue_size)
        self.tracer = configure_tracer(service_name)
        self.dropped = 0
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
            job = self.queue.get()
            try:
                self._process(job)
            except Exception:
                logging.exception("Trace worker failed to process event")
            finally:
                self.queue.task_done()

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

        span_name = f"{decoded.protocol.upper()} {job.event.direction} {decoded.message_name}"
        span = self.tracer.start_span(span_name, start_time=job.event.recv_time_ns)
        try:
            span.set_attribute("network.protocol.name", decoded.protocol)
            span.set_attribute("network.transport", "sctp")
            span.set_attribute(f"{decoded.protocol}.direction", job.event.direction)
            span.set_attribute(f"{decoded.protocol}.pdu.type", decoded.pdu_type)
            span.set_attribute(f"{decoded.protocol}.procedure.name", decoded.procedure_name)
            span.set_attribute(f"{decoded.protocol}.message.name", decoded.message_name)
            span.set_attribute(f"{decoded.protocol}.payload.size", len(job.event.payload))
            span.set_attribute("proxy.forward.duration_ms", job.event.forward_duration_ms)
            span.set_attribute("decoder.queue_delay_ms", queue_delay_ms)
            span.set_attribute("decoder.duration_ms", decoder_duration_ms)
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

            for key, value in correlation_fields.items():
                span.set_attribute(key, value)

            if decoded.decode_error:
                span.set_attribute("decoder.error", decoded.decode_error)
        finally:
            end_time = max(job.event.send_done_time_ns, job.event.recv_time_ns + 1)
            span.end(end_time=end_time)

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
