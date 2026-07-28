import os
from dataclasses import dataclass, field
from typing import Any, Optional

from protocols.asn1_per.pycrate_decoder import PycratePerDecoder


F1AP_PROCEDURES: dict[int, dict[str, Optional[str]]] = {
    0: {
        "procedure": "Reset",
        "initiatingMessage": "Reset",
        "successfulOutcome": "ResetAcknowledge",
    },
    1: {
        "procedure": "F1Setup",
        "initiatingMessage": "F1SetupRequest",
        "successfulOutcome": "F1SetupResponse",
        "unsuccessfulOutcome": "F1SetupFailure",
    },
    2: {
        "procedure": "ErrorIndication",
        "initiatingMessage": "ErrorIndication",
    },
    3: {
        "procedure": "gNBDUConfigurationUpdate",
        "initiatingMessage": "GNBDUConfigurationUpdate",
        "successfulOutcome": "GNBDUConfigurationUpdateAcknowledge",
        "unsuccessfulOutcome": "GNBDUConfigurationUpdateFailure",
    },
    4: {
        "procedure": "gNBCUConfigurationUpdate",
        "initiatingMessage": "GNBCUConfigurationUpdate",
        "successfulOutcome": "GNBCUConfigurationUpdateAcknowledge",
        "unsuccessfulOutcome": "GNBCUConfigurationUpdateFailure",
    },
    5: {
        "procedure": "UEContextSetup",
        "initiatingMessage": "UEContextSetupRequest",
        "successfulOutcome": "UEContextSetupResponse",
        "unsuccessfulOutcome": "UEContextSetupFailure",
    },
    6: {
        "procedure": "UEContextRelease",
        "initiatingMessage": "UEContextReleaseCommand",
        "successfulOutcome": "UEContextReleaseComplete",
    },
    7: {
        "procedure": "UEContextModification",
        "initiatingMessage": "UEContextModificationRequest",
        "successfulOutcome": "UEContextModificationResponse",
        "unsuccessfulOutcome": "UEContextModificationFailure",
    },
    8: {
        "procedure": "UEContextModificationRequired",
        "initiatingMessage": "UEContextModificationRequired",
        "successfulOutcome": "UEContextModificationConfirm",
        "unsuccessfulOutcome": "UEContextModificationRefuse",
    },
    10: {
        "procedure": "UEContextReleaseRequest",
        "initiatingMessage": "UEContextReleaseRequest",
    },
    11: {
        "procedure": "InitialULRRCMessageTransfer",
        "initiatingMessage": "InitialULRRCMessageTransfer",
    },
    12: {
        "procedure": "DLRRCMessageTransfer",
        "initiatingMessage": "DLRRCMessageTransfer",
    },
    13: {
        "procedure": "ULRRCMessageTransfer",
        "initiatingMessage": "ULRRCMessageTransfer",
    },
    16: {
        "procedure": "gNBDUResourceCoordination",
        "initiatingMessage": "GNBDUResourceCoordinationRequest",
        "successfulOutcome": "GNBDUResourceCoordinationResponse",
    },
}

PDU_TYPE_BY_MARKER = {
    0x00: "initiatingMessage",
    0x40: "successfulOutcome",
    0x80: "unsuccessfulOutcome",
}


@dataclass
class DecodedMessage:
    protocol: str
    direction: str
    pdu_type: str
    procedure_code: Optional[int]
    procedure_name: str
    message_name: str
    fields: dict[str, Any] = field(default_factory=dict)
    decode_error: Optional[str] = None


class F1apDecoder:
    def __init__(self) -> None:
        self.pycrate = PycratePerDecoder(
            module_name=os.getenv("F1AP_PYCRATE_MODULE"),
            object_name=os.getenv("F1AP_PYCRATE_OBJECT", "F1AP_PDU"),
        )

    def decode(self, payload: bytes, direction: str) -> DecodedMessage:
        decoded = self._decode_lightweight(payload, direction)

        pycrate_result = self.pycrate.decode_aper(payload)
        if pycrate_result.ok:
            decoded.fields.update(pycrate_result.fields)
            decoded.fields["decoder.strategy"] = "pycrate+lightweight"
        elif self.pycrate.enabled:
            decoded.fields["asn1.decoder"] = "pycrate"
            decoded.decode_error = pycrate_result.error

        return decoded

    def _decode_lightweight(self, payload: bytes, direction: str) -> DecodedMessage:
        if len(payload) < 2:
            return DecodedMessage(
                protocol="f1ap",
                direction=direction,
                pdu_type="empty_or_truncated",
                procedure_code=None,
                procedure_name="empty_or_truncated",
                message_name="empty_or_truncated",
                fields={"decoder.strategy": "lightweight"},
                decode_error="payload shorter than F1AP PDU header",
            )

        pdu_marker = payload[0] & 0xC0
        pdu_type = PDU_TYPE_BY_MARKER.get(pdu_marker, "unknownPDU")
        procedure_code = payload[1]
        procedure = F1AP_PROCEDURES.get(procedure_code)
        if procedure:
            procedure_name = procedure["procedure"] or f"procedure_{procedure_code}"
            message_name = procedure.get(pdu_type) or f"{procedure_name}_{pdu_type}"
        else:
            procedure_name = f"procedure_{procedure_code}"
            message_name = f"{procedure_name}_{pdu_type}"

        return DecodedMessage(
            protocol="f1ap",
            direction=direction,
            pdu_type=pdu_type,
            procedure_code=procedure_code,
            procedure_name=procedure_name,
            message_name=message_name,
            fields={
                "decoder.strategy": "lightweight",
                "f1ap.pdu.marker": pdu_marker,
            },
        )
