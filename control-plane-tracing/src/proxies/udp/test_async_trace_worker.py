import unittest
from types import SimpleNamespace
from unittest.mock import patch

from protocols.decoded_message import DecodedMessage
from proxies.udp.async_trace_worker import AsyncDatagramTraceWorker, TraceJob
from proxies.udp.relay import ForwardedDatagram


class FakeSpan:
    def __init__(self, name: str, start_time: int, context=None) -> None:
        self.name = name
        self.start_time = start_time
        self.context = context
        self.attributes = {}
        self.end_time = None

    def set_attribute(self, key, value) -> None:
        self.attributes[key] = value

    def end(self, end_time: int) -> None:
        self.end_time = end_time


class FakeTracer:
    def __init__(self) -> None:
        self.spans = []

    def start_span(self, name: str, start_time: int, context=None) -> FakeSpan:
        span = FakeSpan(name, start_time, context)
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
                    "pfcp.message.offset": 0,
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
                    "pfcp.message.offset": 16,
                    "pfcp.message.index": 1,
                    "pfcp.datagram.message.count": 2,
                },
            ),
        ]


class FakeTransactionCorrelator:
    def __init__(self) -> None:
        self.observed = []
        self.finished = []
        self.expired = 0

    def observe(self, decoded, event, message_payload):
        self.observed.append((decoded, event, message_payload))
        return SimpleNamespace(
            attributes={"pfcp.transaction.id": f"tx-{len(self.observed)}"},
            parent_context=("pfcp-transaction-root",),
        )

    def finish(self, decision, end_time_ns) -> None:
        self.finished.append((decision, end_time_ns))

    def expire(self) -> None:
        self.expired += 1


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

    @patch("proxies.udp.async_trace_worker.configure_tracer")
    def test_transaction_decision_parents_each_message_span(self, configure_tracer) -> None:
        tracer = FakeTracer()
        configure_tracer.return_value = tracer
        correlator = FakeTransactionCorrelator()
        worker = AsyncDatagramTraceWorker(
            service_name="pfcp-test",
            protocol_name="pfcp",
            queue_size=4,
            decoder=BundledPfcpDecoder(),
            transaction_correlator=correlator,
        )
        event = ForwardedDatagram(
            direction="smf_to_upf",
            payload=b"a" * 16 + b"b" * 16,
            payload_size=32,
            recv_time_ns=1_000_000,
            send_done_time_ns=1_000_100,
            forward_duration_ns=100,
            udp={
                "source.address": "10.0.0.1",
                "source.port": 8805,
                "destination.address": "10.0.0.2",
                "destination.port": 8805,
            },
        )

        worker._export(TraceJob(event=event, enqueue_monotonic_ns=1))

        self.assertEqual([payload for _, _, payload in correlator.observed], [b"a" * 16, b"b" * 16])
        self.assertEqual(len(correlator.finished), 2)
        self.assertTrue(all(span.context == ("pfcp-transaction-root",) for span in tracer.spans))
        self.assertEqual(
            [span.attributes["pfcp.transaction.id"] for span in tracer.spans],
            ["tx-1", "tx-2"],
        )


if __name__ == "__main__":
    unittest.main()
