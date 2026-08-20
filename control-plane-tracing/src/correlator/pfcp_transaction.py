# pyright: reportMissingImports=false
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

from protocols.decoded_message import DecodedMessage


ScalarAttribute = bool | int | float | str
Endpoint = tuple[str, int]
PeerPair = tuple[Endpoint, Endpoint]


# TS 29.244 Table 7.3-1. Version Not Supported Response has no request pair.
PFCP_REQUEST_TO_RESPONSE: dict[int, int] = {
    1: 2,
    3: 4,
    5: 6,
    7: 8,
    9: 10,
    12: 13,
    14: 15,
    16: 17,
    50: 51,
    52: 53,
    54: 55,
    56: 57,
}
PFCP_RESPONSE_TO_REQUEST = {
    response_type: request_type
    for request_type, response_type in PFCP_REQUEST_TO_RESPONSE.items()
}
PFCP_ASSOCIATION_SETUP_REQUEST = 5


@dataclass(frozen=True)
class PfcpTraceIdentity:
    trace_id: str
    span_id: str


@dataclass(frozen=True)
class PfcpTransactionKey:
    peer_pair: PeerPair
    association_epoch: int
    request_source: Endpoint
    request_destination: Endpoint
    request_type: int
    sequence_number: int


@dataclass
class PfcpTransaction:
    transaction_id: str
    key: PfcpTransactionKey
    procedure_name: str
    request_name: str
    request_time_ns: int
    created_monotonic_ns: int
    deadline_monotonic_ns: int
    request_fingerprint: bytes
    trace_identity: PfcpTraceIdentity
    attempts: int = 1
    response_fingerprint: Optional[bytes] = None


@dataclass
class ClosedPfcpTransaction:
    transaction: PfcpTransaction
    state: str
    close_reason: str
    expires_monotonic_ns: int


@dataclass
class PfcpTransactionDecision:
    attributes: dict[str, ScalarAttribute]
    parent_context: Optional[Any] = None
    transaction: Optional[PfcpTransaction] = None
    completion_state: Optional[str] = None
    completion_reason: Optional[str] = None
    response_fingerprint: Optional[bytes] = None


class PfcpTransactionTraceEmitter:
    """Export immediate transaction roots and terminal summaries.

    The root is ended immediately so children never point at an unexported
    parent. A summary span records the request-to-response or timeout duration.
    """

    def __init__(self, service_name: str) -> None:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))
        else:
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        self._tracer = provider.get_tracer(service_name)

    def start(self, transaction: PfcpTransaction) -> PfcpTraceIdentity:
        span = self._tracer.start_span(
            f"PFCP {transaction.procedure_name} transaction",
            start_time=transaction.request_time_ns,
        )
        span.set_attribute("pfcp.transaction.root", True)
        span.set_attribute("pfcp.transaction.id", transaction.transaction_id)
        span.set_attribute("pfcp.transaction.state", "opened")
        span.set_attribute("pfcp.transaction.request.name", transaction.request_name)
        span.set_attribute("pfcp.transaction.request.type", transaction.key.request_type)
        span.set_attribute("pfcp.transaction.sequence_number", transaction.key.sequence_number)
        span.set_attribute("pfcp.transaction.association_epoch", transaction.key.association_epoch)
        context = span.get_span_context()
        identity = PfcpTraceIdentity(
            trace_id=f"{context.trace_id:032x}",
            span_id=f"{context.span_id:016x}",
        )
        span.end(end_time=transaction.request_time_ns + 1)
        return identity

    def finish(
        self,
        transaction: PfcpTransaction,
        state: str,
        close_reason: str,
        end_time_ns: int,
    ) -> None:
        span = self._tracer.start_span(
            f"PFCP {transaction.procedure_name} transaction summary",
            context=self.parent_context(transaction.trace_identity),
            start_time=end_time_ns,
        )
        span.set_attribute("pfcp.transaction.summary", True)
        span.set_attribute("pfcp.transaction.id", transaction.transaction_id)
        span.set_attribute("pfcp.transaction.state", state)
        span.set_attribute("pfcp.transaction.close_reason", close_reason)
        span.set_attribute("pfcp.transaction.request.name", transaction.request_name)
        span.set_attribute("pfcp.transaction.request.type", transaction.key.request_type)
        span.set_attribute("pfcp.transaction.sequence_number", transaction.key.sequence_number)
        span.set_attribute("pfcp.transaction.association_epoch", transaction.key.association_epoch)
        span.set_attribute("pfcp.transaction.attempts", transaction.attempts)
        span.set_attribute("pfcp.transaction.started_unix_ns", transaction.request_time_ns)
        span.set_attribute("pfcp.transaction.ended_unix_ns", end_time_ns)
        span.set_attribute(
            "pfcp.transaction.observed_duration_ms",
            max(0, end_time_ns - transaction.request_time_ns) / 1_000_000.0,
        )
        span.end(end_time=end_time_ns + 1)

    @staticmethod
    def parent_context(identity: PfcpTraceIdentity) -> Any:
        from opentelemetry.trace import (
            NonRecordingSpan,
            SpanContext,
            TraceFlags,
            TraceState,
            set_span_in_context,
        )

        root = SpanContext(
            trace_id=int(identity.trace_id, 16),
            span_id=int(identity.span_id, 16),
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
            trace_state=TraceState(),
        )
        return set_span_in_context(NonRecordingSpan(root))


class PfcpTransactionCorrelator:
    """Keep PFCP request, retransmission, and response spans in one trace."""

    def __init__(
        self,
        service_name: str,
        timeout_ms: int,
        closed_retention_ms: int,
        max_contexts: int,
        emitter: Optional[Any] = None,
    ) -> None:
        self.timeout_ns = max(1, timeout_ms) * 1_000_000
        self.closed_retention_ns = max(0, closed_retention_ms) * 1_000_000
        self.max_contexts = max(1, max_contexts)
        self.emitter = emitter or PfcpTransactionTraceEmitter(service_name)
        self._active: dict[PfcpTransactionKey, PfcpTransaction] = {}
        self._closed: dict[PfcpTransactionKey, ClosedPfcpTransaction] = {}
        self._association_epochs: dict[PeerPair, int] = {}
        self._next_transaction_number = 1

    def observe(
        self,
        decoded: DecodedMessage,
        event: Any,
        message_payload: bytes,
        now_monotonic_ns: Optional[int] = None,
    ) -> PfcpTransactionDecision:
        if now_monotonic_ns is None:
            now_monotonic_ns = time.monotonic_ns()
        self.expire(now_monotonic_ns)

        if decoded.decode_error or decoded.procedure_code is None:
            return self._not_applicable("decode_error")

        endpoints = self._endpoints(event)
        sequence_number = decoded.fields.get("pfcp.sequence_number")
        if endpoints is None or not isinstance(sequence_number, int):
            return self._not_applicable("missing_peer_or_sequence")

        source, destination = endpoints
        message_type = decoded.procedure_code
        fingerprint = hashlib.sha256(message_payload).digest()

        if decoded.pdu_type == "request" and message_type in PFCP_REQUEST_TO_RESPONSE:
            return self._observe_request(
                decoded=decoded,
                event=event,
                source=source,
                destination=destination,
                fingerprint=fingerprint,
                now_monotonic_ns=now_monotonic_ns,
            )

        if decoded.pdu_type == "response" and message_type in PFCP_RESPONSE_TO_REQUEST:
            return self._observe_response(
                decoded=decoded,
                source=source,
                destination=destination,
                fingerprint=fingerprint,
            )

        return self._not_applicable("unsupported_message_type")

    def finish(
        self,
        decision: Optional[PfcpTransactionDecision],
        end_time_ns: int,
        now_monotonic_ns: Optional[int] = None,
    ) -> None:
        if (
            decision is None
            or decision.transaction is None
            or decision.completion_state is None
            or decision.completion_reason is None
        ):
            return

        transaction = decision.transaction
        if self._active.get(transaction.key) is not transaction:
            return
        transaction.response_fingerprint = decision.response_fingerprint
        self._close_transaction(
            transaction=transaction,
            state=decision.completion_state,
            close_reason=decision.completion_reason,
            end_time_ns=end_time_ns,
            now_monotonic_ns=(
                time.monotonic_ns()
                if now_monotonic_ns is None
                else now_monotonic_ns
            ),
        )

    def expire(self, now_monotonic_ns: Optional[int] = None) -> None:
        if now_monotonic_ns is None:
            now_monotonic_ns = time.monotonic_ns()
        for transaction in list(self._active.values()):
            if transaction.deadline_monotonic_ns > now_monotonic_ns:
                continue
            self._close_transaction(
                transaction=transaction,
                state="timed_out",
                close_reason="response_timeout",
                end_time_ns=transaction.request_time_ns + self.timeout_ns,
                now_monotonic_ns=now_monotonic_ns,
            )

        for key, closed in list(self._closed.items()):
            if closed.expires_monotonic_ns <= now_monotonic_ns:
                del self._closed[key]

    def _observe_request(
        self,
        decoded: DecodedMessage,
        event: Any,
        source: Endpoint,
        destination: Endpoint,
        fingerprint: bytes,
        now_monotonic_ns: int,
    ) -> PfcpTransactionDecision:
        message_type = decoded.procedure_code
        assert message_type is not None
        sequence_number = decoded.fields["pfcp.sequence_number"]
        assert isinstance(sequence_number, int)
        peer_pair = self._peer_pair(source, destination)

        key = self._key(
            peer_pair=peer_pair,
            request_source=source,
            request_destination=destination,
            request_type=message_type,
            sequence_number=sequence_number,
        )

        if message_type == PFCP_ASSOCIATION_SETUP_REQUEST:
            existing = self._existing_request(key, fingerprint, now_monotonic_ns)
            if existing is not None:
                return existing
            self._advance_association_epoch(
                peer_pair=peer_pair,
                end_time_ns=event.recv_time_ns,
                now_monotonic_ns=now_monotonic_ns,
            )
            key = self._key(
                peer_pair=peer_pair,
                request_source=source,
                request_destination=destination,
                request_type=message_type,
                sequence_number=sequence_number,
            )

        return self._start_or_reuse_request(
            decoded=decoded,
            event=event,
            key=key,
            fingerprint=fingerprint,
            now_monotonic_ns=now_monotonic_ns,
        )

    def _observe_response(
        self,
        decoded: DecodedMessage,
        source: Endpoint,
        destination: Endpoint,
        fingerprint: bytes,
    ) -> PfcpTransactionDecision:
        response_type = decoded.procedure_code
        assert response_type is not None
        request_type = PFCP_RESPONSE_TO_REQUEST[response_type]
        sequence_number = decoded.fields["pfcp.sequence_number"]
        assert isinstance(sequence_number, int)
        peer_pair = self._peer_pair(source, destination)
        key = self._key(
            peer_pair=peer_pair,
            request_source=destination,
            request_destination=source,
            request_type=request_type,
            sequence_number=sequence_number,
        )

        transaction = self._active.get(key)
        if transaction is not None:
            return PfcpTransactionDecision(
                attributes=self._attributes(
                    transaction,
                    state="matched",
                    role="response",
                    response_matched=True,
                ),
                parent_context=self.emitter.parent_context(transaction.trace_identity),
                transaction=transaction,
                completion_state="matched",
                completion_reason="response",
                response_fingerprint=fingerprint,
            )

        closed = self._closed.get(key)
        if closed is not None:
            return PfcpTransactionDecision(
                attributes=self._attributes(
                    closed.transaction,
                    state="late_response",
                    role="response",
                    response_matched=True,
                    late_duplicate=closed.transaction.response_fingerprint == fingerprint,
                    closed_state=closed.state,
                ),
                parent_context=self.emitter.parent_context(closed.transaction.trace_identity),
                transaction=closed.transaction,
            )

        return PfcpTransactionDecision(
            attributes={
                "pfcp.transaction.enabled": True,
                "pfcp.transaction.state": "orphan_response",
                "pfcp.transaction.role": "response",
                "pfcp.transaction.response.matched": False,
            }
        )

    def _existing_request(
        self,
        key: PfcpTransactionKey,
        fingerprint: bytes,
        now_monotonic_ns: int,
    ) -> Optional[PfcpTransactionDecision]:
        transaction = self._active.get(key)
        if transaction is not None and transaction.request_fingerprint == fingerprint:
            transaction.attempts += 1
            transaction.deadline_monotonic_ns = now_monotonic_ns + self.timeout_ns
            return PfcpTransactionDecision(
                attributes=self._attributes(
                    transaction,
                    state="retransmission",
                    role="request",
                    retransmission=True,
                ),
                parent_context=self.emitter.parent_context(transaction.trace_identity),
                transaction=transaction,
            )

        closed = self._closed.get(key)
        if closed is not None and closed.transaction.request_fingerprint == fingerprint:
            return PfcpTransactionDecision(
                attributes=self._attributes(
                    closed.transaction,
                    state="late_duplicate_request",
                    role="request",
                    late_duplicate=True,
                    closed_state=closed.state,
                ),
                parent_context=self.emitter.parent_context(closed.transaction.trace_identity),
                transaction=closed.transaction,
            )
        return None

    def _start_or_reuse_request(
        self,
        decoded: DecodedMessage,
        event: Any,
        key: PfcpTransactionKey,
        fingerprint: bytes,
        now_monotonic_ns: int,
    ) -> PfcpTransactionDecision:
        existing = self._existing_request(key, fingerprint, now_monotonic_ns)
        if existing is not None:
            return existing

        sequence_reuse = False
        active = self._active.get(key)
        if active is not None:
            sequence_reuse = True
            self._close_transaction(
                transaction=active,
                state="forced_closed",
                close_reason="sequence_reuse_conflict",
                end_time_ns=event.recv_time_ns,
                now_monotonic_ns=now_monotonic_ns,
            )
        if key in self._closed:
            sequence_reuse = True
            del self._closed[key]

        self._enforce_capacity(event.recv_time_ns, now_monotonic_ns)
        transaction = PfcpTransaction(
            transaction_id=self._new_transaction_id(key),
            key=key,
            procedure_name=decoded.procedure_name,
            request_name=decoded.message_name,
            request_time_ns=event.recv_time_ns,
            created_monotonic_ns=now_monotonic_ns,
            deadline_monotonic_ns=now_monotonic_ns + self.timeout_ns,
            request_fingerprint=fingerprint,
            trace_identity=PfcpTraceIdentity(trace_id="", span_id=""),
        )
        transaction.trace_identity = self.emitter.start(transaction)
        self._active[key] = transaction
        return PfcpTransactionDecision(
            attributes=self._attributes(
                transaction,
                state="opened",
                role="request",
                sequence_reuse=sequence_reuse,
            ),
            parent_context=self.emitter.parent_context(transaction.trace_identity),
            transaction=transaction,
        )

    def _advance_association_epoch(
        self,
        peer_pair: PeerPair,
        end_time_ns: int,
        now_monotonic_ns: int,
    ) -> None:
        for transaction in list(self._active.values()):
            if transaction.key.peer_pair != peer_pair:
                continue
            self._close_transaction(
                transaction=transaction,
                state="forced_closed",
                close_reason="association_reset",
                end_time_ns=end_time_ns,
                now_monotonic_ns=now_monotonic_ns,
            )
        self._association_epochs[peer_pair] = self._association_epochs.get(peer_pair, 0) + 1

    def _enforce_capacity(self, end_time_ns: int, now_monotonic_ns: int) -> None:
        while len(self._active) >= self.max_contexts:
            oldest = min(
                self._active.values(),
                key=lambda transaction: transaction.created_monotonic_ns,
            )
            self._close_transaction(
                transaction=oldest,
                state="forced_closed",
                close_reason="capacity_evicted",
                end_time_ns=end_time_ns,
                now_monotonic_ns=now_monotonic_ns,
            )

    def _enforce_closed_capacity(self) -> None:
        while len(self._closed) > self.max_contexts:
            oldest_key = min(
                self._closed,
                key=lambda key: self._closed[key].transaction.created_monotonic_ns,
            )
            del self._closed[oldest_key]

    def _close_transaction(
        self,
        transaction: PfcpTransaction,
        state: str,
        close_reason: str,
        end_time_ns: int,
        now_monotonic_ns: int,
    ) -> None:
        if self._active.get(transaction.key) is not transaction:
            return
        del self._active[transaction.key]
        self.emitter.finish(
            transaction=transaction,
            state=state,
            close_reason=close_reason,
            end_time_ns=max(end_time_ns, transaction.request_time_ns + 1),
        )
        if self.closed_retention_ns <= 0:
            return
        self._closed[transaction.key] = ClosedPfcpTransaction(
            transaction=transaction,
            state=state,
            close_reason=close_reason,
            expires_monotonic_ns=now_monotonic_ns + self.closed_retention_ns,
        )
        self._enforce_closed_capacity()

    def _key(
        self,
        peer_pair: PeerPair,
        request_source: Endpoint,
        request_destination: Endpoint,
        request_type: int,
        sequence_number: int,
    ) -> PfcpTransactionKey:
        return PfcpTransactionKey(
            peer_pair=peer_pair,
            association_epoch=self._association_epochs.get(peer_pair, 0),
            request_source=request_source,
            request_destination=request_destination,
            request_type=request_type,
            sequence_number=sequence_number,
        )

    def _new_transaction_id(self, key: PfcpTransactionKey) -> str:
        number = self._next_transaction_number
        self._next_transaction_number += 1
        return (
            f"pfcp-{key.association_epoch}-{key.request_type}-"
            f"{key.sequence_number:06x}-{number}"
        )

    @staticmethod
    def _endpoints(event: Any) -> Optional[tuple[Endpoint, Endpoint]]:
        try:
            source = (str(event.udp["source.address"]), int(event.udp["source.port"]))
            destination = (
                str(event.udp["destination.address"]),
                int(event.udp["destination.port"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        return source, destination

    @staticmethod
    def _peer_pair(source: Endpoint, destination: Endpoint) -> PeerPair:
        first, second = sorted((source, destination))
        return first, second

    @staticmethod
    def _attributes(
        transaction: PfcpTransaction,
        state: str,
        role: str,
        retransmission: bool = False,
        response_matched: Optional[bool] = None,
        late_duplicate: bool = False,
        sequence_reuse: bool = False,
        closed_state: Optional[str] = None,
    ) -> dict[str, ScalarAttribute]:
        attributes: dict[str, ScalarAttribute] = {
            "pfcp.transaction.enabled": True,
            "pfcp.transaction.id": transaction.transaction_id,
            "pfcp.transaction.state": state,
            "pfcp.transaction.role": role,
            "pfcp.transaction.association_epoch": transaction.key.association_epoch,
            "pfcp.transaction.attempt": transaction.attempts,
            "pfcp.transaction.retransmission": retransmission,
        }
        if response_matched is not None:
            attributes["pfcp.transaction.response.matched"] = response_matched
        if late_duplicate:
            attributes["pfcp.transaction.late_duplicate"] = True
        if sequence_reuse:
            attributes["pfcp.transaction.sequence_reuse"] = True
        if closed_state is not None:
            attributes["pfcp.transaction.closed_state"] = closed_state
        return attributes

    @staticmethod
    def _not_applicable(reason: str) -> PfcpTransactionDecision:
        return PfcpTransactionDecision(
            attributes={
                "pfcp.transaction.enabled": True,
                "pfcp.transaction.state": "not_applicable",
                "pfcp.transaction.reason": reason,
            }
        )
