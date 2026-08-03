from protocols.decoded_message import DecodedMessage


NGAP_PROCEDURES: dict[int, dict[str, str]] = {
    4: {
        "procedure": "DownlinkNASTransport",
        "initiatingMessage": "DownlinkNASTransport",
    },
    14: {
        "procedure": "InitialContextSetup",
        "initiatingMessage": "InitialContextSetupRequest",
        "successfulOutcome": "InitialContextSetupResponse",
        "unsuccessfulOutcome": "InitialContextSetupFailure",
    },
    15: {
        "procedure": "InitialUEMessage",
        "initiatingMessage": "InitialUEMessage",
    },
    21: {
        "procedure": "NGSetup",
        "initiatingMessage": "NGSetupRequest",
        "successfulOutcome": "NGSetupResponse",
        "unsuccessfulOutcome": "NGSetupFailure",
    },
    29: {
        "procedure": "PDUSessionResourceSetup",
        "initiatingMessage": "PDUSessionResourceSetupRequest",
        "successfulOutcome": "PDUSessionResourceSetupResponse",
    },
    44: {
        "procedure": "UERadioCapabilityInfoIndication",
        "initiatingMessage": "UERadioCapabilityInfoIndication",
    },
    46: {
        "procedure": "UplinkNASTransport",
        "initiatingMessage": "UplinkNASTransport",
    },
}

PDU_TYPE_BY_SELECTOR = {
    0x00: "initiatingMessage",
    0x20: "successfulOutcome",
    0x40: "unsuccessfulOutcome",
}


class NgapDecoder:
    def decode(self, payload: bytes, direction: str) -> DecodedMessage:
        if len(payload) < 2:
            return DecodedMessage(
                protocol="ngap",
                direction=direction,
                pdu_type="empty_or_truncated",
                procedure_code=None,
                procedure_name="empty_or_truncated",
                message_name="empty_or_truncated",
                fields={
                    "decoder.strategy": "lightweight",
                    "ngap.decode.status": "truncated",
                },
                decode_error="payload shorter than NGAP PDU header",
            )

        pdu_selector = payload[0] & 0xE0
        pdu_type = PDU_TYPE_BY_SELECTOR.get(pdu_selector, "unknownPDU")
        procedure_code = payload[1]
        procedure = NGAP_PROCEDURES.get(procedure_code)
        if procedure:
            procedure_name = procedure["procedure"]
            message_name = procedure.get(pdu_type) or f"{procedure_name}_{pdu_type}"
        else:
            procedure_name = f"procedure_{procedure_code}"
            message_name = f"{procedure_name}_{pdu_type}"

        return DecodedMessage(
            protocol="ngap",
            direction=direction,
            pdu_type=pdu_type,
            procedure_code=procedure_code,
            procedure_name=procedure_name,
            message_name=message_name,
            fields={
                "decoder.strategy": "lightweight",
                "ngap.decode.status": "classified",
                "ngap.pdu.selector": pdu_selector,
                "ngap.pdu.first_octet": payload[0],
            },
            decode_error=None,
        )
