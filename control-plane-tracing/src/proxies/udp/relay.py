from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


UdpAddress = tuple[str, int]


@dataclass
class UdpRelayConfig:
    upstream_host: str
    upstream_port: int
    downstream_host: Optional[str]
    downstream_port: int
    listen_host: str
    listen_port: int
    max_datagram_bytes: int
    dns_refresh_seconds: float
    log_hex_bytes: int
    downstream_to_upstream_direction: str = "smf_to_upf"
    upstream_to_downstream_direction: str = "upf_to_smf"


@dataclass
class ForwardedDatagram:
    direction: str
    payload_size: int
    recv_time_ns: int
    send_done_time_ns: int
    forward_duration_ns: int
    udp: dict[str, str | int] = field(default_factory=dict)

    @property
    def forward_duration_ms(self) -> float:
        return self.forward_duration_ns / 1_000_000.0


def resolve_udp_addresses(host: str, port: int) -> set[UdpAddress]:
    """Resolve IPv4 UDP endpoints for a Kubernetes service or direct host."""
    results = socket.getaddrinfo(
        host,
        port,
        family=socket.AF_INET,
        type=socket.SOCK_DGRAM,
    )
    return {(address[0], address[1]) for _, _, _, _, address in results}


def is_upstream_source(
    address: UdpAddress,
    upstream_addresses: set[UdpAddress],
    upstream_port: int,
) -> bool:
    return address[1] == upstream_port and address in upstream_addresses


def payload_preview(data: bytes, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    preview = data[:max_bytes].hex()
    if len(data) > max_bytes:
        return f"{preview}..."
    return preview


class UdpRelay:
    """Relay UDP datagrams between one configured downstream and upstream path.

    A single UDP socket stays bound to the public listen port. This makes the
    proxy the peer observed by both endpoints while preserving the original
    payload bytes. The current deployment has one SMF and one UPF per slice;
    packet-level transaction multiplexing is deliberately left to a future
    protocol-aware layer.
    """

    def __init__(
        self,
        cfg: UdpRelayConfig,
        on_forwarded: Callable[[ForwardedDatagram], None],
    ) -> None:
        self.cfg = cfg
        self.on_forwarded = on_forwarded
        self._upstream_addresses: set[UdpAddress] = set()
        self._configured_downstream_addresses: set[UdpAddress] = set()
        self._last_downstream_address: Optional[UdpAddress] = None
        self._last_dns_refresh_ns = 0

    def run(self) -> None:
        sock = self._bind()
        self._refresh_peer_addresses(force=True)

        try:
            while True:
                data, raw_source = sock.recvfrom(self.cfg.max_datagram_bytes)
                source = (raw_source[0], raw_source[1])
                recv_time_ns = time.time_ns()
                forward_start_ns = time.monotonic_ns()

                self._refresh_peer_addresses()
                direction, target = self._route(source)
                if target is None:
                    self._log_missing_target(direction, len(data))
                    continue

                self._forward(
                    sock=sock,
                    data=data,
                    source=source,
                    target=target,
                    direction=direction,
                    recv_time_ns=recv_time_ns,
                    forward_start_ns=forward_start_ns,
                )
        finally:
            sock.close()

    def _bind(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.cfg.listen_host, self.cfg.listen_port))
        logging.info("Listening for UDP datagrams on %s:%d", self.cfg.listen_host, self.cfg.listen_port)
        return sock

    def _refresh_peer_addresses(self, force: bool = False) -> None:
        now_ns = time.monotonic_ns()
        refresh_interval_ns = int(max(0.0, self.cfg.dns_refresh_seconds) * 1_000_000_000)
        if not force and refresh_interval_ns > 0 and now_ns - self._last_dns_refresh_ns < refresh_interval_ns:
            return

        self._last_dns_refresh_ns = now_ns
        self._upstream_addresses = self._resolve_or_keep_previous(
            label="upstream",
            host=self.cfg.upstream_host,
            port=self.cfg.upstream_port,
            previous=self._upstream_addresses,
        )

        if self.cfg.downstream_host:
            self._configured_downstream_addresses = self._resolve_or_keep_previous(
                label="configured downstream",
                host=self.cfg.downstream_host,
                port=self.cfg.downstream_port,
                previous=self._configured_downstream_addresses,
            )

    @staticmethod
    def _resolve_or_keep_previous(
        label: str,
        host: str,
        port: int,
        previous: set[UdpAddress],
    ) -> set[UdpAddress]:
        try:
            addresses = resolve_udp_addresses(host, port)
        except OSError as exc:
            logging.warning("Could not resolve %s UDP endpoint %s:%d: %s", label, host, port, exc)
            return previous

        if not addresses:
            logging.warning("No IPv4 UDP addresses found for %s endpoint %s:%d", label, host, port)
            return previous
        return addresses

    def _select_upstream_address(self) -> Optional[UdpAddress]:
        if not self._upstream_addresses:
            return None
        return sorted(self._upstream_addresses)[0]

    def _select_downstream_address(self) -> Optional[UdpAddress]:
        if self._last_downstream_address is not None:
            return self._last_downstream_address
        if not self._configured_downstream_addresses:
            return None
        return sorted(self._configured_downstream_addresses)[0]

    def _remember_downstream(self, address: UdpAddress) -> None:
        if self._last_downstream_address == address:
            return
        if self._last_downstream_address is not None:
            logging.warning(
                "Replacing downstream UDP peer %s:%d with %s:%d",
                self._last_downstream_address[0],
                self._last_downstream_address[1],
                address[0],
                address[1],
            )
        else:
            logging.info("Downstream UDP peer observed at %s:%d", address[0], address[1])
        self._last_downstream_address = address

    def _route(self, source: UdpAddress) -> tuple[str, Optional[UdpAddress]]:
        if is_upstream_source(source, self._upstream_addresses, self.cfg.upstream_port):
            return self.cfg.upstream_to_downstream_direction, self._select_downstream_address()

        self._remember_downstream(source)
        return self.cfg.downstream_to_upstream_direction, self._select_upstream_address()

    def _log_missing_target(self, direction: str, payload_size: int) -> None:
        if direction == self.cfg.upstream_to_downstream_direction:
            logging.warning(
                "Dropping upstream UDP datagram with no downstream peer, bytes=%d",
                payload_size,
            )
            return

        logging.warning(
            "Dropping downstream UDP datagram because upstream %s:%d is unresolved, bytes=%d",
            self.cfg.upstream_host,
            self.cfg.upstream_port,
            payload_size,
        )

    def _forward(
        self,
        sock: socket.socket,
        data: bytes,
        source: UdpAddress,
        target: UdpAddress,
        direction: str,
        recv_time_ns: int,
        forward_start_ns: int,
    ) -> None:
        try:
            sock.sendto(data, target)
        except OSError as exc:
            logging.warning(
                "Failed to forward UDP datagram %s from %s:%d to %s:%d: %s",
                direction,
                source[0],
                source[1],
                target[0],
                target[1],
                exc,
            )
            return

        forward_duration_ns = time.monotonic_ns() - forward_start_ns
        send_done_time_ns = recv_time_ns + forward_duration_ns
        logging.info(
            "%s udp_datagram bytes=%d from=%s:%d to=%s:%d preview=%s",
            direction,
            len(data),
            source[0],
            source[1],
            target[0],
            target[1],
            payload_preview(data, self.cfg.log_hex_bytes),
        )

        event = ForwardedDatagram(
            direction=direction,
            payload_size=len(data),
            recv_time_ns=recv_time_ns,
            send_done_time_ns=send_done_time_ns,
            forward_duration_ns=forward_duration_ns,
            udp={
                "source.address": source[0],
                "source.port": source[1],
                "destination.address": target[0],
                "destination.port": target[1],
            },
        )
        try:
            self.on_forwarded(event)
        except Exception:
            logging.exception("Trace callback failed after UDP forwarding")
