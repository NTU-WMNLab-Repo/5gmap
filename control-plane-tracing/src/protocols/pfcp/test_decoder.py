import unittest

from protocols.pfcp.decoder import PfcpDecoder
from protocols.pfcp.ie_decoder import PfcpIeDecoder


def ie(ie_type: int, value: bytes) -> bytes:
    return ie_type.to_bytes(2, "big") + len(value).to_bytes(2, "big") + value


def dns_labels(value: str) -> bytes:
    return b"".join(bytes([len(label)]) + label.encode("ascii") for label in value.split("."))


def node_message(message_type: int, sequence_number: int, ies: bytes = b"") -> bytes:
    message_length = 4 + len(ies)
    return (
        bytes([0x20, message_type])
        + message_length.to_bytes(2, "big")
        + sequence_number.to_bytes(3, "big")
        + b"\x00"
        + ies
    )


def session_message(
    message_type: int,
    sequence_number: int,
    seid: int,
    *,
    follow_on: bool = False,
    ies: bytes = b"",
) -> bytes:
    flags = 0x21 | (0x04 if follow_on else 0x00)
    message_length = 12 + len(ies)
    return (
        bytes([flags, message_type])
        + message_length.to_bytes(2, "big")
        + seid.to_bytes(8, "big")
        + sequence_number.to_bytes(3, "big")
        + b"\x00"
        + ies
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
        self.assertEqual(message.fields["pfcp.ie.decode.status"], "no_ies")

    def test_allows_zero_seid_for_session_establishment(self) -> None:
        decoded = self.decoder.decode_datagram(session_message(50, 7, 0), "smf_to_upf")

        self.assertEqual(len(decoded), 1)
        message = decoded[0]
        self.assertEqual(message.message_name, "SessionEstablishmentRequest")
        self.assertTrue(message.fields["pfcp.s_flag"])
        self.assertEqual(message.fields["pfcp.seid"], "0x0000000000000000")
        self.assertTrue(message.fields["pfcp.seid.is_zero"])

    def test_decodes_session_request_correlation_ies(self) -> None:
        cp_f_seid = ie(
            57,
            b"\x02"
            + 0x0102030405060708.to_bytes(8, "big")
            + bytes([10, 42, 2, 20]),
        )
        pdi = ie(
            2,
            ie(20, b"\x00")
            + ie(
                21,
                b"\x01"
                + 0x11223344.to_bytes(4, "big")
                + bytes([10, 42, 2, 30]),
            )
            + ie(22, dns_labels("internet"))
            + ie(93, b"\x02" + bytes([12, 1, 0, 2])),
        )
        create_pdr = ie(
            1,
            ie(56, (7).to_bytes(2, "big"))
            + ie(108, (9).to_bytes(4, "big"))
            + pdi,
        )
        forwarding_parameters = ie(
            4,
            ie(42, b"\x00")
            + ie(
                84,
                b"\x01\x00"
                + 0x55667788.to_bytes(4, "big")
                + bytes([10, 42, 1, 55]),
            ),
        )
        create_far = ie(
            3,
            ie(108, (9).to_bytes(4, "big")) + forwarding_parameters,
        )
        ies = (
            ie(60, b"\x02" + dns_labels("oai-smf10.svc"))
            + cp_f_seid
            + create_pdr
            + create_far
            + ie(257, bytes([1, 0x01, 0x02, 0x03]))
        )

        message = self.decoder.decode_datagram(
            session_message(50, 11, 0, ies=ies), "smf_to_upf"
        )[0]

        self.assertEqual(message.fields["pfcp.ie.decode.status"], "decoded")
        self.assertEqual(message.fields["pfcp.node_id.value"], "oai-smf10.svc")
        self.assertEqual(
            message.fields["pfcp.session.cp_f_seid.seid"],
            "0x0102030405060708",
        )
        self.assertEqual(message.fields["pfcp.session.cp_f_seid.ipv4"], "10.42.2.20")
        self.assertEqual(message.fields["pfcp.pdr.0.pdr_id"], 7)
        self.assertEqual(message.fields["pfcp.pdr.0.far_id"], 9)
        self.assertEqual(message.fields["pfcp.pdr.0.path"], "CreatePDR")
        self.assertEqual(message.fields["pfcp.pdr.0.source_interface.name"], "Access")
        self.assertEqual(message.fields["pfcp.pdr.0.f_teid.0.teid"], 0x11223344)
        self.assertEqual(message.fields["pfcp.pdr.0.f_teid.0.ipv4"], "10.42.2.30")
        self.assertEqual(
            message.fields["pfcp.pdr.0.f_teid.0.path"], "CreatePDR/PDI/F-TEID"
        )
        self.assertEqual(
            message.fields["pfcp.pdr.0.f_teid.0.endpoint_role"],
            "upf_n3_ingress",
        )
        self.assertEqual(
            message.fields["pfcp.pdr.0.network_instance.0.value"], "internet"
        )
        self.assertEqual(message.fields["pfcp.pdr.0.ue_ip.0.ipv4"], "12.1.0.2")
        self.assertEqual(message.fields["pfcp.far.0.far_id"], 9)
        self.assertEqual(message.fields["pfcp.far.0.path"], "CreateFAR")
        self.assertEqual(
            message.fields["pfcp.far.0.destination_interface.name"], "Access"
        )
        self.assertEqual(
            message.fields["pfcp.far.0.outer_header_creation.0.teid"],
            0x55667788,
        )
        self.assertEqual(
            message.fields["pfcp.far.0.outer_header_creation.0.ipv4"],
            "10.42.1.55",
        )
        self.assertEqual(
            message.fields["pfcp.far.0.outer_header_creation.0.endpoint_role"],
            "ran_n3_egress",
        )
        self.assertEqual(message.fields["pfcp.s_nssai.0.sst"], 1)
        self.assertEqual(message.fields["pfcp.s_nssai.0.sd"], "010203")

    def test_decodes_session_response_cause_up_f_seid_and_created_pdr(self) -> None:
        ies = (
            ie(19, b"\x01")
            + ie(
                57,
                b"\x02"
                + 0x1111222233334444.to_bytes(8, "big")
                + bytes([10, 42, 2, 40]),
            )
            + ie(
                8,
                ie(56, (7).to_bytes(2, "big"))
                + ie(
                    21,
                    b"\x01"
                    + 0xAABBCCDD.to_bytes(4, "big")
                    + bytes([10, 42, 2, 40]),
                ),
            )
        )

        message = self.decoder.decode_datagram(
            session_message(51, 11, 0x0102030405060708, ies=ies),
            "upf_to_smf",
        )[0]

        self.assertEqual(message.fields["pfcp.cause.code"], 1)
        self.assertTrue(message.fields["pfcp.cause.success"])
        self.assertEqual(
            message.fields["pfcp.session.up_f_seid.seid"],
            "0x1111222233334444",
        )
        self.assertEqual(message.fields["pfcp.pdr.0.operation"], "created")
        self.assertEqual(message.fields["pfcp.pdr.0.f_teid.0.teid"], 0xAABBCCDD)
        self.assertEqual(
            message.fields["pfcp.pdr.0.f_teid.0.endpoint_role"], "upf_local"
        )

    def test_ie_error_does_not_invalidate_header_or_transaction_fields(self) -> None:
        malformed_ie = b"\x00\x39\x00\x0d\x02\x00"

        message = self.decoder.decode_datagram(
            session_message(50, 19, 0, ies=malformed_ie), "smf_to_upf"
        )[0]

        self.assertIsNone(message.decode_error)
        self.assertEqual(message.fields["pfcp.decode.status"], "header_decoded")
        self.assertEqual(message.fields["pfcp.ie.decode.status"], "malformed")
        self.assertEqual(message.fields["pfcp.sequence_number"], 19)
        self.assertIn("declares", message.fields["pfcp.ie.decode.error"])

    def test_bounds_ie_walk_without_invalidating_header(self) -> None:
        decoder = PfcpDecoder(PfcpIeDecoder(max_ie_count=1))
        recovery_timestamp = ie(96, b"\x00\x00\x00\x01")

        message = decoder.decode_datagram(
            node_message(5, 20, recovery_timestamp + recovery_timestamp),
            "smf_to_upf",
        )[0]

        self.assertIsNone(message.decode_error)
        self.assertEqual(message.fields["pfcp.ie.count"], 1)
        self.assertEqual(message.fields["pfcp.ie.decode.status"], "partial")
        self.assertIn("exceeds limit", message.fields["pfcp.ie.decode.error"])

    def test_decodes_choose_flags_without_consuming_absent_addresses(self) -> None:
        create_pdr = ie(
            1,
            ie(56, (3).to_bytes(2, "big"))
            + ie(
                2,
                ie(20, b"\x00")
                + ie(21, b"\x0d\x07")
                + ie(93, b"\x10"),
            ),
        )

        message = self.decoder.decode_datagram(
            session_message(50, 21, 0, ies=create_pdr), "smf_to_upf"
        )[0]

        self.assertTrue(message.fields["pfcp.pdr.0.f_teid.0.choose"])
        self.assertEqual(message.fields["pfcp.pdr.0.f_teid.0.choose_id"], 7)
        self.assertTrue(message.fields["pfcp.pdr.0.f_teid.0.v4_flag"])
        self.assertFalse(message.fields["pfcp.pdr.0.f_teid.0.ipv4_present"])
        self.assertTrue(message.fields["pfcp.pdr.0.ue_ip.0.choose_ipv4"])
        self.assertFalse(message.fields["pfcp.pdr.0.ue_ip.0.ipv4_present"])

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
