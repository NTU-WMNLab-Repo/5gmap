import socket
import unittest
from unittest.mock import patch

from proxies.udp.relay import (
    UdpRelay,
    UdpRelayConfig,
    is_upstream_source,
    resolve_udp_addresses,
)


class UdpRelayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = UdpRelayConfig(
            upstream_host="upf",
            upstream_port=8805,
            downstream_host="smf",
            downstream_port=8805,
            listen_host="0.0.0.0",
            listen_port=8805,
            max_datagram_bytes=65535,
            dns_refresh_seconds=5,
            log_hex_bytes=0,
        )

    @patch("proxies.udp.relay.socket.getaddrinfo")
    def test_resolve_udp_addresses_returns_ipv4_endpoints(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("10.42.1.50", 8805)),
            (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("10.42.1.51", 8805)),
        ]

        self.assertEqual(
            resolve_udp_addresses("upf", 8805),
            {("10.42.1.50", 8805), ("10.42.1.51", 8805)},
        )

    def test_upstream_classification_requires_resolved_peer_and_port(self) -> None:
        upstream_addresses = {("10.42.1.50", 8805)}

        self.assertTrue(is_upstream_source(("10.42.1.50", 8805), upstream_addresses, 8805))
        self.assertFalse(is_upstream_source(("10.42.1.50", 9999), upstream_addresses, 8805))
        self.assertFalse(is_upstream_source(("10.42.1.60", 8805), upstream_addresses, 8805))

    def test_observed_downstream_overrides_configured_fallback(self) -> None:
        relay = UdpRelay(self.config, lambda _event: None)
        relay._configured_downstream_addresses = {("10.42.1.20", 8805)}

        self.assertEqual(relay._select_downstream_address(), ("10.42.1.20", 8805))

        relay._remember_downstream(("10.42.1.21", 8805))
        self.assertEqual(relay._select_downstream_address(), ("10.42.1.21", 8805))

    def test_route_uses_upstream_and_downstream_directions(self) -> None:
        relay = UdpRelay(self.config, lambda _event: None)
        relay._upstream_addresses = {("10.42.1.50", 8805)}
        relay._configured_downstream_addresses = {("10.42.1.20", 8805)}

        self.assertEqual(
            relay._route(("10.42.1.50", 8805)),
            ("upf_to_smf", ("10.42.1.20", 8805)),
        )
        self.assertEqual(
            relay._route(("10.42.1.21", 8805)),
            ("smf_to_upf", ("10.42.1.50", 8805)),
        )

    def test_forward_preserves_datagram_and_proxy_source_port(self) -> None:
        received_events = []
        relay = UdpRelay(self.config, received_events.append)
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        relay_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        receiver.settimeout(1)

        try:
            receiver.bind(("127.0.0.1", 0))
            relay_socket.bind(("127.0.0.1", 0))
            target = receiver.getsockname()
            proxy_port = relay_socket.getsockname()[1]
            payload = b"\x20\x01\x00\x04"

            relay._forward(
                sock=relay_socket,
                data=payload,
                source=("127.0.0.1", 43000),
                target=target,
                direction="smf_to_upf",
                recv_time_ns=1_000_000,
                forward_start_ns=1,
            )

            received_payload, received_from = receiver.recvfrom(64)
            self.assertEqual(received_payload, payload)
            self.assertEqual(received_from[1], proxy_port)
            self.assertEqual(len(received_events), 1)
            self.assertEqual(received_events[0].direction, "smf_to_upf")
            self.assertEqual(received_events[0].payload_size, len(payload))
        finally:
            receiver.close()
            relay_socket.close()


if __name__ == "__main__":
    unittest.main()
