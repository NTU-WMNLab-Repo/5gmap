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

from correlator.f1ap import F1apCorrelator  # noqa: E402
from protocols.f1ap.decoder import F1apDecoder  # noqa: E402
from proxies.sctp.async_trace_worker import AsyncTraceWorker  # noqa: E402
from proxies.sctp.relay import SctpRelay, SctpRelayConfig  # noqa: E402


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
    cu_connect_retries: int
    cu_connect_retry_seconds: float
    trace_queue_size: int


def load_config() -> Config:
    return Config(
        cu_host=os.getenv("CU_HOST", "oai-cu"),
        cu_port=int(os.getenv("CU_PORT", "38472")),
        listen_host=os.getenv("LISTEN_HOST", "0.0.0.0"),
        listen_port=int(os.getenv("LISTEN_PORT", "38472")),
        sctp_ppid=int(os.getenv("SCTP_PPID", str(F1AP_PPID))),
        service_name=os.getenv("OTEL_SERVICE_NAME", "f1ap-sctp-proxy"),
        log_hex_bytes=int(os.getenv("LOG_HEX_BYTES", "32")),
        cu_connect_retries=int(os.getenv("CU_CONNECT_RETRIES", "60")),
        cu_connect_retry_seconds=float(os.getenv("CU_CONNECT_RETRY_SECONDS", "2")),
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
    decoder = F1apDecoder()
    correlator = F1apCorrelator.from_env()

    worker = AsyncTraceWorker(
        service_name=cfg.service_name,
        protocol_name="f1ap",
        decoder=decoder,
        queue_size=cfg.trace_queue_size,
        correlator=correlator,
    )
    worker.start()

    relay = SctpRelay(
        cfg=SctpRelayConfig(
            upstream_host=cfg.cu_host,
            upstream_port=cfg.cu_port,
            listen_host=cfg.listen_host,
            listen_port=cfg.listen_port,
            sctp_ppid=cfg.sctp_ppid,
            connect_retries=cfg.cu_connect_retries,
            connect_retry_seconds=cfg.cu_connect_retry_seconds,
            log_hex_bytes=cfg.log_hex_bytes,
        ),
        on_forwarded=worker.submit,
    )
    relay.run()


if __name__ == "__main__":
    run_proxy()
