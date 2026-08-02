import os
from typing import Any, Iterable, Optional

from protocols.asn1_per.pycrate_decoder import PycratePerDecoder
from protocols.decoded_message import DecodedMessage


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


class F1apDecoder:
    def __init__(self) -> None:
        enable_pycrate = os.getenv("F1AP_ENABLE_PYCRATE", "1") != "0"
        self.pycrate = PycratePerDecoder(
            module_name=(
                os.getenv("F1AP_PYCRATE_MODULE", "pycrate_asn1dir.F1AP")
                if enable_pycrate
                else None
            ),
            object_name=os.getenv("F1AP_PYCRATE_OBJECT", "F1AP_PDU_Descriptions.F1AP_PDU"),
        )

    def decode(self, payload: bytes, direction: str) -> DecodedMessage:
        decoded = self._decode_lightweight(payload, direction)

        pycrate_result = self.pycrate.decode_aper(payload)
        if pycrate_result.ok:
            decoded.fields.update(pycrate_result.fields)
            decoded.fields.update(extract_f1ap_fields(pycrate_result.value))
            decoded.fields["decoder.strategy"] = "pycrate"
            apply_pycrate_names(decoded, pycrate_result.value)
        elif self.pycrate.enabled:
            decoded.fields["asn1.decoder"] = "pycrate"
            decoded.fields["asn1.decode.error"] = pycrate_result.error or "pycrate decode failed"
            decoded.fields["decoder.strategy"] = "lightweight"

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


def normalize_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def as_attr_value(value: Any, *, max_len: int = 512) -> Optional[bool | int | float | str]:
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, bytes):
        return value.hex()[:max_len]
    if isinstance(value, str):
        return value[:max_len]
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
        nested = as_attr_value(value[1], max_len=max_len)
        if nested is None:
            return value[0]
        return nested
    return repr(value)[:max_len]


def walk_named_values(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str):
                yield key, child
            yield from walk_named_values(child)
        return

    if isinstance(value, (list, tuple)):
        if len(value) == 2 and isinstance(value[0], str):
            yield value[0], value[1]
        for child in value:
            yield from walk_named_values(child)


def all_named_values(value: Any, names: set[str]) -> list[Any]:
    normalized = {normalize_name(name) for name in names}
    found = []
    for name, candidate in walk_named_values(value):
        if normalize_name(name) in normalized:
            found.append(candidate)
    return found


def extract_choice_name(value: Any) -> Optional[str]:
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
        return value[0]
    return None


def extract_top_level(value: Any) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    if not isinstance(value, tuple) or len(value) != 2 or not isinstance(value[0], str):
        return None, None
    pdu_type = value[0]
    body = value[1] if isinstance(value[1], dict) else None
    return pdu_type, body


def extract_ie_summary(value: Any) -> tuple[list[int], list[str]]:
    ids: list[int] = []
    names: list[str] = []

    def visit(candidate: Any) -> None:
        if isinstance(candidate, dict):
            if "id" in candidate and "value" in candidate:
                ie_id = candidate.get("id")
                if isinstance(ie_id, int):
                    ids.append(ie_id)
                choice_name = extract_choice_name(candidate.get("value"))
                if choice_name:
                    names.append(choice_name)
            for child in candidate.values():
                visit(child)
        elif isinstance(candidate, (list, tuple)):
            for child in candidate:
                visit(child)

    visit(value)
    return ids, names


def extract_f1ap_fields(value: Any) -> dict[str, bool | int | float | str]:
    fields: dict[str, bool | int | float | str] = {
        "asn1.decode.full": True,
    }

    pdu_type, body = extract_top_level(value)
    if pdu_type:
        fields["f1ap.pycrate.pdu.type"] = pdu_type
    if body:
        procedure_code = body.get("procedureCode")
        criticality = body.get("criticality")
        if isinstance(procedure_code, int):
            fields["f1ap.pycrate.procedure.code"] = procedure_code
        if isinstance(criticality, str):
            fields["f1ap.pycrate.criticality"] = criticality

        message_name = extract_choice_name(body.get("value"))
        if message_name:
            fields["f1ap.pycrate.message.name"] = message_name

    ie_ids, ie_names = extract_ie_summary(value)
    if ie_ids:
        fields["f1ap.ie.ids"] = ",".join(str(item) for item in ie_ids[:64])
        fields["f1ap.ie.count"] = len(ie_ids)
    if ie_names:
        fields["f1ap.ie.names"] = ",".join(ie_names[:64])

    selected_names = {
        "transaction.id": {"TransactionID", "TransactionID-ExtIEs"},
        "gnb.cu.ue.f1ap.id": {"gNB-CU-UE-F1AP-ID", "GNB-CU-UE-F1AP-ID"},
        "gnb.du.ue.f1ap.id": {"gNB-DU-UE-F1AP-ID", "GNB-DU-UE-F1AP-ID"},
        "nr.cgi": {"NRCGI"},
        "c.rnti": {"C-RNTI"},
        "srb.id": {"SRBID"},
        "drb.id": {"DRBID"},
        "pdu.session.id": {"PDU-Session-ID"},
        "rrc.container": {"RRCContainer"},
    }
    for attr_name, names in selected_names.items():
        values = all_named_values(value, names)
        if not values:
            continue
        attr_value = as_attr_value(values[0])
        if attr_value is not None:
            fields[f"f1ap.{attr_name}"] = attr_value
            if attr_name == "c.rnti" and isinstance(attr_value, int):
                fields["f1ap.c.rnti.hex"] = f"0x{attr_value:04x}"
        if len(values) > 1:
            fields[f"f1ap.{attr_name}.count"] = len(values)

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
        procedure = F1AP_PROCEDURES.get(procedure_code)
        if procedure:
            decoded.procedure_name = procedure["procedure"] or decoded.procedure_name

    message_name = extract_choice_name(body.get("value"))
    if message_name:
        decoded.message_name = message_name
