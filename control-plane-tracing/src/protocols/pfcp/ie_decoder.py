from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import IPv4Address, IPv6Address
from typing import Any, Callable, Final, Iterable


PFCP_IE_HEADER_BYTES: Final = 4
PFCP_MAX_IE_DEPTH: Final = 8
PFCP_MAX_IE_COUNT: Final = 4096
PFCP_MAX_EXPORTED_RECORDS: Final = 64

IE_CREATE_PDR: Final = 1
IE_PDI: Final = 2
IE_CREATE_FAR: Final = 3
IE_FORWARDING_PARAMETERS: Final = 4
IE_CREATED_PDR: Final = 8
IE_UPDATE_PDR: Final = 9
IE_UPDATE_FAR: Final = 10
IE_UPDATE_FORWARDING_PARAMETERS: Final = 11
IE_REMOVE_PDR: Final = 15
IE_REMOVE_FAR: Final = 16
IE_CAUSE: Final = 19
IE_SOURCE_INTERFACE: Final = 20
IE_F_TEID: Final = 21
IE_NETWORK_INSTANCE: Final = 22
IE_DESTINATION_INTERFACE: Final = 42
IE_PDR_ID: Final = 56
IE_F_SEID: Final = 57
IE_NODE_ID: Final = 60
IE_OUTER_HEADER_CREATION: Final = 84
IE_UE_IP_ADDRESS: Final = 93
IE_FAR_ID: Final = 108
IE_CREATE_TRAFFIC_ENDPOINT: Final = 127
IE_CREATED_TRAFFIC_ENDPOINT: Final = 128
IE_UPDATE_TRAFFIC_ENDPOINT: Final = 129
IE_REMOVE_TRAFFIC_ENDPOINT: Final = 130
IE_S_NSSAI: Final = 257


IE_NAMES: Final[dict[int, str]] = {
    IE_CREATE_PDR: "CreatePDR",
    IE_PDI: "PDI",
    IE_CREATE_FAR: "CreateFAR",
    IE_FORWARDING_PARAMETERS: "ForwardingParameters",
    IE_CREATED_PDR: "CreatedPDR",
    IE_UPDATE_PDR: "UpdatePDR",
    IE_UPDATE_FAR: "UpdateFAR",
    IE_UPDATE_FORWARDING_PARAMETERS: "UpdateForwardingParameters",
    IE_REMOVE_PDR: "RemovePDR",
    IE_REMOVE_FAR: "RemoveFAR",
    IE_CAUSE: "Cause",
    IE_SOURCE_INTERFACE: "SourceInterface",
    IE_F_TEID: "F-TEID",
    IE_NETWORK_INSTANCE: "NetworkInstance",
    IE_DESTINATION_INTERFACE: "DestinationInterface",
    IE_PDR_ID: "PDR-ID",
    IE_F_SEID: "F-SEID",
    IE_NODE_ID: "NodeID",
    IE_OUTER_HEADER_CREATION: "OuterHeaderCreation",
    IE_UE_IP_ADDRESS: "UEIPAddress",
    IE_FAR_ID: "FAR-ID",
    IE_CREATE_TRAFFIC_ENDPOINT: "CreateTrafficEndpoint",
    IE_CREATED_TRAFFIC_ENDPOINT: "CreatedTrafficEndpoint",
    IE_UPDATE_TRAFFIC_ENDPOINT: "UpdateTrafficEndpoint",
    IE_REMOVE_TRAFFIC_ENDPOINT: "RemoveTrafficEndpoint",
    IE_S_NSSAI: "S-NSSAI",
}

GROUPED_IE_TYPES: Final[frozenset[int]] = frozenset(
    {
        IE_CREATE_PDR,
        IE_PDI,
        IE_CREATE_FAR,
        IE_FORWARDING_PARAMETERS,
        IE_CREATED_PDR,
        IE_UPDATE_PDR,
        IE_UPDATE_FAR,
        IE_UPDATE_FORWARDING_PARAMETERS,
        IE_REMOVE_PDR,
        IE_REMOVE_FAR,
        IE_CREATE_TRAFFIC_ENDPOINT,
        IE_CREATED_TRAFFIC_ENDPOINT,
        IE_UPDATE_TRAFFIC_ENDPOINT,
        IE_REMOVE_TRAFFIC_ENDPOINT,
    }
)

PDR_GROUPS: Final[dict[int, str]] = {
    IE_CREATE_PDR: "create",
    IE_CREATED_PDR: "created",
    IE_UPDATE_PDR: "update",
    IE_REMOVE_PDR: "remove",
}
FAR_GROUPS: Final[dict[int, str]] = {
    IE_CREATE_FAR: "create",
    IE_UPDATE_FAR: "update",
    IE_REMOVE_FAR: "remove",
}
FORWARDING_PARAMETER_GROUPS: Final[frozenset[int]] = frozenset(
    {IE_FORWARDING_PARAMETERS, IE_UPDATE_FORWARDING_PARAMETERS}
)

SOURCE_INTERFACES: Final[dict[int, str]] = {
    0: "Access",
    1: "Core",
    2: "SGi-LAN/N6-LAN",
    3: "CP-function",
    4: "5G-VN-Internal",
}
DESTINATION_INTERFACES: Final[dict[int, str]] = {
    0: "Access",
    1: "Core",
    2: "SGi-LAN/N6-LAN",
    3: "CP-function",
    4: "LI-function",
    5: "5G-VN-Internal",
}

CAUSE_NAMES: Final[dict[int, str]] = {
    0: "Reserved",
    1: "RequestAccepted",
    2: "MoreUsageReportToSend",
    3: "RequestPartiallyAccepted",
    64: "RequestRejected",
    65: "SessionContextNotFound",
    66: "MandatoryIEMissing",
    67: "ConditionalIEMissing",
    68: "InvalidLength",
    69: "MandatoryIEIncorrect",
    70: "InvalidForwardingPolicy",
    71: "InvalidFTEIDAllocationOption",
    72: "NoEstablishedPFCPAssociation",
    73: "RuleCreationModificationFailure",
    74: "PFCPEntityInCongestion",
    75: "NoResourcesAvailable",
    76: "ServiceNotSupported",
    77: "SystemFailure",
    78: "RedirectionRequested",
    79: "AllDynamicAddressesOccupied",
    80: "UnknownPredefinedRule",
    81: "UnknownApplicationID",
    82: "L2TPTunnelEstablishmentFailure",
    83: "L2TPSessionEstablishmentFailure",
    84: "L2TPTunnelRelease",
    85: "L2TPSessionRelease",
    86: "PFCPSessionRestorationFailure",
    87: "L2TPTunnelAuthenticationFailure",
    88: "L2TPSessionAuthenticationFailure",
    89: "L2TPTunnelLNSNotReachable",
}


@dataclass(frozen=True)
class PfcpIe:
    ie_type: int
    length: int
    offset: int
    value: bytes
    path: tuple[str, ...]
    children: tuple["PfcpIe", ...] = ()


@dataclass
class _DecodeState:
    ie_count: int = 0
    grouped_count: int = 0
    unsupported_count: int = 0
    max_depth: int = 0
    errors: list[str] = field(default_factory=list)
    attributes_truncated: bool = False


class PfcpIeDecoder:
    """Bounded PFCP TLV walker and selected IE value decoder."""

    def __init__(
        self,
        max_depth: int = PFCP_MAX_IE_DEPTH,
        max_ie_count: int = PFCP_MAX_IE_COUNT,
        max_exported_records: int = PFCP_MAX_EXPORTED_RECORDS,
    ) -> None:
        self.max_depth = max_depth
        self.max_ie_count = max_ie_count
        self.max_exported_records = max_exported_records

    def decode(self, payload: bytes, message_type: int, direction: str) -> dict[str, Any]:
        state = _DecodeState()
        nodes = self._parse_sequence(payload, 0, (), state)
        fields: dict[str, Any] = {
            "pfcp.ie.decode.enabled": True,
            "pfcp.ie.bytes": len(payload),
            "pfcp.ie.count": state.ie_count,
            "pfcp.ie.top_level.count": len(nodes),
            "pfcp.ie.grouped.count": state.grouped_count,
            "pfcp.ie.unsupported.count": state.unsupported_count,
            "pfcp.ie.max_depth": state.max_depth,
        }

        top_level = nodes[: self.max_exported_records]
        if len(nodes) > len(top_level):
            state.attributes_truncated = True
        fields["pfcp.ie.top_level.type_ids"] = ",".join(
            str(node.ie_type) for node in top_level
        )
        fields["pfcp.ie.top_level.names"] = ",".join(
            IE_NAMES.get(node.ie_type, f"IE-{node.ie_type}") for node in top_level
        )

        all_nodes = list(self._walk(nodes))
        self._extract_causes(all_nodes, fields, state)
        self._extract_node_ids(all_nodes, fields, state)
        self._extract_f_seids(all_nodes, message_type, direction, fields, state)
        self._extract_generic_records(all_nodes, fields, state)
        self._extract_pdrs(all_nodes, fields, state)
        self._extract_fars(all_nodes, fields, state)

        if not payload:
            status = "no_ies"
        elif state.errors and state.ie_count:
            status = "partial"
        elif state.errors:
            status = "malformed"
        else:
            status = "decoded"
        fields["pfcp.ie.decode.status"] = status

        if state.errors:
            fields["pfcp.ie.decode.error_count"] = len(state.errors)
            fields["pfcp.ie.decode.error"] = "; ".join(state.errors)[:2048]
        if state.attributes_truncated:
            fields["pfcp.ie.attributes.truncated"] = True

        return fields

    def _parse_sequence(
        self,
        payload: bytes,
        depth: int,
        parent_path: tuple[str, ...],
        state: _DecodeState,
    ) -> list[PfcpIe]:
        nodes: list[PfcpIe] = []
        offset = 0
        state.max_depth = max(state.max_depth, depth)

        while offset < len(payload):
            if state.ie_count >= self.max_ie_count:
                state.errors.append(f"IE count exceeds limit {self.max_ie_count}")
                break

            remaining = len(payload) - offset
            if remaining < PFCP_IE_HEADER_BYTES:
                state.errors.append(
                    f"truncated IE header at value offset {offset}: {remaining} bytes remain"
                )
                break

            ie_type = int.from_bytes(payload[offset : offset + 2], "big")
            ie_length = int.from_bytes(payload[offset + 2 : offset + 4], "big")
            value_start = offset + PFCP_IE_HEADER_BYTES
            value_end = value_start + ie_length
            if value_end > len(payload):
                state.errors.append(
                    f"IE {ie_type} at value offset {offset} declares {ie_length} bytes, "
                    f"but only {len(payload) - value_start} remain"
                )
                break

            name = IE_NAMES.get(ie_type, f"IE-{ie_type}")
            path = parent_path + (name,)
            value = payload[value_start:value_end]
            state.ie_count += 1
            if ie_type not in IE_NAMES:
                state.unsupported_count += 1

            children: tuple[PfcpIe, ...] = ()
            if ie_type in GROUPED_IE_TYPES:
                state.grouped_count += 1
                if depth >= self.max_depth:
                    state.errors.append(
                        f"grouped IE {'/'.join(path)} exceeds depth limit {self.max_depth}"
                    )
                else:
                    children = tuple(
                        self._parse_sequence(value, depth + 1, path, state)
                    )

            nodes.append(
                PfcpIe(
                    ie_type=ie_type,
                    length=ie_length,
                    offset=offset,
                    value=value,
                    path=path,
                    children=children,
                )
            )
            offset = value_end

        return nodes

    @staticmethod
    def _walk(nodes: Iterable[PfcpIe]) -> Iterable[PfcpIe]:
        for node in nodes:
            yield node
            yield from PfcpIeDecoder._walk(node.children)

    def _extract_causes(
        self,
        nodes: list[PfcpIe],
        fields: dict[str, Any],
        state: _DecodeState,
    ) -> None:
        records = self._decode_records(
            nodes, IE_CAUSE, "pfcp.cause", self._decode_cause, fields, state
        )
        if records:
            self._copy_record_alias(records[0], "pfcp.cause", fields)

    def _extract_node_ids(
        self,
        nodes: list[PfcpIe],
        fields: dict[str, Any],
        state: _DecodeState,
    ) -> None:
        records = self._decode_records(
            nodes, IE_NODE_ID, "pfcp.node_id", self._decode_node_id, fields, state
        )
        if records:
            self._copy_record_alias(records[0], "pfcp.node_id", fields)

    def _extract_f_seids(
        self,
        nodes: list[PfcpIe],
        message_type: int,
        direction: str,
        fields: dict[str, Any],
        state: _DecodeState,
    ) -> None:
        matches = [node for node in nodes if node.ie_type == IE_F_SEID]
        fields["pfcp.f_seid.count"] = len(matches)
        role = self._f_seid_role(message_type, direction)

        for index, node in enumerate(matches[: self.max_exported_records]):
            values = self._decode_record(node, self._decode_f_seid, state)
            values["role"] = role
            self._store_record(fields, f"pfcp.f_seid.{index}", values)
            if index == 0 and role in {"cp", "up"}:
                self._store_record(fields, f"pfcp.session.{role}_f_seid", values)

        if len(matches) > self.max_exported_records:
            state.attributes_truncated = True

    def _extract_generic_records(
        self,
        nodes: list[PfcpIe],
        fields: dict[str, Any],
        state: _DecodeState,
    ) -> None:
        specs: tuple[tuple[int, str, Callable[[bytes], dict[str, Any]]], ...] = (
            (IE_F_TEID, "pfcp.f_teid", self._decode_f_teid),
            (
                IE_OUTER_HEADER_CREATION,
                "pfcp.outer_header_creation",
                self._decode_outer_header_creation,
            ),
            (IE_UE_IP_ADDRESS, "pfcp.ue_ip", self._decode_ue_ip),
            (
                IE_NETWORK_INSTANCE,
                "pfcp.network_instance",
                self._decode_network_instance,
            ),
            (IE_S_NSSAI, "pfcp.s_nssai", self._decode_s_nssai),
        )
        for ie_type, prefix, decoder in specs:
            self._decode_records(nodes, ie_type, prefix, decoder, fields, state)

    def _extract_pdrs(
        self,
        nodes: list[PfcpIe],
        fields: dict[str, Any],
        state: _DecodeState,
    ) -> None:
        pdrs = [node for node in nodes if node.ie_type in PDR_GROUPS]
        fields["pfcp.pdr.count"] = len(pdrs)

        for index, pdr in enumerate(pdrs[: self.max_exported_records]):
            prefix = f"pfcp.pdr.{index}"
            fields[f"{prefix}.operation"] = PDR_GROUPS[pdr.ie_type]
            fields[f"{prefix}.path"] = "/".join(pdr.path)

            pdr_id = self._first_child(pdr, IE_PDR_ID)
            if pdr_id is not None:
                pdr_values = self._decode_record(pdr_id, self._decode_pdr_id, state)
                if "pdr_id" in pdr_values:
                    fields[f"{prefix}.pdr_id"] = pdr_values["pdr_id"]

            far_id = self._first_child(pdr, IE_FAR_ID)
            if far_id is not None:
                far_values = self._decode_record(far_id, self._decode_far_id, state)
                if "far_id" in far_values:
                    fields[f"{prefix}.far_id"] = far_values["far_id"]

            pdi = self._first_child(pdr, IE_PDI)
            fields[f"{prefix}.pdi.present"] = pdi is not None
            scope = list(self._walk(pdi.children if pdi is not None else pdr.children))

            source = self._first(scope, IE_SOURCE_INTERFACE)
            source_code: int | None = None
            if source is not None:
                source_values = self._decode_record(
                    source, self._decode_source_interface, state
                )
                source_code = source_values.get("code")
                self._store_record(fields, f"{prefix}.source_interface", source_values)

            f_teids = [node for node in scope if node.ie_type == IE_F_TEID]
            fields[f"{prefix}.f_teid.count"] = len(f_teids)
            for fteid_index, f_teid in enumerate(
                f_teids[: self.max_exported_records]
            ):
                values = self._decode_record(f_teid, self._decode_f_teid, state)
                if PDR_GROUPS[pdr.ie_type] == "created":
                    values["endpoint_role"] = "upf_local"
                elif source_code == 0:
                    values["endpoint_role"] = "upf_n3_ingress"
                self._store_record(
                    fields, f"{prefix}.f_teid.{fteid_index}", values
                )

            self._extract_scoped_records(
                scope,
                IE_UE_IP_ADDRESS,
                f"{prefix}.ue_ip",
                self._decode_ue_ip,
                fields,
                state,
            )
            self._extract_scoped_records(
                scope,
                IE_NETWORK_INSTANCE,
                f"{prefix}.network_instance",
                self._decode_network_instance,
                fields,
                state,
            )

        if len(pdrs) > self.max_exported_records:
            state.attributes_truncated = True

    def _extract_fars(
        self,
        nodes: list[PfcpIe],
        fields: dict[str, Any],
        state: _DecodeState,
    ) -> None:
        fars = [node for node in nodes if node.ie_type in FAR_GROUPS]
        fields["pfcp.far.count"] = len(fars)

        for index, far in enumerate(fars[: self.max_exported_records]):
            prefix = f"pfcp.far.{index}"
            fields[f"{prefix}.operation"] = FAR_GROUPS[far.ie_type]
            fields[f"{prefix}.path"] = "/".join(far.path)

            far_id = self._first_child(far, IE_FAR_ID)
            if far_id is not None:
                far_values = self._decode_record(far_id, self._decode_far_id, state)
                if "far_id" in far_values:
                    fields[f"{prefix}.far_id"] = far_values["far_id"]

            forwarding = next(
                (
                    child
                    for child in far.children
                    if child.ie_type in FORWARDING_PARAMETER_GROUPS
                ),
                None,
            )
            scope = list(
                self._walk(forwarding.children if forwarding is not None else far.children)
            )

            destination = self._first(scope, IE_DESTINATION_INTERFACE)
            destination_code: int | None = None
            if destination is not None:
                destination_values = self._decode_record(
                    destination, self._decode_destination_interface, state
                )
                destination_code = destination_values.get("code")
                self._store_record(
                    fields, f"{prefix}.destination_interface", destination_values
                )

            creations = [
                node for node in scope if node.ie_type == IE_OUTER_HEADER_CREATION
            ]
            fields[f"{prefix}.outer_header_creation.count"] = len(creations)
            for creation_index, creation in enumerate(
                creations[: self.max_exported_records]
            ):
                values = self._decode_record(
                    creation, self._decode_outer_header_creation, state
                )
                if destination_code == 0:
                    values["endpoint_role"] = "ran_n3_egress"
                self._store_record(
                    fields,
                    f"{prefix}.outer_header_creation.{creation_index}",
                    values,
                )

            self._extract_scoped_records(
                scope,
                IE_NETWORK_INSTANCE,
                f"{prefix}.network_instance",
                self._decode_network_instance,
                fields,
                state,
            )

        if len(fars) > self.max_exported_records:
            state.attributes_truncated = True

    def _extract_scoped_records(
        self,
        nodes: list[PfcpIe],
        ie_type: int,
        prefix: str,
        decoder: Callable[[bytes], dict[str, Any]],
        fields: dict[str, Any],
        state: _DecodeState,
    ) -> None:
        matches = [node for node in nodes if node.ie_type == ie_type]
        fields[f"{prefix}.count"] = len(matches)
        for index, node in enumerate(matches[: self.max_exported_records]):
            values = self._decode_record(node, decoder, state)
            self._store_record(fields, f"{prefix}.{index}", values)
        if len(matches) > self.max_exported_records:
            state.attributes_truncated = True

    def _decode_records(
        self,
        nodes: list[PfcpIe],
        ie_type: int,
        prefix: str,
        decoder: Callable[[bytes], dict[str, Any]],
        fields: dict[str, Any],
        state: _DecodeState,
    ) -> list[dict[str, Any]]:
        matches = [node for node in nodes if node.ie_type == ie_type]
        fields[f"{prefix}.count"] = len(matches)
        records: list[dict[str, Any]] = []
        for index, node in enumerate(matches[: self.max_exported_records]):
            values = self._decode_record(node, decoder, state)
            records.append(values)
            self._store_record(fields, f"{prefix}.{index}", values)
        if len(matches) > self.max_exported_records:
            state.attributes_truncated = True
        return records

    @staticmethod
    def _store_record(
        fields: dict[str, Any], prefix: str, values: dict[str, Any]
    ) -> None:
        for key, value in values.items():
            fields[f"{prefix}.{key}"] = value

    @staticmethod
    def _copy_record_alias(
        values: dict[str, Any], prefix: str, fields: dict[str, Any]
    ) -> None:
        for key, value in values.items():
            fields[f"{prefix}.{key}"] = value

    @staticmethod
    def _first(nodes: Iterable[PfcpIe], ie_type: int) -> PfcpIe | None:
        return next((node for node in nodes if node.ie_type == ie_type), None)

    @staticmethod
    def _first_child(node: PfcpIe, ie_type: int) -> PfcpIe | None:
        return next((child for child in node.children if child.ie_type == ie_type), None)

    @staticmethod
    def _f_seid_role(message_type: int, direction: str) -> str:
        if message_type == 50:
            return "cp"
        if message_type == 51:
            return "up"
        if direction == "smf_to_upf":
            return "cp"
        if direction == "upf_to_smf":
            return "up"
        return "unknown"

    @staticmethod
    def _decode_record(
        node: PfcpIe,
        decoder: Callable[[bytes], dict[str, Any]],
        state: _DecodeState,
    ) -> dict[str, Any]:
        values: dict[str, Any] = {"path": "/".join(node.path)}
        try:
            values.update(decoder(node.value))
        except ValueError as exc:
            error = f"{'/'.join(node.path)}: {exc}"
            state.errors.append(error)
            values["decode_error"] = str(exc)
        return values

    @staticmethod
    def _decode_cause(value: bytes) -> dict[str, Any]:
        PfcpIeDecoder._require(value, 1, "Cause")
        code = value[0]
        if code == 0:
            category = "invalid"
        elif code < 64:
            category = "acceptance"
        else:
            category = "rejection"
        return {
            "code": code,
            "name": CAUSE_NAMES.get(code, f"Cause{code}"),
            "category": category,
            "success": code == 1,
            "partial": code == 3,
        }

    @staticmethod
    def _decode_node_id(value: bytes) -> dict[str, Any]:
        PfcpIeDecoder._require(value, 1, "Node ID")
        node_type = value[0] & 0x0F
        body = value[1:]
        if node_type == 0:
            PfcpIeDecoder._require(body, 4, "Node ID IPv4 address")
            node_id = str(IPv4Address(body[:4]))
            node_type_name = "ipv4"
        elif node_type == 1:
            PfcpIeDecoder._require(body, 16, "Node ID IPv6 address")
            node_id = str(IPv6Address(body[:16]))
            node_type_name = "ipv6"
        elif node_type == 2:
            node_id = PfcpIeDecoder._decode_dns_labels(body)
            node_type_name = "fqdn"
        else:
            raise ValueError(f"unsupported Node ID type {node_type}")
        return {"type": node_type_name, "value": node_id}

    @staticmethod
    def _decode_f_seid(value: bytes) -> dict[str, Any]:
        PfcpIeDecoder._require(value, 9, "F-SEID")
        flags = value[0]
        has_ipv4 = bool(flags & 0x02)
        has_ipv6 = bool(flags & 0x01)
        cursor = 9
        result: dict[str, Any] = {
            "seid": f"0x{int.from_bytes(value[1:9], 'big'):016x}",
            "ipv4_present": has_ipv4,
            "ipv6_present": has_ipv6,
        }
        if has_ipv4:
            PfcpIeDecoder._require(value[cursor:], 4, "F-SEID IPv4 address")
            result["ipv4"] = str(IPv4Address(value[cursor : cursor + 4]))
            cursor += 4
        if has_ipv6:
            PfcpIeDecoder._require(value[cursor:], 16, "F-SEID IPv6 address")
            result["ipv6"] = str(IPv6Address(value[cursor : cursor + 16]))
            cursor += 16
        if len(value) > cursor:
            result["extra_bytes"] = len(value) - cursor
        return result

    @staticmethod
    def _decode_f_teid(value: bytes) -> dict[str, Any]:
        PfcpIeDecoder._require(value, 1, "F-TEID")
        flags = value[0]
        has_ipv4 = bool(flags & 0x01)
        has_ipv6 = bool(flags & 0x02)
        choose = bool(flags & 0x04)
        choose_id_present = bool(flags & 0x08)
        cursor = 1
        result: dict[str, Any] = {
            "choose": choose,
            "choose_id_present": choose_id_present,
            "v4_flag": has_ipv4,
            "v6_flag": has_ipv6,
            "ipv4_present": has_ipv4 and not choose,
            "ipv6_present": has_ipv6 and not choose,
        }

        if not choose:
            PfcpIeDecoder._require(value[cursor:], 4, "F-TEID TEID")
            teid = int.from_bytes(value[cursor : cursor + 4], "big")
            result["teid"] = teid
            result["teid_hex"] = f"0x{teid:08x}"
            cursor += 4
            if has_ipv4:
                PfcpIeDecoder._require(value[cursor:], 4, "F-TEID IPv4 address")
                result["ipv4"] = str(IPv4Address(value[cursor : cursor + 4]))
                cursor += 4
            if has_ipv6:
                PfcpIeDecoder._require(value[cursor:], 16, "F-TEID IPv6 address")
                result["ipv6"] = str(IPv6Address(value[cursor : cursor + 16]))
                cursor += 16

        if choose_id_present:
            PfcpIeDecoder._require(value[cursor:], 1, "F-TEID CHOOSE ID")
            result["choose_id"] = value[cursor]
            cursor += 1
        if len(value) > cursor:
            result["extra_bytes"] = len(value) - cursor
        return result

    @staticmethod
    def _decode_network_instance(value: bytes) -> dict[str, Any]:
        if not value:
            raise ValueError("Network Instance is empty")
        try:
            decoded = PfcpIeDecoder._decode_dns_labels(value)
            encoding = "dns_labels"
        except ValueError:
            try:
                decoded = value.decode("ascii")
                encoding = "ascii"
            except UnicodeDecodeError:
                decoded = value.hex()
                encoding = "hex"
        return {"value": decoded, "encoding": encoding}

    @staticmethod
    def _decode_source_interface(value: bytes) -> dict[str, Any]:
        return PfcpIeDecoder._decode_interface(value, SOURCE_INTERFACES, "Source")

    @staticmethod
    def _decode_destination_interface(value: bytes) -> dict[str, Any]:
        return PfcpIeDecoder._decode_interface(
            value, DESTINATION_INTERFACES, "Destination"
        )

    @staticmethod
    def _decode_interface(
        value: bytes, names: dict[int, str], label: str
    ) -> dict[str, Any]:
        PfcpIeDecoder._require(value, 1, f"{label} Interface")
        code = value[0] & 0x0F
        return {"code": code, "name": names.get(code, f"Interface{code}")}

    @staticmethod
    def _decode_pdr_id(value: bytes) -> dict[str, Any]:
        PfcpIeDecoder._require(value, 2, "PDR ID")
        return {"pdr_id": int.from_bytes(value[:2], "big")}

    @staticmethod
    def _decode_far_id(value: bytes) -> dict[str, Any]:
        PfcpIeDecoder._require(value, 4, "FAR ID")
        return {"far_id": int.from_bytes(value[:4], "big")}

    @staticmethod
    def _decode_outer_header_creation(value: bytes) -> dict[str, Any]:
        PfcpIeDecoder._require(value, 2, "Outer Header Creation")
        octet5 = value[0]
        octet6 = value[1]
        cursor = 2
        names = [
            name
            for mask, name in (
                (0x01, "GTP-U/UDP/IPv4"),
                (0x02, "GTP-U/UDP/IPv6"),
                (0x04, "UDP/IPv4"),
                (0x08, "UDP/IPv6"),
                (0x10, "IPv4"),
                (0x20, "IPv6"),
                (0x40, "C-TAG"),
                (0x80, "S-TAG"),
            )
            if octet5 & mask
        ]
        result: dict[str, Any] = {
            "description_bits": f"0x{octet5:02x}{octet6:02x}",
            "description": ",".join(names) if names else "none",
            "n19_indication": bool(octet6 & 0x01),
            "n6_indication": bool(octet6 & 0x02),
            "low_layer_ssm": bool(octet6 & 0x04),
        }

        if octet5 & 0x03:
            PfcpIeDecoder._require(value[cursor:], 4, "Outer Header Creation TEID")
            teid = int.from_bytes(value[cursor : cursor + 4], "big")
            result["teid"] = teid
            result["teid_hex"] = f"0x{teid:08x}"
            cursor += 4
        if octet5 & 0x15:
            PfcpIeDecoder._require(value[cursor:], 4, "Outer Header Creation IPv4")
            result["ipv4"] = str(IPv4Address(value[cursor : cursor + 4]))
            cursor += 4
        if octet5 & 0x2A:
            PfcpIeDecoder._require(value[cursor:], 16, "Outer Header Creation IPv6")
            result["ipv6"] = str(IPv6Address(value[cursor : cursor + 16]))
            cursor += 16
        if octet5 & 0x0C:
            PfcpIeDecoder._require(value[cursor:], 2, "Outer Header Creation port")
            result["port"] = int.from_bytes(value[cursor : cursor + 2], "big")
            cursor += 2
        if octet5 & 0x40:
            PfcpIeDecoder._require(value[cursor:], 3, "Outer Header Creation C-TAG")
            result["c_tag"] = value[cursor : cursor + 3].hex()
            cursor += 3
        if octet5 & 0x80:
            PfcpIeDecoder._require(value[cursor:], 3, "Outer Header Creation S-TAG")
            result["s_tag"] = value[cursor : cursor + 3].hex()
            cursor += 3
        if len(value) > cursor:
            result["extra_bytes"] = len(value) - cursor
        return result

    @staticmethod
    def _decode_ue_ip(value: bytes) -> dict[str, Any]:
        PfcpIeDecoder._require(value, 1, "UE IP Address")
        flags = value[0]
        has_ipv6 = bool(flags & 0x01)
        has_ipv4 = bool(flags & 0x02)
        destination = bool(flags & 0x04)
        ipv6_delegation = bool(flags & 0x08)
        choose_ipv4 = bool(flags & 0x10)
        choose_ipv6 = bool(flags & 0x20)
        ipv6_prefix_length_present = bool(flags & 0x40)
        cursor = 1
        result: dict[str, Any] = {
            "role": "destination" if destination else "source",
            "choose_ipv4": choose_ipv4,
            "choose_ipv6": choose_ipv6,
            "ipv4_present": has_ipv4,
            "ipv6_present": has_ipv6,
        }
        if has_ipv4:
            PfcpIeDecoder._require(value[cursor:], 4, "UE IPv4 address")
            result["ipv4"] = str(IPv4Address(value[cursor : cursor + 4]))
            cursor += 4
        if has_ipv6:
            PfcpIeDecoder._require(value[cursor:], 16, "UE IPv6 address")
            result["ipv6"] = str(IPv6Address(value[cursor : cursor + 16]))
            cursor += 16
        if ipv6_delegation:
            PfcpIeDecoder._require(value[cursor:], 1, "IPv6 Prefix Delegation Bits")
            result["ipv6_prefix_delegation_bits"] = value[cursor]
            cursor += 1
        if ipv6_prefix_length_present:
            PfcpIeDecoder._require(value[cursor:], 1, "IPv6 Prefix Length")
            result["ipv6_prefix_length"] = value[cursor]
            cursor += 1
        if len(value) > cursor:
            result["extra_bytes"] = len(value) - cursor
        return result

    @staticmethod
    def _decode_s_nssai(value: bytes) -> dict[str, Any]:
        PfcpIeDecoder._require(value, 4, "S-NSSAI")
        sst = value[0]
        sd = value[1:4].hex()
        return {"sst": sst, "sd": sd, "value": f"{sst}-{sd}"}

    @staticmethod
    def _decode_dns_labels(value: bytes) -> str:
        labels: list[str] = []
        cursor = 0
        while cursor < len(value):
            label_length = value[cursor]
            cursor += 1
            if label_length == 0 or label_length > 63:
                raise ValueError(f"invalid DNS label length {label_length}")
            end = cursor + label_length
            if end > len(value):
                raise ValueError("DNS label extends beyond IE value")
            try:
                labels.append(value[cursor:end].decode("ascii"))
            except UnicodeDecodeError as exc:
                raise ValueError("DNS label is not ASCII") from exc
            cursor = end
        if not labels:
            raise ValueError("DNS label value is empty")
        return ".".join(labels)

    @staticmethod
    def _require(value: bytes, size: int, field_name: str) -> None:
        if len(value) < size:
            raise ValueError(
                f"{field_name} requires {size} bytes, received {len(value)}"
            )
