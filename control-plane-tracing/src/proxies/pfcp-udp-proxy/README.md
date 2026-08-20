# PFCP UDP Tracing Proxy

## Prototype Status

This PFCP proxy is a transparent UDP relay between an SMF and a UPF. It
forwards each original datagram before enqueueing observability work, then
performs PFCP header and selected-IE light decode asynchronously.

The decoder exports PFCP version, flags, message type and name, message length,
sequence number, and SEID when present. It also walks bounded PFCP TLVs and
exports Cause, Node ID, CP/UP F-SEID, PDR/FAR identity and direction, N3
F-TEID/Outer Header Creation endpoints, UE IP, Network Instance, and S-NSSAI.
Request/response transaction correlation is enabled: a request, its identical
retransmissions, and its matching response share one trace. UE and
cross-protocol trace relationships are not implemented yet.

One forwarded UDP datagram normally produces one span. If the datagram contains
a valid `FO=1` PFCP bundle, the worker emits one span for every embedded PFCP
message without changing the original datagram before forwarding.

## Traffic Path

```text
SMF -> PFCP UDP tracing proxy -> UPF
UPF -> PFCP UDP tracing proxy -> SMF
```

The proxy owns UDP port `8805` and uses the same bound socket for both outgoing
directions. The SMF sees the proxy as its PFCP peer; the UPF replies to that
same proxy socket. The proxy records the observed SMF address and uses it for
UPF responses. `SMF_HOST` is a fallback only until the first SMF datagram is
observed.

With `RanProxy=1`, the deployment script temporarily sets the SMF's static
UPF endpoint to the `pfcpproxy<slice>` ClusterIP and disables SMF UPF discovery.
It also configures the UPF to advertise `pfcpproxy<slice>` as its
`UPF_FQDN_5G` Node ID. OAI SMF learns that FQDN from PFCP Association Setup
Response and resolves it before later heartbeat and session procedures, so this
keeps response-driven traffic on the proxy path without payload rewriting.

The proxy's `UPF_HOST` remains the real `oai-spgwu-tiny<slice>-svc` headless
service. With `RanProxy=0`, the script removes the proxy, clears the SMF static
endpoint, re-enables original SMF UPF discovery, and restores the UPF-advertised
FQDN to `oai-spgwu-tiny<slice>-svc`.

## Span Semantics

The span name is one of:

```text
PFCP smf_to_upf AssociationSetupRequest
PFCP upf_to_smf AssociationSetupResponse
PFCP smf_to_upf SessionEstablishmentRequest
```

Every span includes `network.transport=udp`, `pfcp.direction`, UDP
source/destination addresses and ports, `proxy.forward.duration_ms`,
`tracing.queue_delay_ms`, and `tracing.dropped_events`. Header-decoded spans
also include:

```text
pfcp.version
pfcp.fo_flag
pfcp.mp_flag
pfcp.s_flag
pfcp.message.type
pfcp.message.name
pfcp.message.length
pfcp.message.size
pfcp.sequence_number
pfcp.seid                 # present only when S=1
pfcp.message.index
pfcp.datagram.message.count
pfcp.datagram.bundled
```

Selected IE attributes are emitted as numbered records, including:

```text
pfcp.ie.decode.status
pfcp.node_id.<index>.*
pfcp.cause.<index>.*
pfcp.session.cp_f_seid.*
pfcp.session.up_f_seid.*
pfcp.pdr.<index>.*
pfcp.far.<index>.*
pfcp.f_teid.<index>.*
pfcp.outer_header_creation.<index>.*
pfcp.ue_ip.<index>.*
pfcp.network_instance.<index>.*
pfcp.s_nssai.<index>.*
```

See [`../../protocols/pfcp/README.md`](../../protocols/pfcp/README.md) for the
exact IE scope, nesting, endpoint-role attributes, and specification basis.

`pfcp.payload.size` is the individual PFCP message size; `pfcp.datagram.size`
is the original UDP datagram size. For a bundle, every child message span starts
when the proxy receives the shared UDP datagram and ends when it finishes
forwarding that datagram. Queue and decoder timing are therefore common
observability costs, not added forwarding overhead.

No raw datagram payload or unsupported IE value is sent to Jaeger. Unknown
message types still receive header-decoded spans. Malformed header or bundle
data is reported through `decoder.error`; malformed selected IE data is isolated
under `pfcp.ie.decode.*`. Neither condition affects forwarding, and an IE error
does not discard valid header fields used by transaction correlation.

For supported PFCP request/response pairs, the proxy immediately exports a
`PFCP <procedure> transaction` root, then makes the packet spans children of
that root. A matching response exports a `PFCP <procedure> transaction summary`
child with `pfcp.transaction.observed_duration_ms`. The immediate root is a
trace anchor, not request/response latency; packet spans still show only the
receive-to-forwarding duration.

Message spans receive `pfcp.transaction.id`, `pfcp.transaction.state`,
`pfcp.transaction.role`, `pfcp.transaction.attempt`, and
`pfcp.transaction.retransmission`. Matching responses also receive
`pfcp.transaction.response.matched=true`. A short closed tombstone keeps the
same trace parent for late duplicate UDP messages without retaining an active
request indefinitely. Detailed matching and timeout behavior is in
[`../../correlator/pfcp-transaction.md`](../../correlator/pfcp-transaction.md).

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `UPF_HOST` | `oai-spgwu-tiny` | Real UPF service behind the proxy. |
| `UPF_PORT` | `8805` | Real UPF PFCP UDP port. |
| `SMF_HOST` | `oai-smf` | SMF service used before a datagram reveals its source. |
| `SMF_PORT` | `8805` | SMF PFCP UDP port. |
| `LISTEN_HOST` | `0.0.0.0` | Local UDP bind address. |
| `LISTEN_PORT` | `8805` | Local PFCP UDP bind port. |
| `OTEL_SERVICE_NAME` | `pfcp-udp-proxy` | OpenTelemetry service name. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Optional OTLP gRPC endpoint. |
| `LOG_HEX_BYTES` | `0` | Bytes of payload hex to print in logs; not exported as a span attribute. |
| `TRACE_QUEUE_SIZE` | `10000` | Async raw-span queue depth. |
| `PFCP_MAX_DATAGRAM_BYTES` | `65535` | Maximum UDP receive size. |
| `PFCP_DNS_REFRESH_SECONDS` | `5` | UPF/SMF service DNS refresh interval. |
| `PFCP_TRANSACTION_TIMEOUT_MS` | `30000` | Idle time after the most recent request or retransmission before the proxy closes active transaction state. |
| `PFCP_TRANSACTION_CLOSED_RETENTION_MS` | `5000` | Closed-state retention for late duplicate requests or responses. |
| `PFCP_TRANSACTION_MAX_CONTEXTS` | `10000` | Maximum active transactions and maximum retained closed tombstones; the oldest active state is force-closed. |

## Container

Build and push the PFCP image independently from F1AP and NGAP:

```sh
IMAGE=docker.io/genechen0203/pfcp-udp-proxy:latest

cd control-plane-tracing/src
docker login
docker build -f proxies/pfcp-udp-proxy/Dockerfile -t "$IMAGE" .
docker push "$IMAGE"
```

For an amd64 lab cluster when building on another architecture:

```sh
IMAGE=docker.io/genechen0203/pfcp-udp-proxy:latest

cd control-plane-tracing/src
docker login
docker buildx build --platform linux/amd64 \
  -f proxies/pfcp-udp-proxy/Dockerfile \
  -t "$IMAGE" \
  --push .
```
