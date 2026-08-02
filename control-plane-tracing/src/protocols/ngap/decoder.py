from protocols.decoded_message import DecodedMessage


class NgapDecoder:
    def decode(self, payload: bytes, direction: str) -> DecodedMessage:
        pdu_marker = payload[0] & 0xC0 if payload else None
        return DecodedMessage(
            protocol="ngap",
            direction=direction,
            pdu_type="opaque",
            procedure_code=None,
            procedure_name="opaque_ngap",
            message_name="opaque_ngap_sctp_message",
            fields={
                "decoder.strategy": "opaque",
                "ngap.decode.status": "not_decoded",
                "ngap.pdu.marker": pdu_marker,
            },
            decode_error=None,
        )
