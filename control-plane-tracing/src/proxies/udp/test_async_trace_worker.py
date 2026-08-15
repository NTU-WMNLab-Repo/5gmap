import unittest
from unittest.mock import patch

from protocols.decoded_message import DecodedMessage
from proxies.udp.async_trace_worker import AsyncDatagramTraceWorker, TraceJob
from proxies.udp.relay import ForwardedDatagram


class FakeSpan:
    def __init__(self, name: str, start_time: int) -> None:
        self.name = name
        self.start_time = start_time
        self.attributes = {}
        self.end_time = None

    def set_attribute(self, key, value) -> None:
        self.attributes[key] = value

    def end(self, end_time: int) -> None:
        self.end_time = end_time


class FakeTracer:
    def __init__(self) -> None:
        self.spans = []

    def start_span(self, name: str, start_time: int) -> FakeSpan:
        span = FakeSpan(name, start_time)
        self.spans.append(span)
        return span


class BundledPfcpDecoder:
    def decode_datagram(self, _payload: bytes, direction: str):
        return [
            DecodedMessage(
                protocol="pfcp",
                direction=direction,
                pdu_type="request",
                procedure_code=50,
                procedure_name="SessionEstablishment",
                message_name="SessionEstablishmentRequest",
                fields={
                    "pfcp.message.size": 16,
                    "pfcp.message.index": 0,
                    "pfcp.datagram.message.count": 2,
                },
            ),
            DecodedMessage(
                protocol="pfcp",
                direction=direction,
                pdu_type="response",
                procedure_code=51,
                procedure_name="SessionEstablishment",
                message_name="SessionEstablishmentResponse",
                fields={
                    "pfcp.message.size": 16,
                    "pfcp.message.index": 1,
                    "pfcp.datagram.message.count": 2,
                },
            ),
        ]


class AsyncDatagramTraceWorkerTest(unittest.TestCase):
    @patch("proxies.udp.async_trace_worker.configure_tracer")
    def test_exports_one_span_per_decoded_pfcp_message(self, configure_tracer) -> None:
        tracer = FakeTracer()
        configure_tracer.return_value = tracer
        worker = AsyncDatagramTraceWorker(
            service_name="pfcp-test",
            protocol_name="pfcp",
            queue_size=4,
            decoder=BundledPfcpDecoder(),
        )
        event = ForwardedDatagram(
            direction="smf_to_upf",
            payload=b"x" * 32,
            payload_size=32,
            recv_time_ns=1_000_000,
            send_done_time_ns=1_000_100,
            forward_duration_ns=100,
            udp={"source.address": "10.0.0.1", "source.port": 8805},
        )

        worker._export(TraceJob(event=event, enqueue_monotonic_ns=1))

        self.assertEqual(
            [span.name for span in tracer.spans],
            [
                "PFCP smf_to_upf SessionEstablishmentRequest",
                "PFCP smf_to_upf SessionEstablishmentResponse",
            ],
        )
        self.assertEqual(
            [span.attributes["pfcp.message.index"] for span in tracer.spans],
            [0, 1],
        )
        self.assertTrue(
            all(span.attributes["pfcp.payload.size"] == 16 for span in tracer.spans)
        )
        self.assertTrue(
            all(span.attributes["pfcp.datagram.size"] == 32 for span in tracer.spans)
        )
        self.assertTrue(all(span.start_time == event.recv_time_ns for span in tracer.spans))
        self.assertTrue(all(span.end_time == event.send_done_time_ns for span in tracer.spans))


if __name__ == "__main__":
    unittest.main()
