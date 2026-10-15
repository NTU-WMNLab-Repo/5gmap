# PFCP Compact Span Attribute Experiment

## Metadata

- Date: 2026-08-25
- Experiment start: 2026-08-25 09:37:56.046 UTC
- Experiment start: 2026-08-25 17:37:56.046 Asia/Taipei
- Jaeger capture end: 2026-08-25 09:44:41.709 UTC
- Jaeger capture end: 2026-08-25 17:44:41.709 Asia/Taipei
- Git hash under test: `53caa73` (`Compact PFCP span attributes`)
- Proxy image: `genechen0203/pfcp-udp-proxy:latest`
- Proxy image ID:
  `sha256:7288c4c5a1bd257c35e43fc6869660b2d7004ea68fd278c08a2b31f521bd4d2e`
- Topology: SMF -> `pfcpproxy10` -> UPF over N4/PFCP UDP port `8805`
- Scope: validate the compact PFCP span schema after removing duplicate and
  derived attributes, while retaining the identifiers needed for PFCP
  transaction tracing and later session-to-UE correlation.

## Objective

The selected-IE experiment on 2026-08-20 exposed an OpenTelemetry per-span
attribute limit: four Session Establishment Request spans reached 130 Jaeger
tags and lost standard transport identity fields. This experiment validates
that the compact schema:

1. removes the duplicate aliases and derived values that caused the overflow;
2. keeps every normal packet span below the 128-attribute SDK limit; and
3. retains header, transaction, F-SEID, PDR/FAR, N3 endpoint, UE IP, and timing
   fields on the live OAI traffic observed in this window.

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
start   = 1787650676046000 = 2026-08-25 09:37:56.046000 UTC
end     = 1787651081709000 = 2026-08-25 09:44:41.709000 UTC
limit   = 2000
```

The first and last returned span starts are:

```text
1787650676046589 = 2026-08-25 09:37:56.046589 UTC
1787651076203940 = 2026-08-25 09:44:36.203940 UTC
```

The first span begins 0.589 ms after the requested lower bound. Kubernetes log
commands have only a lower bound, so the raw logs include traffic after the
strict Jaeger capture window. Counts and timing statistics in this document use
only the Jaeger response.

## Trace Health

Jaeger returned 52 traces containing 208 spans. Every trace has exactly the
expected four-span transaction shape, and every non-root span has the immediate
transaction root as its parent:

```text
PFCP <procedure> transaction
  PFCP <direction> <Request>
  PFCP <direction> <Response>
  PFCP <procedure> transaction summary
```

All 52 summaries have `pfcp.transaction.state=matched`. The 104 packet spans
contain:

```text
AssociationSetupRequest / Response       = 1 / 1
HeartbeatRequest / Response              = 40 / 40
SessionEstablishmentRequest / Response   = 4 / 4
SessionModificationRequest / Response    = 4 / 4
SessionDeletionRequest / Response        = 3 / 3
total packet spans                        = 104
```

There are no `decoder.error` attributes and
`decoder.dropped_events=0` on all 104 packet spans. `pfcp.decode.status` is
absent on all 104 spans by design: successful known messages no longer emit a
redundant success status. `pfcp.ie.decode.status=no_ies` appears only on the
three header-only Session Deletion Requests; it is not a parsing failure.

## Attribute Capacity Result

The prior selected-IE run is the appropriate comparison because it used the
same PFCP proxy topology and selected IE scope. This is a schema-capacity
comparison, not a latency comparison between two independent runs.

```text
packet-span tag count              2026-08-20       2026-08-25
minimum                                  64               27
average                               73.439           30.394
maximum                                  130              54
at or above 128 attributes                4               0
```

All four current Session Establishment Request spans have 54 tags, down from
130 tags in the previous run. Thus no packet span reached the SDK attribute
limit, and all 104 packet spans retain:

```text
network.protocol.name = pfcp
network.transport = udp
pfcp.direction
pfcp.message.class
pfcp.message.name
pfcp.message.type
pfcp.message.size
pfcp.sequence_number
pfcp.version
proxy.forward.duration_ms
decoder.queue_delay_ms
decoder.duration_ms
decoder.dropped_events
pfcp.transaction.id
pfcp.transaction.state
pfcp.transaction.role
```

Each of these fields is present on 104 / 104 packet spans. This directly fixes
the four missing `network.*`, `pfcp.direction`, and `pfcp.pdu.type` cases from
the previous capture; the latter is intentionally replaced by the retained
`pfcp.message.class` field.

## Duplicate Removal Evidence

The following old forms are absent from every current packet span. The first
column records their packet-span occurrences in
`../20260820-pfcp-ie-decode/jaeger-pfcpproxy-traces.raw.json`; a value above
the prior packet-span count means a repeated IE was exported more than once in
one span.

```text
old form or namespace                         2026-08-20   2026-08-25
tracing.queue_delay_ms / tracing.dropped_events       98            0
pfcp.pdu.type                                           94            0
pfcp.procedure.name / code and pfcp.payload.size       98            0
pfcp.message.length and pfcp.s_flag                    98            0
pfcp.seid.is_zero                                       22            0
PFCP IE parser summary aliases                          98            0
pfcp.f_seid.*                                          146            0
pfcp.f_teid.*                                          170            0
pfcp.outer_header_creation.*                           134            0
pfcp.ue_ip.*                                           154            0
pfcp.network_instance.*                                 98            0
```

The numbered canonical records remain. For example,
`pfcp.node_id.0.value` and `pfcp.cause.0.name` replace the old unnumbered
aliases, while `pfcp.session.cp_f_seid.0.*` and
`pfcp.session.up_f_seid.0.*` replace generic F-SEID records. PDR and FAR child
IEs now appear only under their owning `pfcp.pdr.<index>.*` or
`pfcp.far.<index>.*` namespace. This proves that the removal targets duplicate
serialization rather than values that happened to be equal in this OAI run.

## Important Attribute Retention

All expected live-message attributes were present on every applicable span:

```text
Association Setup Request:  Node ID                         1 / 1
Association Setup Response: Cause and Node ID                1 / 1
Session Establishment Request: header SEID, CP F-SEID,
  source/destination rule direction, UE IPv4                4 / 4
Session Establishment Response: header SEID, Cause, UP F-SEID,
  Created-PDR F-TEID                                         4 / 4
Session Modification Request: header SEID, PDR/FAR direction,
  Outer Header Creation TEID and IPv4, UE IPv4               4 / 4
Session Modification Response: header SEID, Cause, PDR ID   4 / 4
Session Deletion Request / Response: header SEID;
  response Cause                                              3 / 3
```

Concrete examples from the first session procedure show the intentionally
distinct session identifiers remain visible:

```text
SessionEstablishmentRequest
  pfcp.seid                         = 0x0000000000000000
  pfcp.session.cp_f_seid.0.seid     = 0x000000000000000a
  pfcp.session.cp_f_seid.0.ipv4     = 10.42.2.94

SessionEstablishmentResponse
  pfcp.seid                         = 0x000000000000000a
  pfcp.session.up_f_seid.0.seid     = 0x0000000000000004
  pfcp.session.up_f_seid.0.ipv4     = 10.42.2.95
```

The UPF raw log corroborates the live PFCP procedures: it receives the
Association Setup request, four Session Establishment requests with header
SEID zero, and the corresponding Session Modification requests while creating
the expected FAR and PDR state. The proxy raw log records the first Association
Setup request/response at 09:37:56.048/09:37:56.051 UTC, aligned with the
first Jaeger transaction.

`pfcp.unscoped.*`, `pfcp.s_nssai.*`, and PDR/FAR Network Instance attributes
do not occur in this traffic window because the observed packets did not carry
those selected IEs. This experiment therefore establishes no live-data result
for those conditional paths; their parser coverage remains in the unit tests.

## Forwarding And Decode Timing

The following figures cover the 104 packet spans:

```text
proxy.forward.duration_ms: min=0.028594 avg=1.134889 max=4.476742
decoder.queue_delay_ms:    min=0.020721 avg=1.008155 max=9.834259
decoder.duration_ms:       min=0.035725 avg=0.212907 max=0.687824
```

Packet forwarding completes before the datagram enters the trace queue. The
queue and decoder measurements are observability work, not additional N4
forwarding overhead.

## Result

The compact schema succeeds on the observed OAI PFCP workload. It removes the
previous duplicate tag families, reduces the largest packet span from 130 to
54 tags, and leaves every checked correlation-relevant field available. No
important attribute was accidentally removed from the Association Setup,
Session Establishment, Session Modification, or Session Deletion messages in
this capture.

The next PFCP validation should exercise an unscoped selected IE, S-NSSAI, or
Network Instance so the remaining conditional namespaces are verified against
live traffic as well. The canonical schema and removal rationale are documented
in `../../src/protocols/pfcp/README.md`.
