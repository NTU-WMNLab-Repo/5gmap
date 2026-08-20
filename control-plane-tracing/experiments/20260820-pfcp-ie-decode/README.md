# PFCP Selected IE Decode Experiment

## Metadata

- Date: 2026-08-20
- Experiment start: 2026-08-20 13:10:22.892 UTC
- Experiment start: 2026-08-20 21:10:22.892 Asia/Taipei
- Jaeger capture end: 2026-08-20 13:16:35.671509 UTC
- Jaeger capture end: 2026-08-20 21:16:35.671509 Asia/Taipei
- Git hash under test: `323cfdb` (`Add selected PFCP IE decoding`)
- Proxy image: `genechen0203/pfcp-udp-proxy:latest`
- Proxy image ID:
  `sha256:9abf47d311f2d24ce5a881327b2ebc52fc6d8df132f79136f336ab0401b0e304`
- Topology: SMF -> `pfcpproxy10` -> UPF over N4/PFCP UDP port `8805`
- Scope: validate bounded selected-PFCP-IE decoding while retaining the existing
  asynchronous UDP relay and PFCP request/response transaction traces.

## Objective

Validate that the live proxy decodes the selected Information Elements needed
for future session-to-UE correlation without modifying a PFCP payload or
blocking its forwarding path. The validation focuses on:

1. Association Node ID and Cause;
2. session CP/UP F-SEID values;
3. PDR/FAR source and destination interfaces;
4. UE IPv4 address, F-TEID, and Outer Header Creation N3 endpoint; and
5. agreement between Jaeger attributes, raw proxy datagram prefixes, and OAI
   SMF/UPF logs.

## Raw Evidence

- `jaeger-pfcpproxy-traces.raw.json`: unmodified Jaeger API response for the
  strict capture window.
- `pfcp-proxy-log.raw.txt`: unmodified proxy log collected with the stated
  lower bound.
- `smf-log.raw.txt` and `upf-log.raw.txt`: unmodified endpoint logs collected
  with the same lower bound.
- `pfcp-proxy-deployment.raw.yaml` and `pfcp-proxy-pod.raw.yaml`: deployed
  proxy configuration, image, and runtime state.
- `oai-pods.raw.txt`: pod snapshot collected with the other evidence.

The Jaeger query was:

```text
service = pfcpproxy10
start   = 1787231422892000 = 2026-08-20 13:10:22.892000 UTC
end     = 1787231795671509 = 2026-08-20 13:16:35.671509 UTC
limit   = 2000
```

The first and last returned span starts are:

```text
1787231422892225 = 2026-08-20 13:10:22.892225 UTC
1787231793032297 = 2026-08-20 13:16:33.032297 UTC
```

The first span begins 0.225 ms after the requested lower bound. Kubernetes log
commands use only a lower bound, so the raw logs include a small amount of
traffic after the strict Jaeger capture window. Counts and timing statistics in
this document use only the Jaeger response.

## Transaction And Decode Health

Jaeger returned 49 complete PFCP transaction traces, containing 196 spans. All
49 traces have the expected four-span shape:

```text
PFCP <procedure> transaction
  PFCP <direction> <Request>
  PFCP <direction> <Response>
  PFCP <procedure> transaction summary
```

Every summary is `pfcp.transaction.state=matched`; each request/response pair
has one transaction ID and matching sequence number. The packet message counts
are:

```text
AssociationSetupRequest / Response       = 1 / 1
HeartbeatRequest / Response              = 37 / 37
SessionEstablishmentRequest / Response   = 4 / 4
SessionModificationRequest / Response    = 4 / 4
SessionDeletionRequest / Response        = 3 / 3
total packet spans                        = 98
```

All 98 packet spans have `pfcp.decode.status=header_decoded` and no
`decoder.error`. Selected IE traversal reports:

```text
pfcp.ie.decode.status=decoded  = 95
pfcp.ie.decode.status=no_ies   = 3  (the SessionDeletionRequest messages)
pfcp.ie.decode.error           = 0
tracing.dropped_events         = 0 on every packet span
decoder.dropped_events         = 0 on every packet span
```

`no_ies` is expected for these header-only Session Deletion Requests. It is not
a parsing failure.

## IE Decode Evidence

### Association Setup

The first proxy datagrams are an Association Setup request and response:

```text
13:10:22.895  smf_to_upf  20 05 ...  AssociationSetupRequest
13:10:22.898  upf_to_smf  20 06 ...  AssociationSetupResponse
```

The request span decodes `pfcp.node_id.value=oai-smf`. The response decodes
`pfcp.cause.name=RequestAccepted` and
`pfcp.node_id.value=pfcpproxy10`. The latter is the configured Node ID that the
UPF advertises for this proxy topology; it is not an inferred physical UPF pod
name. The SMF log records the matching N4 Association Setup Response at
13:10:22.898 UTC.

### Session Establishment

All four Session Establishment Requests decode the following consistent
structure:

```text
PFCP header SEID                    = 0x0000000000000000
pfcp.session.cp_f_seid.seid         = 0x1, 0x4, 0x7, 0xa
pfcp.session.cp_f_seid.ipv4         = 10.42.2.73
PDR source interface                = Access
FAR destination interface           = Core
PDR F-TEID                           = CHOOSE=true, CHOOSE ID=42
UE IPv4 address                     = 12.1.1.2
```

The matching responses decode:

```text
PFCP header SEID                    = 0x1, 0x4, 0x7, 0xa
pfcp.session.up_f_seid.seid         = 0x1, 0x2, 0x3, 0x4
pfcp.session.up_f_seid.ipv4         = 10.42.2.74
Created-PDR F-TEID                  = TEID 1, 2, 3, 4 at 10.42.2.74
Cause                               = RequestAccepted
```

The UPF log independently records four establishment requests with header
SEID zero, then creates FAR and PDR state for UPF session SEIDs 1 through 4.
The SMF log records the same UE IPv4 address and the response sender values
`0x1`, `0x4`, `0x7`, and `0xa`. This is consistent with the decoder's separate
CP F-SEID and UP F-SEID fields.

### Session Modification And N3 Endpoint

Each of the four Session Modification Requests uses the UP F-SEID in its PFCP
header (`0x1` through `0x4`) and decodes:

```text
PDR ID / FAR ID                     = 2 / 2
PDR source interface                = Core
FAR destination interface           = Access
Outer Header Creation               = GTP-U/UDP/IPv4
Outer Header Creation IPv4          = 10.42.1.186
Outer Header Creation endpoint role = ran_n3_egress
UE IPv4 address                     = 12.1.1.2
```

The decoded N3 TEIDs are exactly the values the SMF logs as
`DL GTP F-TEID (AN F-TEID)`:

```text
0x48f6604f
0x27db1f25
0x638e5670
0xb93bce17
```

The pod snapshot identifies `10.42.1.186` as the CU pod IP, which is the
expected RAN-side N3 target in this integrated CU deployment. The UPF log also
records one FAR and one PDR addition for each Session Modification Request.
All four responses have `Cause=RequestAccepted` and return `CreatedPDR` ID 2.

The three Session Deletion request/response pairs use the expected UP and CP
header SEIDs respectively, and every response has `Cause=RequestAccepted`.
This confirms that session state is still released after selected IE decoding
is enabled.

## Attribute Capacity Finding

The selected IE values above are decoded correctly, but this experiment reveals
an exporter-capacity issue that must be fixed before treating every span as a
complete queryable record. The live proxy's OpenTelemetry SDK reports
`SpanLimits().max_attributes=128`.

Each of the four `SessionEstablishmentRequest` spans reaches this budget and
has 130 Jaeger tags after Jaeger-added instrumentation tags are included. These
four spans retain the decoded CP F-SEID, PDR/FAR, F-TEID, UE IP, transaction ID,
and timing fields, but lack these standard attributes:

```text
network.protocol.name
network.transport
pfcp.direction
pfcp.pdu.type
```

The direction remains visible in the operation name
`PFCP smf_to_upf SessionEstablishmentRequest`, so this capture is still
unambiguous. However, consumers must not rely on parsing operation names.
The next implementation change should reserve the standard transport and PFCP
identity attributes, then compact or cap repeated detailed IE attributes before
the OpenTelemetry span limit is reached. This is an attribute-export issue,
not an IE parsing error.

## Forwarding And Decode Timing

The following figures cover all 98 packet spans:

```text
proxy.forward.duration_ms: min=0.019630 avg=1.132876 max=3.576457
decoder.queue_delay_ms:    min=0.034197 avg=1.163441 max=10.853328
decoder.duration_ms:       min=0.072804 avg=0.261238 max=0.836228
```

The new selected-IE decode time is higher than the earlier header-only decode,
as expected, but packet forwarding completes before the datagram enters the
trace queue. Queue delay and decode time are therefore observability work, not
additional N4 forwarding latency. The 49 matched transactions have a
proxy-observed request-to-response interval of 1.276561 to 5.937453 ms, with
an average of 3.501537 ms.

## Result

The selected PFCP IE decoder is semantically consistent with this live OAI N4
run. It correctly exposes the CP and UP session identifiers, UE IPv4 address,
UPF F-TEIDs, RAN N3 endpoint, and PDR/FAR direction needed for later PFCP to
NGAP correlation. Proxy forwarding and the existing PFCP transaction traces
remain healthy.

The experiment also exposes the 128-attribute span limit for the largest
Session Establishment Request. Addressing that export limit is the necessary
next correction before using these spans as the canonical online correlation
input.
