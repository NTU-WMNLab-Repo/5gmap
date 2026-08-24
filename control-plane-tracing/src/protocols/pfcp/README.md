# PFCP Decoder Notes

This folder contains the PFCP header and selected-IE decoder used by the UDP
tracing proxy.

## Current Decoder Level

The PFCP proxy is a transparent UDP relay. It forwards each datagram before the
asynchronous tracing worker decodes the PFCP header and emits spans. The decoder
then walks the PFCP Type-Length-Value (TLV) Information Elements (IEs) and
decodes only the fields needed to describe PFCP sessions and prepare later
NGAP-PFCP correlation.

For an unbundled datagram, the worker exports one PFCP span. For a valid
`FO=1` bundled datagram, it walks every PFCP header declared by the message
length fields and exports one span for each embedded PFCP message. All spans
from the same datagram share its receive timestamp and forwarding duration,
because that is the proxy observation available before the datagram is split for
tracing.

Unlike F1AP and NGAP, PFCP is not ASN.1 PER. Its wire format is a variable
length binary header followed by zero or more PFCP IEs. The runtime light
decoder is therefore a direct byte parser in this folder, not a pycrate-based
decoder.

## PFCP Header Basis

3GPP TS 29.244 defines a variable-length PFCP header. The first four octets
are always present:

| Field | Location | Light-decoder meaning |
| --- | --- | --- |
| Version | octet 1, bits 8-6 | PFCP version; the current specification uses decimal `1`. |
| Spare | octet 1, bits 5-4 | Must be sent as zero and ignored on receipt. |
| FO | octet 1, bit 3 | `Follow On`; another PFCP message follows in the same UDP datagram when set. |
| MP | octet 1, bit 2 | Message-priority flag. The first decoder should preserve the flag but need not interpret priority. |
| S | octet 1, bit 1 | Indicates whether the 8-octet SEID field is present. |
| Message Type | octet 2 | Identifies the PFCP control-plane message. |
| Message Length | octets 3-4 | Big-endian length excluding the first four octets. |

The complete header layout depends on `S`:

| `S` | Header size | Remaining header fields |
| ---: | ---: | --- |
| `0` | 8 octets | 3-octet sequence number, then one spare octet. This is the node-related form used by the observed heartbeat and association messages. |
| `1` | 16 octets | 8-octet SEID, 3-octet sequence number, then the final header octet. This is the session-related form. |

For a PFCP message with `message_length`, its complete size is
`4 + message_length` bytes. The SEID, when present, and the sequence number
are included in this length. A decoder must not assume that a UDP datagram holds
exactly one message: when `FO=1`, it must use the first message length to locate
the next PFCP header in the same datagram.

The current OAI capture contains only `FO=0` datagrams, but the decoder already
handles a valid `FO=1` chain. A malformed chain, such as `FO=1` without a
following message or bytes after `FO=0`, is exported as a decode error and does
not affect forwarding.

The `S` flag means that a SEID field exists, not that its value is necessarily
non-zero. In particular, a Session Establishment Request may carry a present,
zero SEID because the peer's session endpoint is not known yet. Therefore a
light decoder exports `pfcp.seid` when `S=1`, including a zero SEID, rather
than treating zero as an invalid parse. A separate `pfcp.s_flag` would merely
duplicate the presence or absence of that field, so it is not emitted.

## Observed OAI Message Mapping

The 2026-08-14 full-path capture observed these first-two-octet combinations.
`0x20` is PFCP version 1 with `S=0`; `0x21` is PFCP version 1 with `S=1`.

| Header prefix | Message type | PFCP message | Observed direction |
| --- | ---: | --- | --- |
| `20 01` | `1` | Heartbeat Request | SMF to UPF |
| `20 02` | `2` | Heartbeat Response | UPF to SMF |
| `20 05` | `5` | Association Setup Request | SMF to UPF |
| `20 06` | `6` | Association Setup Response | UPF to SMF |
| `21 32` | `50` | Session Establishment Request | SMF to UPF |
| `21 33` | `51` | Session Establishment Response | UPF to SMF |
| `21 34` | `52` | Session Modification Request | SMF to UPF |
| `21 35` | `53` | Session Modification Response | UPF to SMF |
| `21 36` | `54` | Session Deletion Request | SMF to UPF |
| `21 37` | `55` | Session Deletion Response | UPF to SMF |

These values agree with TS 29.244 Table 7.3-1. The capture contained one
Association Setup exchange, 27 heartbeat exchanges, two session
establishment/modification exchanges, and one session deletion exchange. This
is enough to validate the initial header map, but it does not make direction a
safe substitute for the message-type field: later node reports and session
reports can originate from the UPF.

## Selected IE Decode Basis

Every 3GPP-defined PFCP IE starts with a two-octet type and a two-octet length;
the length excludes that four-octet IE header. Grouped IEs contain another TLV
sequence in their value. The runtime walker is bounded to eight grouped levels
and 4096 total IEs per PFCP message. It recursively enters only grouped IE types
that this project needs and skips unsupported values by their declared length.
It exports at most 64 records per selected category and sets
`pfcp.ie.attributes.truncated=true` when that bound is exceeded. It never exports
the complete IE value or raw PFCP payload.

The selected fields follow TS 29.244:

| IE or grouped path | Type | Decoded information | Purpose |
| --- | ---: | --- | --- |
| `Cause` | `19` | code and name | Procedure result. |
| `Node ID` | `60` | IPv4, IPv6, or DNS-label FQDN | PFCP association peer. |
| `F-SEID` | `57` | SEID and endpoint IPv4/IPv6 address | CP/UP PFCP-session endpoints. |
| `Create/Created/Update/Remove PDR` | `1/8/9/15` | operation, PDR ID, referenced FAR ID, and nested PDI fields | PFCP rule identity and direction. |
| `Source Interface` | `20` | interface code and name | Distinguishes access/core-side incoming traffic. |
| `F-TEID` | `21` | CH/CHID allocation request, TEID, and IPv4/IPv6 endpoint | Local N3/N9 tunnel endpoint or allocation request. |
| `Create/Update/Remove FAR` | `3/10/16` | operation, FAR ID, and nested forwarding fields | Outgoing rule identity. |
| `Destination Interface` | `42` | interface code and name | Distinguishes access/core-side outgoing traffic. |
| `Outer Header Creation` | `84` | header description, GTP-U TEID, destination IP, and applicable UDP/VLAN fields | Peer N3/N9 tunnel endpoint. |
| `UE IP Address` | `93` | source/destination role, IPv4/IPv6, and CHOOSE/prefix data when present | Supporting session evidence. |
| `Network Instance` | `22` | decoded APN/DNN labels, with ASCII/hex fallback | Supporting DNN scope. |
| `S-NSSAI` | `257` | SST and SD | Supporting slice scope. |

The walker also enters Create/Created/Update/Remove Traffic Endpoint grouped IEs
so these selected child values remain observable when a peer uses PDI
optimization. Complete Traffic Endpoint semantics are not implemented.

Malformed IE data is isolated from header decoding. A span receives
`pfcp.ie.decode.status=partial` or `malformed` and a bounded
`pfcp.ie.decode.error`, while the valid message type and sequence number remain
available to PFCP transaction correlation. Forwarding has already completed by
this point.

## Span Attribute Profile

The implementation parses and validates the PFCP header and selected IEs after
the datagram has already been forwarded. The span schema is intentionally
compact. In the 2026-08-20 selected-IE experiment, four Session Establishment
Request spans reached 130 Jaeger tags and lost standard proxy attributes. The
Python OpenTelemetry SDK default is 128 span attributes, so the earlier schema
could evict useful header or timing data when the same IE was exported through
more than one namespace.

The compact schema removes only exact duplicate representations. It does not
merge fields merely because their values happened to match in the current OAI
capture. In particular, these remain distinct facts:

- `pfcp.seid` is the PFCP header's receiver-side session endpoint identifier.
- `pfcp.session.cp_f_seid.<index>.seid` and
  `pfcp.session.up_f_seid.<index>.seid` are F-SEID IE values advertised by the
  control-plane and user-plane peers respectively.
- `pfcp.message.size` is the embedded PFCP message size; `pfcp.datagram.size`
  remains available for a PFCP bundle or malformed datagram, where it can differ.

### Header And Decoder Fields

Normal decoded messages emit these canonical fields:

```text
pfcp.version
pfcp.message.type
pfcp.message.name
pfcp.message.class
pfcp.message.size
pfcp.sequence_number
pfcp.seid                         # only when S=1; zero is preserved
```

The following fields appear only when their non-default or diagnostic meaning
matters:

```text
pfcp.fo_flag                       # only when FO=1
pfcp.mp_flag                       # only when MP=1
pfcp.message.priority              # only when MP=1 and S=1
pfcp.message.offset
pfcp.message.index
pfcp.datagram.size
pfcp.datagram.message.count
pfcp.datagram.bundled              # all four are emitted for a valid bundle
pfcp.decode.status                 # unknown version/type or malformed header
pfcp.ie.decode.status              # no IEs, malformed, or partial IE parse
pfcp.ie.decode.error
pfcp.ie.count                      # IE parser error context
pfcp.ie.unsupported.count          # only when nonzero
pfcp.ie.attributes.truncated
```

`pfcp.message.length`, `pfcp.s_flag`, and `pfcp.seid.is_zero` are omitted
because they are exactly derivable from the canonical fields. A successful IE
parse emits no generic `decoded` status. Likewise, false flag values are not
exported: absence means the corresponding flag was not set. Malformed messages
retain offset/index diagnostics even when they are not bundled.

At span export, `pfcp.message.class`, `pfcp.message.name`,
`pfcp.message.type`, and `pfcp.message.size` replace the parallel generic
`pfcp.pdu.type`, `pfcp.procedure.name`, `pfcp.procedure.code`, and
`pfcp.payload.size` forms. `decoder.queue_delay_ms`, `decoder.duration_ms`,
and `decoder.dropped_events` are the canonical asynchronous-observability
fields; the old duplicate `tracing.*` queue/drop fields are not emitted.

### Selected IE Fields

Repeated values remain numbered; a `.count` appears only when the corresponding
record set is nonempty. The canonical record paths are:

```text
pfcp.node_id.<index>.*
pfcp.cause.<index>.*
pfcp.session.cp_f_seid.<index>.*
pfcp.session.up_f_seid.<index>.*
pfcp.unscoped.f_seid.<index>.*
pfcp.pdr.<index>.pdr_id
pfcp.pdr.<index>.far_id
pfcp.pdr.<index>.source_interface.*
pfcp.pdr.<index>.f_teid.<index>.*
pfcp.pdr.<index>.ue_ip.<index>.*
pfcp.pdr.<index>.network_instance.<index>.*
pfcp.far.<index>.far_id
pfcp.far.<index>.destination_interface.*
pfcp.far.<index>.outer_header_creation.<index>.*
pfcp.far.<index>.network_instance.<index>.*
pfcp.unscoped.f_teid.<index>.*
pfcp.unscoped.outer_header_creation.<index>.*
pfcp.unscoped.ue_ip.<index>.*
pfcp.unscoped.network_instance.<index>.*
pfcp.s_nssai.<index>.*
```

An F-TEID, Outer Header Creation, UE IP Address, or Network Instance nested in
a PDR or FAR is emitted only through that PDR/FAR path. The old generic
`pfcp.f_teid.*`, `pfcp.outer_header_creation.*`, `pfcp.ue_ip.*`, and
`pfcp.network_instance.*` aliases are therefore removed. The `pfcp.unscoped.*`
namespace keeps selected values that are not owned by a PDR or FAR, such as a
Traffic Endpoint child IE.

The old unnumbered first-record aliases for Cause, Node ID, and CP/UP F-SEID are
also removed. `path`, `teid_hex`, address-presence booleans, Cause
success/category booleans, and `S-NSSAI.value` are omitted because they are
either encoded by the canonical key/value or exactly derived from it. PDR
F-TEIDs observed on the Access source interface are still marked
`endpoint_role=upf_n3_ingress`; Created PDR local F-TEIDs are marked
`upf_local`; FAR Outer Header Creation values targeting Access are marked
`ran_n3_egress`.

The UDP worker exports low-priority selected fields first, then emits PFCP
header, first-rule and primary unscoped records, UDP-peer, transaction, core
network, forwarding, and timing attributes last. This makes an SDK attribute
cap discard extra IE detail before the fields needed to interpret or correlate
the span. It does not affect packet forwarding or PFCP transaction matching.

Known message types receive their TS 29.244 request/response names. An unknown
message type still receives an `UnknownMessageType<N>` span. A truncated header,
impossible declared length, or malformed `FO` chain receives a
`MalformedDatagram` span with `decoder.error`. A malformed message remains a
tracing concern only and never delays or prevents forwarding.

The current decoder deliberately excludes:

- complete decoding of every PFCP IE and vendor-specific IE value;
- persistent reconstruction of PDR/FAR state across modification messages;
- NGAP/F1AP cross-protocol UE correlation;
- exporting complete raw PFCP payloads to Jaeger.

PFCP request/response transaction correlation and retransmission detection are
implemented from the decoded header fields. The worker groups a request,
identical request retransmissions, and a matching response into one trace using
the scoped sequence number and observed UDP peers. See
`../../correlator/pfcp-transaction.md` for state, timeout, trace-shape, and
attribute details.

Selected IE decoding does not change transaction matching. Request/response
matching still uses the scoped header sequence number and observed peers; IE
values are span evidence for later session-state and cross-protocol work.

## Reliable Delivery And Transaction Retention

TS 29.244 clause 6.4 requires a sender to retain a request until it receives a
matching response or stops retransmitting. A response uses the same sequence
number, while retransmitted requests retain the original message content and
header. The relevant sequence number is unique only among outstanding requests
for the relevant sender IP address, sender UDP port, and remote PFCP peer; it is
not a globally unique packet ID.

The same clause defines `T1` and `N1` as implementation-specific. It supplies
no universal retry timer or retry count that a proxy can hard-code. Therefore
the proxy uses a configurable inactivity timeout after the most recent request
or retransmission, plus a short closed-state retention period for late duplicate
traffic. Those proxy values are not protocol-defined `T1`/`N1` values. Their
defaults and the rationale for closing on a matching response are documented in
`../../correlator/pfcp-transaction.md`.

## Planned Decode Path

Recommended implementation order:

1. Validate the selected IE values against live SMF/UPF logs and raw PFCP
   messages, especially both N3 endpoint tuples.
2. Run an offline NGAP-PFCP experiment that rejects ambiguous or incomplete N3
   tuple matches before adding any online binding state.
3. Add PFCP-session state keyed by the CP/UP F-SEIDs so PDR/FAR modifications
   can update rather than replace the observed rule set.
4. Capture or generate a real `FO=1` PFCP bundle and a retransmission/loss case
   to validate the already implemented bundle and transaction paths.

## Python Decoder Choice

The runtime light decoder uses direct Python byte parsing and no new dependency.
It parses the fixed header, walks bounded TLVs, and decodes only the selected IE
values above. Unsupported values are skipped without constructing a complete
PFCP object tree.

Two useful tools remain available for later full or offline decoding:

- Scapy provides `scapy.contrib.pfcp`, including PFCP header and many IE
  dissectors. It is useful for packet inspection and validation, but is broader
  than this proxy's selected runtime path.
- pycrate includes a `TS29244_PFCP` module. It is a candidate when the project
  needs a complete structured PFCP representation rather than the bounded
  selected fields exported here.

Neither tool is required in the proxy image.

## References

- 3GPP TS 29.244 specification record:
  https://portal.3gpp.org/desktopmodules/Specifications/SpecificationDetails.aspx?specificationId=3111
- ETSI publication of 3GPP TS 29.244 v19.5.0, clauses 7.2.1A, 7.2.2, 7.3.1,
  7.5, and 8.2 (PFCP message format, grouped session IEs, and IE encodings):
  https://www.etsi.org/deliver/etsi_ts/129200_129299/129244/19.05.00_60/ts_129244v190500p.pdf
- ETSI publication of 3GPP TS 29.244 v19.4.0, clause 6.4 (reliable delivery,
  sequence number scope, retransmission, and implementation-specific `T1` and
  `N1`):
  https://www.etsi.org/deliver/etsi_ts/129200_129299/129244/19.04.00_60/ts_129244v190400p.pdf
- 3GPP TS 29.244 archive:
  https://www.3gpp.org/ftp/Specs/archive/29_series/29.244/
- Scapy PFCP dissector:
  https://scapy.readthedocs.io/en/stable/api/scapy.contrib.pfcp.html
- Scapy PFCP dissector source, used as a second implementation reference for
  IE type assignments and bit-field ordering:
  https://github.com/secdev/scapy/blob/master/scapy/contrib/pfcp.py
- pycrate package information:
  https://pypi.org/project/pycrate/
- Full-path OAI validation record:
  `../../../experiments/20260814-pfcp-proxy-full-path/README.md`
- Selected-IE validation record:
  `../../../experiments/20260820-pfcp-ie-decode/README.md`
