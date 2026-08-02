import logging
import select
import socket
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import sctp


@dataclass
class Peer:
    name: str
    sock: object
    addr: Optional[tuple] = None


@dataclass
class SctpRelayConfig:
    upstream_host: str
    upstream_port: int
    listen_host: str
    listen_port: int
    sctp_ppid: int
    connect_retries: int
    connect_retry_seconds: float
    log_hex_bytes: int
    downstream_to_upstream_direction: str = "du_to_cu"
    upstream_to_downstream_direction: str = "cu_to_du"


@dataclass
class ForwardedPacket:
    direction: str
    payload: bytes
    recv_time_ns: int
    send_done_time_ns: int
    forward_duration_ns: int
    sctp: dict[str, int] = field(default_factory=dict)

    @property
    def forward_duration_ms(self) -> float:
        return self.forward_duration_ns / 1_000_000.0


def normalize_ppid(ppid: int) -> int:
    if ppid > 0xFFFF:
        return ppid
    return socket.htonl(ppid)


def ppid_from_pinfo(pinfo: object, default_ppid: int) -> int:
    ppid = getattr(pinfo, "ppid", None)
    if ppid is None or ppid == 0:
        return normalize_ppid(default_ppid)
    return normalize_ppid(ppid)


def sctp_metadata(pinfo: object, default_ppid: int) -> dict[str, int]:
    values = {"ppid": getattr(pinfo, "ppid", default_ppid)}
    for key in ("stream", "ssn", "tsn", "context"):
        value = getattr(pinfo, key, None)
        if value is not None:
            values[key] = value
    return values


def payload_preview(data: bytes, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    preview = data[:max_bytes].hex()
    if len(data) > max_bytes:
        return f"{preview}..."
    return preview


class SctpRelay:
    def __init__(
        self,
        cfg: SctpRelayConfig,
        on_forwarded: Callable[[ForwardedPacket], None],
    ) -> None:
        self.cfg = cfg
        self.on_forwarded = on_forwarded

    def run(self) -> None:
        listen_sock = self._listen()
        upstream = self._connect_upstream()
        downstream: Optional[Peer] = None

        while True:
            readers = [listen_sock, upstream.sock]
            if downstream is not None:
                readers.append(downstream.sock)

            readable, _, _ = select.select(readers, [], [])

            for sock in readable:
                if sock is listen_sock:
                    client, addr = listen_sock.accept()
                    if downstream is not None:
                        logging.warning("Rejecting additional downstream connection from %s", addr)
                        client.close()
                        continue
                    downstream = Peer(name="downstream", sock=client, addr=addr)
                    logging.info("Downstream connected from %s", addr)
                    continue

                if downstream is not None and sock is downstream.sock:
                    if not self._forward(
                        downstream,
                        upstream,
                        self.cfg.downstream_to_upstream_direction,
                    ):
                        downstream.sock.close()
                        downstream = None
                    continue

                if sock is upstream.sock:
                    if downstream is None:
                        _, _, data, _ = self._recv(upstream)
                        logging.warning(
                            "Dropping upstream message with no downstream, bytes=%d",
                            len(data),
                        )
                        continue
                    if not self._forward(
                        upstream,
                        downstream,
                        self.cfg.upstream_to_downstream_direction,
                    ):
                        raise RuntimeError("upstream disconnected")

    def _listen(self) -> object:
        listen_sock = sctp.sctpsocket_tcp(socket.AF_INET)
        listen_sock.bind((self.cfg.listen_host, self.cfg.listen_port))
        listen_sock.listen(5)
        logging.info("Listening for downstream on %s:%d", self.cfg.listen_host, self.cfg.listen_port)
        return listen_sock

    def _connect_upstream(self) -> Peer:
        last_error = None

        for attempt in range(1, self.cfg.connect_retries + 1):
            upstream_sock = sctp.sctpsocket_tcp(socket.AF_INET)
            logging.info(
                "Connecting to upstream %s:%d, attempt %d/%d",
                self.cfg.upstream_host,
                self.cfg.upstream_port,
                attempt,
                self.cfg.connect_retries,
            )
            try:
                upstream_sock.connect((self.cfg.upstream_host, self.cfg.upstream_port))
                return Peer(
                    name="upstream",
                    sock=upstream_sock,
                    addr=(self.cfg.upstream_host, self.cfg.upstream_port),
                )
            except Exception as exc:
                last_error = exc
                upstream_sock.close()
                time.sleep(self.cfg.connect_retry_seconds)

        raise RuntimeError(
            f"failed to connect to upstream "
            f"{self.cfg.upstream_host}:{self.cfg.upstream_port}: {last_error}"
        )

    @staticmethod
    def _recv(peer: Peer):
        return peer.sock.sctp_recv(65535)

    def _forward(self, source: Peer, target: Peer, direction: str) -> bool:
        _, _, data, pinfo = self._recv(source)
        if not data:
            logging.warning("%s disconnected", source.name)
            return False

        recv_time_ns = time.time_ns()
        forward_start_ns = time.monotonic_ns()
        ppid = ppid_from_pinfo(pinfo, self.cfg.sctp_ppid)
        target.sock.sctp_send(data, ppid=ppid)
        forward_duration_ns = time.monotonic_ns() - forward_start_ns
        send_done_time_ns = recv_time_ns + forward_duration_ns

        logging.info(
            "%s %s bytes=%d ppid=%s preview=%s",
            direction,
            "sctp_packet",
            len(data),
            getattr(pinfo, "ppid", self.cfg.sctp_ppid),
            payload_preview(data, self.cfg.log_hex_bytes),
        )

        self.on_forwarded(
            ForwardedPacket(
                direction=direction,
                payload=bytes(data),
                recv_time_ns=recv_time_ns,
                send_done_time_ns=send_done_time_ns,
                forward_duration_ns=forward_duration_ns,
                sctp=sctp_metadata(pinfo, self.cfg.sctp_ppid),
            )
        )
        return True
