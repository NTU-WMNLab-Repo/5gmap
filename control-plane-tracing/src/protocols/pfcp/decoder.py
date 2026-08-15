from __future__ import annotations

from typing import Final, Optional

from protocols.decoded_message import DecodedMessage


PFCP_VERSION: Final = 1
PFCP_MIN_NODE_HEADER_BYTES: Final = 8
PFCP_MIN_SESSION_HEADER_BYTES: Final = 16


# TS 29.244 Table 7.3-1. The lightweight decoder intentionally maps only the
# header message type; it does not inspect message-specific Information Elements.
PFCP_MESSAGE_TYPES: Final[dict[int, tuple[str, str, str]]] = {
    1: ("Heartbeat", "HeartbeatRequest", "request"),
    2: ("Heartbeat", "HeartbeatResponse", "response"),
    3: ("PFDManagement", "PFDManagementRequest", "request"),
    4: ("PFDManagement", "PFDManagementResponse", "response"),
    5: ("AssociationSetup", "AssociationSetupRequest", "request"),
    6: ("AssociationSetup", "AssociationSetupResponse", "response"),
    7: ("AssociationUpdate", "AssociationUpdateRequest", "request"),
    8: ("AssociationUpdate", "AssociationUpdateResponse", "response"),
    9: ("AssociationRelease", "AssociationReleaseRequest", "request"),
    10: ("AssociationRelease", "AssociationReleaseResponse", "response"),
    11: ("VersionNotSupported", "VersionNotSupportedResponse", "response"),
    12: ("NodeReport", "NodeReportRequest", "request"),
    13: ("NodeReport", "NodeReportResponse", "response"),
    14: ("SessionSetDeletion", "SessionSetDeletionRequest", "request"),
    15: ("SessionSetDeletion", "SessionSetDeletionResponse", "response"),
    16: ("SessionSetModification", "SessionSetModificationRequest", "request"),
    17: ("SessionSetModification", "SessionSetModificationResponse", "response"),
    50: ("SessionEstablishment", "SessionEstablishmentRequest", "request"),
    51: ("SessionEstablishment", "SessionEstablishmentResponse", "response"),
    52: ("SessionModification", "SessionModificationRequest", "request"),
    53: ("SessionModification", "SessionModificationResponse", "response"),
    54: ("SessionDeletion", "SessionDeletionRequest", "request"),
    55: ("SessionDeletion", "SessionDeletionResponse", "response"),
    56: ("SessionReport", "SessionReportRequest", "request"),
    57: ("SessionReport", "SessionReportResponse", "response"),
}


class PfcpDecoder:
    """Decode PFCP headers without parsing Information Elements."""

    def decode_datagram(self, payload: bytes, direction: str) -> list[DecodedMessage]:
        if not payload:
            return [
                self._malformed_message(
                    direction=direction,
                    message_index=0,
                    offset=0,
                    error="empty PFCP datagram",
                )
            ]

        decoded_messages: list[DecodedMessage] = []
        offset = 0
        message_index = 0

        while offset < len(payload):
            decoded, message_size, follow_on = self._decode_message(
                payload=payload,
                direction=direction,
                message_index=message_index,
                offset=offset,
            )
            decoded_messages.append(decoded)

            if message_size is None:
                break

            next_offset = offset + message_size
            if next_offset == len(payload):
                if follow_on:
                    self._append_error(
                        decoded,
                        "FO=1 but no following PFCP message is present",
                    )
                    decoded.fields["pfcp.bundle.error"] = "missing_follow_on"
                break

            if not follow_on:
                trailing_bytes = len(payload) - next_offset
                self._append_error(
                    decoded,
                    f"FO=0 but {trailing_bytes} trailing datagram bytes remain",
                )
                decoded.fields["pfcp.bundle.error"] = "unexpected_trailing_bytes"
                decoded.fields["pfcp.bundle.trailing_bytes"] = trailing_bytes
                break

            offset = next_offset
            message_index += 1

        self._annotate_datagram(decoded_messages, len(payload))
        return decoded_messages

    def _decode_message(
        self,
        payload: bytes,
        direction: str,
        message_index: int,
        offset: int,
    ) -> tuple[DecodedMessage, Optional[int], bool]:
        remaining_bytes = len(payload) - offset
        if remaining_bytes < 4:
            return (
                self._malformed_message(
                    direction=direction,
                    message_index=message_index,
                    offset=offset,
                    error=(
                        "truncated PFCP header: fewer than the mandatory "
                        f"four bytes remain ({remaining_bytes})"
                    ),
                ),
                None,
                False,
            )

        flags = payload[offset]
        version = (flags >> 5) & 0x07
        spare_bits = (flags >> 3) & 0x03
        follow_on = bool(flags & 0x04)
        message_priority = bool(flags & 0x02)
        seid_present = bool(flags & 0x01)
        message_type = payload[offset + 1]
        message_length = int.from_bytes(payload[offset + 2 : offset + 4], "big")
        header_size = (
            PFCP_MIN_SESSION_HEADER_BYTES if seid_present else PFCP_MIN_NODE_HEADER_BYTES
        )
        message_size = 4 + message_length

        base_fields: dict[str, bool | int | str] = {
            "decoder.strategy": "pfcp_header",
            "pfcp.decode.enabled": True,
            "pfcp.version": version,
            "pfcp.fo_flag": follow_on,
            "pfcp.mp_flag": message_priority,
            "pfcp.s_flag": seid_present,
            "pfcp.message.type": message_type,
            "pfcp.message.length": message_length,
            "pfcp.message.size": message_size,
            "pfcp.message.offset": offset,
            "pfcp.message.index": message_index,
        }
        if spare_bits:
            base_fields["pfcp.header.spare_bits"] = spare_bits

        if message_size < header_size:
            base_fields["pfcp.decode.status"] = "malformed"
            base_fields["pfcp.header.minimum_size"] = header_size
            return (
                self._malformed_message(
                    direction=direction,
                    message_index=message_index,
                    offset=offset,
                    error=(
                        f"PFCP message length {message_length} declares {message_size} bytes, "
                        f"shorter than the {header_size}-byte header"
                    ),
                    fields=base_fields,
                ),
                None,
                follow_on,
            )

        if message_size > remaining_bytes:
            base_fields["pfcp.decode.status"] = "malformed"
            base_fields["pfcp.datagram.remaining_bytes"] = remaining_bytes
            return (
                self._malformed_message(
                    direction=direction,
                    message_index=message_index,
                    offset=offset,
                    error=(
                        f"PFCP message declares {message_size} bytes but only "
                        f"{remaining_bytes} datagram bytes remain"
                    ),
                    fields=base_fields,
                ),
                None,
                follow_on,
            )

        sequence_offset = offset + (12 if seid_present else 4)
        base_fields["pfcp.sequence_number"] = int.from_bytes(
            payload[sequence_offset : sequence_offset + 3],
            "big",
        )

        if seid_present:
            seid = int.from_bytes(payload[offset + 4 : offset + 12], "big")
            base_fields["pfcp.seid"] = f"0x{seid:016x}"
            base_fields["pfcp.seid.is_zero"] = seid == 0
            if message_priority:
                base_fields["pfcp.message.priority"] = payload[offset + 15] >> 4
        else:
            final_header_octet = payload[offset + 7]
            if final_header_octet:
                base_fields["pfcp.header.spare_octet"] = final_header_octet

        procedure_name, message_name, message_class = self._message_info(message_type)
        base_fields["pfcp.message.class"] = message_class
        if version != PFCP_VERSION:
            base_fields["pfcp.decode.status"] = "unsupported_version"
            decode_error = f"unsupported PFCP version {version}"
        elif message_type not in PFCP_MESSAGE_TYPES:
            base_fields["pfcp.decode.status"] = "unknown_message_type"
            decode_error = None
        else:
            base_fields["pfcp.decode.status"] = "header_decoded"
            decode_error = None

        return (
            DecodedMessage(
                protocol="pfcp",
                direction=direction,
                pdu_type=message_class,
                procedure_code=message_type,
                procedure_name=procedure_name,
                message_name=message_name,
                fields=base_fields,
                decode_error=decode_error,
            ),
            message_size,
            follow_on,
        )

    @staticmethod
    def _message_info(message_type: int) -> tuple[str, str, str]:
        info = PFCP_MESSAGE_TYPES.get(message_type)
        if info is not None:
            return info
        return (
            f"message_type_{message_type}",
            f"UnknownMessageType{message_type}",
            "other",
        )

    @staticmethod
    def _malformed_message(
        direction: str,
        message_index: int,
        offset: int,
        error: str,
        fields: Optional[dict[str, bool | int | str]] = None,
    ) -> DecodedMessage:
        message_fields: dict[str, bool | int | str] = {
            "decoder.strategy": "pfcp_header",
            "pfcp.decode.enabled": True,
            "pfcp.decode.status": "malformed",
            "pfcp.message.offset": offset,
            "pfcp.message.index": message_index,
        }
        if fields:
            message_fields.update(fields)
        return DecodedMessage(
            protocol="pfcp",
            direction=direction,
            pdu_type="malformed",
            procedure_code=None,
            procedure_name="malformed",
            message_name="MalformedDatagram",
            fields=message_fields,
            decode_error=error,
        )

    @staticmethod
    def _append_error(decoded: DecodedMessage, error: str) -> None:
        if decoded.decode_error:
            decoded.decode_error = f"{decoded.decode_error}; {error}"
        else:
            decoded.decode_error = error
        decoded.fields["pfcp.decode.status"] = "malformed"

    @staticmethod
    def _annotate_datagram(decoded_messages: list[DecodedMessage], datagram_size: int) -> None:
        message_count = len(decoded_messages)
        bundled = message_count > 1
        for decoded in decoded_messages:
            decoded.fields["pfcp.datagram.size"] = datagram_size
            decoded.fields["pfcp.datagram.message.count"] = message_count
            decoded.fields["pfcp.datagram.bundled"] = bundled
