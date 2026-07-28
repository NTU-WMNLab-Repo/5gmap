#!/usr/bin/env python3
import logging
import os
import select
import socket
import time
from dataclasses import dataclass
from typing import Optional

import sctp
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter


F1AP_PPID = 62


@dataclass
class Config:
    cu_host: str
    cu_port: int
    listen_host: str
    listen_port: int
    sctp_ppid: int
    service_name: str
    log_hex_bytes: int


@dataclass
class Peer:
    name: str
    sock: object
    addr: Optional[tuple] = None


def load_config() -> Config:
    return Config(
        cu_host=os.getenv("CU_HOST", "oai-cu"),
        cu_port=int(os.getenv("CU_PORT", "38472")),
        listen_host=os.getenv("LISTEN_HOST", "0.0.0.0"),
        listen_port=int(os.getenv("LISTEN_PORT", "38472")),
        sctp_ppid=int(os.getenv("SCTP_PPID", str(F1AP_PPID))),
        service_name=os.getenv("OTEL_SERVICE_NAME", "f1ap-sctp-proxy"),
        log_hex_bytes=int(os.getenv("LOG_HEX_BYTES", "32")),
    )


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def configure_tracer(service_name: str) -> trace.Tracer:
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    else:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


def normalize_ppid(ppid: int) -> int:
    if ppid > 0xFFFF:
        return ppid
    return socket.htonl(ppid)


def ppid_from_pinfo(pinfo: object, default_ppid: int) -> int:
    ppid = getattr(pinfo, "ppid", None)
    if ppid is None or ppid == 0:
        return normalize_ppid(default_ppid)
    return normalize_ppid(ppid)


def classify_f1ap(data: bytes) -> str:
    payload = data.hex()

    # These are coarse observed prefixes from OAI F1-C experiments. They are
    # useful for early tracing but should be replaced by ASN.1 PER decoding.
    known_prefixes = {
        "0001": "f1_setup_request_or_initiating_message",
        "4001": "f1_setup_response_or_successful_outcome",
        "0005": "ue_context_setup_request_or_initiating_message",
        "4005": "ue_context_setup_response_or_successful_outcome",
    }

    for prefix, name in known_prefixes.items():
        if payload.startswith(prefix):
            return name

    if not payload:
        return "empty"

    return "unknown_f1ap_message"


def payload_preview(data: bytes, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    preview = data[:max_bytes].hex()
    if len(data) > max_bytes:
        return f"{preview}..."
    return preview


def recv_sctp(peer: Peer):
    from_addr, flags, data, pinfo = peer.sock.sctp_recv(65535)
    return from_addr, flags, data, pinfo


def send_sctp(peer: Peer, data: bytes, ppid: int) -> None:
    peer.sock.sctp_send(data, ppid=ppid)


def trace_message(
    tracer: trace.Tracer,
    direction: str,
    data: bytes,
    pinfo: object,
    duration_ms: float,
    cfg: Config,
) -> None:
    message_type = classify_f1ap(data)
    ppid = getattr(pinfo, "ppid", None)
    stream = getattr(pinfo, "stream", None)
    ssn = getattr(pinfo, "ssn", None)
    tsn = getattr(pinfo, "tsn", None)

    with tracer.start_as_current_span(f"F1AP {direction} {message_type}") as span:
        span.set_attribute("network.protocol.name", "f1ap")
        span.set_attribute("network.transport", "sctp")
        span.set_attribute("f1ap.direction", direction)
        span.set_attribute("f1ap.message.type", message_type)
        span.set_attribute("f1ap.payload.size", len(data))
        span.set_attribute("sctp.ppid", ppid if ppid is not None else cfg.sctp_ppid)
        span.set_attribute("proxy.forward.duration_ms", duration_ms)

        if stream is not None:
            span.set_attribute("sctp.stream", stream)
        if ssn is not None:
            span.set_attribute("sctp.ssn", ssn)
        if tsn is not None:
            span.set_attribute("sctp.tsn", tsn)


def forward_message(
    tracer: trace.Tracer,
    source: Peer,
    target: Peer,
    direction: str,
    cfg: Config,
) -> bool:
    _, _, data, pinfo = recv_sctp(source)
    if not data:
        logging.warning("%s disconnected", source.name)
        return False

    ppid = ppid_from_pinfo(pinfo, cfg.sctp_ppid)
    start = time.monotonic()
    send_sctp(target, data, ppid)
    duration_ms = (time.monotonic() - start) * 1000.0

    message_type = classify_f1ap(data)
    logging.info(
        "%s %s bytes=%d ppid=%s preview=%s",
        direction,
        message_type,
        len(data),
        getattr(pinfo, "ppid", cfg.sctp_ppid),
        payload_preview(data, cfg.log_hex_bytes),
    )

    trace_message(tracer, direction, data, pinfo, duration_ms, cfg)
    return True


def connect_cu(cfg: Config) -> Peer:
    cu_sock = sctp.sctpsocket_tcp(socket.AF_INET)
    logging.info("Connecting to CU %s:%d", cfg.cu_host, cfg.cu_port)
    cu_sock.connect((cfg.cu_host, cfg.cu_port))
    return Peer(name="CU", sock=cu_sock, addr=(cfg.cu_host, cfg.cu_port))


def listen_for_du(cfg: Config) -> object:
    listen_sock = sctp.sctpsocket_tcp(socket.AF_INET)
    listen_sock.bind((cfg.listen_host, cfg.listen_port))
    listen_sock.listen(5)
    logging.info("Listening for DU on %s:%d", cfg.listen_host, cfg.listen_port)
    return listen_sock


def run_proxy() -> None:
    configure_logging()
    cfg = load_config()
    tracer = configure_tracer(cfg.service_name)

    listen_sock = listen_for_du(cfg)
    cu = connect_cu(cfg)
    du: Optional[Peer] = None

    while True:
        readers = [listen_sock, cu.sock]
        if du is not None:
            readers.append(du.sock)

        readable, _, _ = select.select(readers, [], [])

        for sock in readable:
            if sock is listen_sock:
                client, addr = listen_sock.accept()
                if du is not None:
                    logging.warning("Rejecting additional DU connection from %s", addr)
                    client.close()
                    continue
                du = Peer(name="DU", sock=client, addr=addr)
                logging.info("DU connected from %s", addr)
                continue

            if du is not None and sock is du.sock:
                if not forward_message(tracer, du, cu, "du_to_cu", cfg):
                    du.sock.close()
                    du = None
                continue

            if sock is cu.sock:
                if du is None:
                    _, _, data, _ = recv_sctp(cu)
                    logging.warning("Dropping CU message with no connected DU, bytes=%d", len(data))
                    continue
                if not forward_message(tracer, cu, du, "cu_to_du", cfg):
                    raise RuntimeError("CU disconnected")


if __name__ == "__main__":
    run_proxy()
