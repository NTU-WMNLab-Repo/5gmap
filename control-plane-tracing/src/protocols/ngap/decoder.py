import os
from typing import Any

from protocols.asn1_per.pycrate_decoder import PycratePerDecoder
from protocols.asn1_per.value_helpers import (
    all_named_values,
    as_attr_value,
    extract_choice_name,
    extract_ie_summary,
    extract_top_level,
)
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
    def __init__(self) -> None:
        enable_pycrate = os.getenv("NGAP_ENABLE_PYCRATE", "1") != "0"
        self.pycrate = PycratePerDecoder(
            module_name=(
                os.getenv("NGAP_PYCRATE_MODULE", "pycrate_asn1dir.NGAP")
                if enable_pycrate
                else None
            ),
            object_name=os.getenv("NGAP_PYCRATE_OBJECT", "NGAP_PDU_Descriptions.NGAP_PDU"),
        )

    def decode(self, payload: bytes, direction: str) -> DecodedMessage:
        decoded = self._decode_lightweight(payload, direction)

        pycrate_result = self.pycrate.decode_aper(payload)
        if pycrate_result.ok:
            decoded.fields.update(pycrate_result.fields)
            decoded.fields.update(extract_ngap_fields(pycrate_result.value))
            decoded.fields["decoder.strategy"] = "pycrate"
            decoded.fields["ngap.decode.status"] = "decoded"
            apply_pycrate_names(decoded, pycrate_result.value)
        elif self.pycrate.enabled:
            decoded.fields["asn1.decoder"] = "pycrate"
            decoded.fields["asn1.decode.error"] = pycrate_result.error or "pycrate decode failed"
            decoded.fields["decoder.strategy"] = "lightweight"

        return decoded

    def _decode_lightweight(self, payload: bytes, direction: str) -> DecodedMessage:
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


def extract_ngap_fields(value: Any) -> dict[str, bool | int | float | str]:
    fields: dict[str, bool | int | float | str] = {
        "asn1.decode.full": True,
    }

    pdu_type, body = extract_top_level(value)
    if pdu_type:
        fields["ngap.pycrate.pdu.type"] = pdu_type
    if body:
        procedure_code = body.get("procedureCode")
        criticality = body.get("criticality")
        if isinstance(procedure_code, int):
            fields["ngap.pycrate.procedure.code"] = procedure_code
        if isinstance(criticality, str):
            fields["ngap.pycrate.criticality"] = criticality

        message_name = extract_choice_name(body.get("value"))
        if message_name:
            fields["ngap.pycrate.message.name"] = message_name

    ie_ids, ie_names = extract_ie_summary(value)
    if ie_ids:
        fields["ngap.ie.ids"] = ",".join(str(item) for item in ie_ids[:64])
        fields["ngap.ie.count"] = len(ie_ids)
    if ie_names:
        fields["ngap.ie.names"] = ",".join(ie_names[:64])

    selected_names = {
        "ran.ue.ngap.id": {"RAN-UE-NGAP-ID"},
        "amf.ue.ngap.id": {"AMF-UE-NGAP-ID"},
        "global.ran.node.id": {"GlobalRANNodeID"},
        "ran.node.name": {"RANNodeName"},
        "nr.cgi": {"NRCGI", "nR-CGI"},
        "tai": {"TAI", "tAI"},
        "rrc.establishment.cause": {"RRCEstablishmentCause"},
        "pdu.session.id": {"PDUSessionID", "PDU-Session-ID"},
        "pdu.session.resource.setup.list.su.req": {
            "PDUSessionResourceSetupListSUReq",
        },
        "pdu.session.resource.setup.list.su.res": {
            "PDUSessionResourceSetupListSURes",
        },
        "pdu.session.resource.setup.response.transfer": {
            "PDUSessionResourceSetupResponseTransfer",
        },
    }
    for attr_name, names in selected_names.items():
        values = all_named_values(value, names)
        if not values:
            continue
        attr_value = as_attr_value(values[0])
        if attr_value is not None:
            fields[f"ngap.{attr_name}"] = attr_value
        if len(values) > 1:
            fields[f"ngap.{attr_name}.count"] = len(values)

    return fields


def apply_pycrate_names(decoded: DecodedMessage, value: Any) -> None:
    pdu_type, body = extract_top_level(value)
    if pdu_type:
        decoded.pdu_type = pdu_type

    if not body:
        return

    procedure_code = body.get("procedureCode")
    if isinstance(procedure_code, int):
        decoded.procedure_code = procedure_code
        procedure = NGAP_PROCEDURES.get(procedure_code)
        if procedure:
            decoded.procedure_name = procedure["procedure"]

    message_name = extract_choice_name(body.get("value"))
    if message_name:
        decoded.message_name = message_name
