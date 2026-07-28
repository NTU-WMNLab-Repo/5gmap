import os
from dataclasses import dataclass, field
from typing import Any, Optional

from protocols.asn1_per.pycrate_decoder import PycratePerDecoder


F1AP_PROCEDURES = {
    0: "Reset",
    1: "F1Setup",
    2: "gNBDUConfigurationUpdate",
    3: "gNBCUConfigurationUpdate",
    4: "gNBDUResourceCoordination",
    5: "UEContextSetup",
    6: "UEContextRelease",
    7: "UEContextModification",
    8: "UEContextModificationRequired",
    9: "UEContextReleaseRequest",
    11: "InitialULRRCMessageTransfer",
    12: "DLRRCMessageTransfer",
    13: "ULRRCMessageTransfer",
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
        procedure_name = F1AP_PROCEDURES.get(procedure_code, f"procedure_{procedure_code}")
        message_name = self._message_name(procedure_name, pdu_type)

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

    @staticmethod
    def _message_name(procedure_name: str, pdu_type: str) -> str:
        suffix_by_pdu = {
            "initiatingMessage": "Request",
            "successfulOutcome": "Response",
            "unsuccessfulOutcome": "Failure",
        }
        suffix = suffix_by_pdu.get(pdu_type)
        if not suffix:
            return procedure_name

        if procedure_name.endswith(("Request", "Response", "Failure", "Notification")):
            return procedure_name

        return f"{procedure_name}{suffix}"
