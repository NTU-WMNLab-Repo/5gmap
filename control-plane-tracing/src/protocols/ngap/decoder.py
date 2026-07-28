from protocols.f1ap.decoder import DecodedMessage


class NgapDecoder:
    def decode(self, payload: bytes, direction: str) -> DecodedMessage:
        return DecodedMessage(
            protocol="ngap",
            direction=direction,
            pdu_type="unsupported",
            procedure_code=None,
            procedure_name="unsupported_ngap_decode",
            message_name="unsupported_ngap_decode",
            fields={"decoder.strategy": "not_implemented"},
            decode_error="NGAP decoding is not implemented yet",
        )

