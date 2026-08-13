#!/usr/bin/env python3
import logging
import os
import pathlib
import sys
from dataclasses import dataclass


SRC_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from proxies.udp.async_trace_worker import AsyncRawTraceWorker  # noqa: E402
from proxies.udp.relay import UdpRelay, UdpRelayConfig  # noqa: E402


PFCP_PORT = 8805


@dataclass
class Config:
    upf_host: str
    upf_port: int
    smf_host: str
    smf_port: int
    listen_host: str
    listen_port: int
    service_name: str
    log_hex_bytes: int
    trace_queue_size: int
    max_datagram_bytes: int
    dns_refresh_seconds: float


def load_config() -> Config:
    return Config(
        upf_host=os.getenv("UPF_HOST", "oai-spgwu-tiny"),
        upf_port=int(os.getenv("UPF_PORT", str(PFCP_PORT))),
        smf_host=os.getenv("SMF_HOST", "oai-smf"),
        smf_port=int(os.getenv("SMF_PORT", str(PFCP_PORT))),
        listen_host=os.getenv("LISTEN_HOST", "0.0.0.0"),
        listen_port=int(os.getenv("LISTEN_PORT", str(PFCP_PORT))),
        service_name=os.getenv("OTEL_SERVICE_NAME", "pfcp-udp-proxy"),
        log_hex_bytes=int(os.getenv("LOG_HEX_BYTES", "0")),
        trace_queue_size=int(os.getenv("TRACE_QUEUE_SIZE", "10000")),
        max_datagram_bytes=int(os.getenv("PFCP_MAX_DATAGRAM_BYTES", "65535")),
        dns_refresh_seconds=float(os.getenv("PFCP_DNS_REFRESH_SECONDS", "5")),
    )


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def run_proxy() -> None:
    configure_logging()
    cfg = load_config()
    worker = AsyncRawTraceWorker(
        service_name=cfg.service_name,
        protocol_name="pfcp",
        queue_size=cfg.trace_queue_size,
    )
    worker.start()

    relay = UdpRelay(
        cfg=UdpRelayConfig(
            upstream_host=cfg.upf_host,
            upstream_port=cfg.upf_port,
            downstream_host=cfg.smf_host,
            downstream_port=cfg.smf_port,
            listen_host=cfg.listen_host,
            listen_port=cfg.listen_port,
            max_datagram_bytes=cfg.max_datagram_bytes,
            dns_refresh_seconds=cfg.dns_refresh_seconds,
            log_hex_bytes=cfg.log_hex_bytes,
            downstream_to_upstream_direction="smf_to_upf",
            upstream_to_downstream_direction="upf_to_smf",
        ),
        on_forwarded=worker.submit,
    )
    relay.run()


if __name__ == "__main__":
    run_proxy()
