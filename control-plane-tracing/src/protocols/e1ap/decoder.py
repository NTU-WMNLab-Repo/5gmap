from protocols.f1ap.decoder import DecodedMessage


class E1apDecoder:
    def decode(self, payload: bytes, direction: str) -> DecodedMessage:
        return DecodedMessage(
            protocol="e1ap",
            direction=direction,
            pdu_type="unsupported",
            procedure_code=None,
            procedure_name="unsupported_e1ap_decode",
            message_name="unsupported_e1ap_decode",
            fields={"decoder.strategy": "not_implemented"},
            decode_error="E1AP decoding is not implemented yet",
        )

