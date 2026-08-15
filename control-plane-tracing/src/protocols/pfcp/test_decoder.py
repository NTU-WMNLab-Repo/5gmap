import unittest

from protocols.pfcp.decoder import PfcpDecoder


def node_message(message_type: int, sequence_number: int) -> bytes:
    return (
        bytes([0x20, message_type, 0x00, 0x04])
        + sequence_number.to_bytes(3, "big")
        + b"\x00"
    )


def session_message(
    message_type: int,
    sequence_number: int,
    seid: int,
    *,
    follow_on: bool = False,
) -> bytes:
    flags = 0x21 | (0x04 if follow_on else 0x00)
    return (
        bytes([flags, message_type, 0x00, 0x0C])
        + seid.to_bytes(8, "big")
        + sequence_number.to_bytes(3, "big")
        + b"\x00"
    )


class PfcpDecoderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.decoder = PfcpDecoder()

    def test_decodes_observed_node_related_header(self) -> None:
        decoded = self.decoder.decode_datagram(node_message(5, 0x010203), "smf_to_upf")

        self.assertEqual(len(decoded), 1)
        message = decoded[0]
        self.assertEqual(message.message_name, "AssociationSetupRequest")
        self.assertEqual(message.pdu_type, "request")
        self.assertEqual(message.procedure_code, 5)
        self.assertEqual(message.fields["pfcp.sequence_number"], 0x010203)
        self.assertFalse(message.fields["pfcp.s_flag"])
        self.assertEqual(message.fields["pfcp.message.size"], 8)
        self.assertEqual(message.fields["pfcp.decode.status"], "header_decoded")

    def test_allows_zero_seid_for_session_establishment(self) -> None:
        decoded = self.decoder.decode_datagram(session_message(50, 7, 0), "smf_to_upf")

        self.assertEqual(len(decoded), 1)
        message = decoded[0]
        self.assertEqual(message.message_name, "SessionEstablishmentRequest")
        self.assertTrue(message.fields["pfcp.s_flag"])
        self.assertEqual(message.fields["pfcp.seid"], "0x0000000000000000")
        self.assertTrue(message.fields["pfcp.seid.is_zero"])

    def test_expands_follow_on_messages(self) -> None:
        payload = (
            session_message(50, 41, 0, follow_on=True)
            + session_message(51, 41, 0x1234)
        )

        decoded = self.decoder.decode_datagram(payload, "smf_to_upf")

        self.assertEqual(
            [message.message_name for message in decoded],
            ["SessionEstablishmentRequest", "SessionEstablishmentResponse"],
        )
        self.assertEqual(
            [message.fields["pfcp.message.index"] for message in decoded],
            [0, 1],
        )
        self.assertTrue(all(message.fields["pfcp.datagram.bundled"] for message in decoded))
        self.assertTrue(
            all(message.fields["pfcp.datagram.message.count"] == 2 for message in decoded)
        )

    def test_rejects_declared_length_beyond_datagram(self) -> None:
        decoded = self.decoder.decode_datagram(b"\x20\x01\x00\x0c\x00\x00\x01\x00", "smf_to_upf")

        self.assertEqual(len(decoded), 1)
        self.assertEqual(decoded[0].message_name, "MalformedDatagram")
        self.assertEqual(decoded[0].fields["pfcp.decode.status"], "malformed")
        self.assertIn("declares", decoded[0].decode_error or "")

    def test_marks_missing_follow_on_message(self) -> None:
        decoded = self.decoder.decode_datagram(
            session_message(50, 7, 0, follow_on=True),
            "smf_to_upf",
        )

        self.assertEqual(len(decoded), 1)
        self.assertEqual(decoded[0].fields["pfcp.bundle.error"], "missing_follow_on")
        self.assertEqual(decoded[0].fields["pfcp.decode.status"], "malformed")


if __name__ == "__main__":
    unittest.main()
