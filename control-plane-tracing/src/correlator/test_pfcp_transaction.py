import unittest
from types import SimpleNamespace

from correlator.pfcp_transaction import (
    PfcpTraceIdentity,
    PfcpTransactionCorrelator,
)
from protocols.decoded_message import DecodedMessage


class FakeEmitter:
    def __init__(self) -> None:
        self.started = []
        self.finished = []

    def start(self, transaction):
        identity = PfcpTraceIdentity(
            trace_id=f"{len(self.started) + 1:032x}",
            span_id=f"{len(self.started) + 1:016x}",
        )
        self.started.append((transaction, identity))
        return identity

    @staticmethod
    def parent_context(identity):
        return ("pfcp-transaction", identity.trace_id, identity.span_id)

    def finish(self, transaction, state, close_reason, end_time_ns) -> None:
        self.finished.append((transaction, state, close_reason, end_time_ns))


class PfcpTransactionCorrelatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.emitter = FakeEmitter()
        self.correlator = PfcpTransactionCorrelator(
            service_name="pfcp-test",
            timeout_ms=30_000,
            closed_retention_ms=5_000,
            max_contexts=4,
            emitter=self.emitter,
        )

    def test_matching_response_uses_the_request_trace(self) -> None:
        request = self.correlator.observe(
            self._message(50, "request"),
            self._event("10.0.0.10", "10.0.0.20", 1_000),
            b"session-establishment-request",
            now_monotonic_ns=10,
        )
        response = self.correlator.observe(
            self._message(51, "response"),
            self._event("10.0.0.20", "10.0.0.10", 2_000),
            b"session-establishment-response",
            now_monotonic_ns=20,
        )

        self.assertEqual(request.attributes["pfcp.transaction.state"], "opened")
        self.assertEqual(response.attributes["pfcp.transaction.state"], "matched")
        self.assertTrue(response.attributes["pfcp.transaction.response.matched"])
        self.assertEqual(request.parent_context, response.parent_context)

        self.correlator.finish(response, end_time_ns=2_100, now_monotonic_ns=30)

        self.assertEqual(len(self.emitter.started), 1)
        self.assertEqual(len(self.emitter.finished), 1)
        _, state, close_reason, end_time_ns = self.emitter.finished[0]
        self.assertEqual(state, "matched")
        self.assertEqual(close_reason, "response")
        self.assertEqual(end_time_ns, 2_100)

    def test_retransmission_reuses_trace_and_resets_idle_timeout(self) -> None:
        first = self.correlator.observe(
            self._message(1, "request"),
            self._event("10.0.0.10", "10.0.0.20", 1_000),
            b"heartbeat-request",
            now_monotonic_ns=10,
        )
        retransmission = self.correlator.observe(
            self._message(1, "request"),
            self._event("10.0.0.10", "10.0.0.20", 2_000),
            b"heartbeat-request",
            now_monotonic_ns=20_000_000,
        )

        self.assertEqual(retransmission.attributes["pfcp.transaction.state"], "retransmission")
        self.assertTrue(retransmission.attributes["pfcp.transaction.retransmission"])
        self.assertEqual(retransmission.attributes["pfcp.transaction.attempt"], 2)
        self.assertEqual(first.parent_context, retransmission.parent_context)

        self.correlator.expire(now_monotonic_ns=30_000_000_000)
        self.assertEqual(self.emitter.finished, [])

        self.correlator.expire(now_monotonic_ns=30_020_000_001)
        self.assertEqual(len(self.emitter.finished), 1)
        _, state, close_reason, _ = self.emitter.finished[0]
        self.assertEqual(state, "timed_out")
        self.assertEqual(close_reason, "response_timeout")

    def test_closed_tombstone_keeps_late_duplicates_in_trace(self) -> None:
        request = self.correlator.observe(
            self._message(50, "request"),
            self._event("10.0.0.10", "10.0.0.20", 1_000),
            b"request",
            now_monotonic_ns=10,
        )
        response = self.correlator.observe(
            self._message(51, "response"),
            self._event("10.0.0.20", "10.0.0.10", 2_000),
            b"response",
            now_monotonic_ns=20,
        )
        self.correlator.finish(response, end_time_ns=2_100, now_monotonic_ns=30)

        late_request = self.correlator.observe(
            self._message(50, "request"),
            self._event("10.0.0.10", "10.0.0.20", 3_000),
            b"request",
            now_monotonic_ns=40,
        )
        late_response = self.correlator.observe(
            self._message(51, "response"),
            self._event("10.0.0.20", "10.0.0.10", 4_000),
            b"response",
            now_monotonic_ns=50,
        )

        self.assertEqual(late_request.attributes["pfcp.transaction.state"], "late_duplicate_request")
        self.assertEqual(late_response.attributes["pfcp.transaction.state"], "late_response")
        self.assertTrue(late_request.attributes["pfcp.transaction.late_duplicate"])
        self.assertTrue(late_response.attributes["pfcp.transaction.late_duplicate"])
        self.assertEqual(request.parent_context, late_request.parent_context)
        self.assertEqual(request.parent_context, late_response.parent_context)
        self.assertEqual(len(self.emitter.finished), 1)

    def test_same_sequence_with_different_request_fingerprint_forces_close(self) -> None:
        first = self.correlator.observe(
            self._message(52, "request"),
            self._event("10.0.0.10", "10.0.0.20", 1_000),
            b"first-modification",
            now_monotonic_ns=10,
        )
        replacement = self.correlator.observe(
            self._message(52, "request"),
            self._event("10.0.0.10", "10.0.0.20", 2_000),
            b"different-modification",
            now_monotonic_ns=20,
        )

        self.assertTrue(replacement.attributes["pfcp.transaction.sequence_reuse"])
        self.assertNotEqual(first.parent_context, replacement.parent_context)
        self.assertEqual(len(self.emitter.finished), 1)
        _, state, close_reason, _ = self.emitter.finished[0]
        self.assertEqual(state, "forced_closed")
        self.assertEqual(close_reason, "sequence_reuse_conflict")

    def test_closed_tombstones_are_bounded_by_max_contexts(self) -> None:
        self.correlator = PfcpTransactionCorrelator(
            service_name="pfcp-test",
            timeout_ms=30_000,
            closed_retention_ms=5_000,
            max_contexts=1,
            emitter=self.emitter,
        )
        first_request = self.correlator.observe(
            self._message(1, "request", sequence_number=1),
            self._event("10.0.0.10", "10.0.0.20", 1_000),
            b"first-request",
            now_monotonic_ns=10,
        )
        first_response = self.correlator.observe(
            self._message(2, "response", sequence_number=1),
            self._event("10.0.0.20", "10.0.0.10", 2_000),
            b"first-response",
            now_monotonic_ns=20,
        )
        self.correlator.finish(first_response, end_time_ns=2_100, now_monotonic_ns=30)

        second_request = self.correlator.observe(
            self._message(1, "request", sequence_number=2),
            self._event("10.0.0.10", "10.0.0.20", 3_000),
            b"second-request",
            now_monotonic_ns=40,
        )
        second_response = self.correlator.observe(
            self._message(2, "response", sequence_number=2),
            self._event("10.0.0.20", "10.0.0.10", 4_000),
            b"second-response",
            now_monotonic_ns=50,
        )
        self.correlator.finish(second_response, end_time_ns=4_100, now_monotonic_ns=60)

        self.assertEqual(len(self.correlator._closed), 1)
        self.assertEqual(
            self.correlator.observe(
                self._message(2, "response", sequence_number=1),
                self._event("10.0.0.20", "10.0.0.10", 5_000),
                b"first-response",
                now_monotonic_ns=70,
            ).attributes["pfcp.transaction.state"],
            "orphan_response",
        )
        self.assertNotEqual(first_request.parent_context, second_request.parent_context)

    @staticmethod
    def _message(
        message_type: int,
        pdu_type: str,
        sequence_number: int = 0x10203,
    ) -> DecodedMessage:
        request = pdu_type == "request"
        procedure = {
            1: "Heartbeat",
            2: "Heartbeat",
            50: "SessionEstablishment",
            51: "SessionEstablishment",
            52: "SessionModification",
        }[message_type]
        suffix = "Request" if request else "Response"
        return DecodedMessage(
            protocol="pfcp",
            direction="smf_to_upf" if request else "upf_to_smf",
            pdu_type=pdu_type,
            procedure_code=message_type,
            procedure_name=procedure,
            message_name=f"{procedure}{suffix}",
            fields={"pfcp.sequence_number": sequence_number},
        )

    @staticmethod
    def _event(source: str, destination: str, recv_time_ns: int):
        return SimpleNamespace(
            recv_time_ns=recv_time_ns,
            udp={
                "source.address": source,
                "source.port": 8805,
                "destination.address": destination,
                "destination.port": 8805,
            },
        )


if __name__ == "__main__":
    unittest.main()
