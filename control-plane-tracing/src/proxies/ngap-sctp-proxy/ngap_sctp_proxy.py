#!/usr/bin/env python3
# pyright: reportMissingImports=false
import logging
import os
import pathlib
import sys
from dataclasses import dataclass


SRC_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from correlator.ngap import NgapCorrelator  # noqa: E402
from protocols.ngap.decoder import NgapDecoder  # noqa: E402
from proxies.sctp.async_trace_worker import AsyncTraceWorker  # noqa: E402
from proxies.sctp.relay import SctpRelay, SctpRelayConfig  # noqa: E402


NGAP_PPID = 60
NGAP_PORT = 38412


@dataclass
class Config:
    amf_host: str
    amf_port: int
    listen_host: str
    listen_port: int
    sctp_ppid: int
    service_name: str
    log_hex_bytes: int
    amf_connect_retries: int
    amf_connect_retry_seconds: float
    trace_queue_size: int


def load_config() -> Config:
    return Config(
        amf_host=os.getenv("AMF_HOST", "oai-amf"),
        amf_port=int(os.getenv("AMF_PORT", str(NGAP_PORT))),
        listen_host=os.getenv("LISTEN_HOST", "0.0.0.0"),
        listen_port=int(os.getenv("LISTEN_PORT", str(NGAP_PORT))),
        sctp_ppid=int(os.getenv("SCTP_PPID", str(NGAP_PPID))),
        service_name=os.getenv("OTEL_SERVICE_NAME", "ngap-sctp-proxy"),
        log_hex_bytes=int(os.getenv("LOG_HEX_BYTES", "32")),
        amf_connect_retries=int(os.getenv("AMF_CONNECT_RETRIES", "60")),
        amf_connect_retry_seconds=float(os.getenv("AMF_CONNECT_RETRY_SECONDS", "2")),
        trace_queue_size=int(os.getenv("TRACE_QUEUE_SIZE", "10000")),
    )


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def run_proxy() -> None:
    configure_logging()
    cfg = load_config()
    decoder = NgapDecoder()
    correlator = NgapCorrelator.from_env()

    worker = AsyncTraceWorker(
        service_name=cfg.service_name,
        protocol_name="ngap",
        decoder=decoder,
        queue_size=cfg.trace_queue_size,
        correlator=correlator,
    )
    worker.start()

    relay = SctpRelay(
        cfg=SctpRelayConfig(
            upstream_host=cfg.amf_host,
            upstream_port=cfg.amf_port,
            listen_host=cfg.listen_host,
            listen_port=cfg.listen_port,
            sctp_ppid=cfg.sctp_ppid,
            connect_retries=cfg.amf_connect_retries,
            connect_retry_seconds=cfg.amf_connect_retry_seconds,
            log_hex_bytes=cfg.log_hex_bytes,
            downstream_to_upstream_direction="cu_to_amf",
            upstream_to_downstream_direction="amf_to_cu",
        ),
        on_forwarded=worker.submit,
    )
    relay.run()


if __name__ == "__main__":
    run_proxy()
