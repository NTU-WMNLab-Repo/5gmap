# pyright: reportMissingImports=false
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass

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


class AsyncRawTraceWorker:
    """Emit raw UDP spans after forwarding without protocol decoding."""

    def __init__(self, service_name: str, protocol_name: str, queue_size: int) -> None:
        self.protocol_name = protocol_name
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
            job = self.queue.get()
            try:
                self._export(job)
            except Exception:
                logging.exception("Raw UDP trace worker failed to export event")
            finally:
                self.queue.task_done()

    def _export(self, job: TraceJob) -> None:
        event = job.event
        queue_delay_ms = (time.monotonic_ns() - job.enqueue_monotonic_ns) / 1_000_000.0
        span = self.tracer.start_span(
            f"{self.protocol_name.upper()} {event.direction} raw_datagram",
            start_time=event.recv_time_ns,
        )
        try:
            span.set_attribute("network.protocol.name", self.protocol_name)
            span.set_attribute("network.transport", "udp")
            span.set_attribute(f"{self.protocol_name}.direction", event.direction)
            span.set_attribute(f"{self.protocol_name}.message.name", "raw_datagram")
            span.set_attribute(f"{self.protocol_name}.payload.size", event.payload_size)
            span.set_attribute(f"{self.protocol_name}.decode.enabled", False)
            span.set_attribute("proxy.forward.duration_ms", event.forward_duration_ms)
            span.set_attribute("tracing.queue_delay_ms", queue_delay_ms)
            span.set_attribute("tracing.dropped_events", self.dropped)

            for key, value in event.udp.items():
                span.set_attribute(f"udp.{key}", value)
        finally:
            end_time = max(event.send_done_time_ns, event.recv_time_ns + 1)
            span.end(end_time=end_time)
