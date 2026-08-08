# Online Cross-Protocol Correlator

## Purpose

The online correlator is a lightweight HTTP state service for assigning one
OpenTelemetry trace ID to the same UE control-plane lifecycle across F1AP and
NGAP proxy pods.

It does not forward packets, decode ASN.1, export spans, or store full decoded
payloads. The F1AP and NGAP proxies still export the complete spans themselves.
The correlator only receives a compact UE-correlation envelope and returns the
trace identity that the proxy should use before exporting the span.

The first version does not export a synthetic UE lifecycle root span. Proxies
use the returned trace ID and parent span ID as a remote parent context so F1AP
and NGAP spans appear in the same Jaeger trace. A later version can add an
explicit root span if the trace tree needs a visible lifecycle parent.

This service belongs under `src/correlator/online/` because it is shared
cross-protocol correlation state. Protocol-local correlators remain in
`src/correlator/f1ap.py` and `src/correlator/ngap.py`.

## API

### `POST /v1/events`

Mutates state and returns the current online UE lifecycle decision.

Example F1AP input:

```json
{
  "service_name": "f1proxy10",
  "protocol": "f1ap",
  "local_correlation_id": "f1ap-ue-du-30295",
  "direction": "du_to_cu",
  "message_name": "InitialULRRCMessageTransfer",
  "procedure_name": "InitialULRRCMessageTransfer",
  "event_time_unix_ns": 1785854817535227000,
  "ids": {
    "du_id": 30295,
    "cu_id": null,
    "c_rnti": 30295
  },
  "release_complete": false
}
```

Example NGAP input:

```json
{
  "service_name": "ngapproxy10",
  "protocol": "ngap",
  "local_correlation_id": "ngap-ue-ran-1-gen-1",
  "direction": "cu_to_amf",
  "message_name": "InitialUEMessage",
  "procedure_name": "InitialUEMessage",
  "event_time_unix_ns": 1785854817544022920,
  "ids": {
    "ran_id": 1,
    "amf_id": null,
    "generation": 1
  },
  "release_complete": false
}
```

The proxy sends only the correlation envelope. It does not send `asn1.value`,
RRC containers, NAS payloads, or the SCTP payload bytes.

Return body:

```json
{
  "trace_id": "128-bit lowercase hex trace ID",
  "parent_span_id": "64-bit lowercase hex parent span ID",
  "ue_correlation_id": "ue-online-00000001",
  "state": "pending",
  "confidence": "local",
  "linked_protocols": ["f1ap"],
  "close_reason": null,
  "local_correlation_id": "f1ap-ue-du-30295",
  "local_state": "pending",
  "first_seen_unix_ns": 1785854817535227000,
  "last_seen_unix_ns": 1785854817535227000
}
```

`buffer_decision` is intentionally not returned. The proxy worker owns buffering
policy because buffering is a local export concern. The correlator only returns
the best current state and trace identity.

### `POST /v1/resolve`

Reads current state for a protocol-local lifecycle without incrementing message
counters or creating new state. Proxy workers use this when a buffered span is
about to be exported after its local buffer timeout.

The request body has the same shape as `/v1/events`.

### `GET /healthz`

Returns:

```json
{"status":"ok"}
```

### `GET /v1/state`

Returns a debug snapshot of the in-memory tables. This is intended for lab
debugging and should not be used on a hot path.

## Internal Tables

The correlator stores three groups of in-memory state.

### F1AP Local Lifecycle Table

Keyed by `f1ap.ue.correlation_id` when available, otherwise by a fallback key
derived from DU UE ID, C-RNTI, or CU UE ID.

Stored fields:

- local correlation ID;
- linked global UE lifecycle ID;
- first and last seen timestamps;
- observed F1AP IDs: DU UE ID, CU UE ID, C-RNTI;
- message counters;
- first and last timestamp per message name;
- release-complete flag.

### NGAP Local Lifecycle Table

Keyed by `ngap.ue.correlation_id` when available, otherwise by RAN UE NGAP ID,
AMF UE NGAP ID, and generation when present.

Stored fields:

- local correlation ID;
- linked global UE lifecycle ID;
- first and last seen timestamps;
- observed NGAP IDs: RAN UE NGAP ID, AMF UE NGAP ID, generation;
- message counters;
- first and last timestamp per message name;
- release-complete flag.

### Global UE Lifecycle Table

Keyed by `ue-online-NNNNNNNN`.

Stored fields:

- canonical `trace_id`;
- synthetic `parent_span_id` used by proxies as a remote parent context;
- lifecycle state;
- linked F1AP local lifecycle keys;
- linked NGAP local lifecycle keys;
- first and last seen timestamps;
- close reason.

The service is in-memory and single-replica in this first version. If the
correlator pod restarts, new UE lifecycle trace IDs will be allocated after the
restart. A future multi-CU or HA version should put this state in Redis or an
equivalent shared store.

## Matching Logic

The first version uses the evidence validated by the offline analyzer:

```text
F1AP CU UE F1AP ID == NGAP RAN UE NGAP ID
AND
F1AP InitialULRRCMessageTransfer precedes NGAP InitialUEMessage
within ONLINE_CORRELATION_INITIAL_GAP_MS
```

Lifecycle time overlap adds supporting evidence, and release-complete alignment
adds a small score when both releases are observed.

CU UE ID and RAN UE NGAP ID equality is strong evidence in the current OAI
deployment, but it is not treated as a portable 3GPP guarantee. Timing is kept
as an independent required signal for a high-confidence match.

## Proxy Buffering Flow

The proxy worker only enters the online buffer for UE-related decoded events.

F1AP UE-related condition:

- `f1ap.ue.correlation_id`;
- `f1ap.ue.du_id`;
- `f1ap.ue.cu_id`;
- `f1ap.ue.c_rnti`;
- `f1ap.gnb.du.ue.f1ap.id`;
- `f1ap.gnb.cu.ue.f1ap.id`;
- `f1ap.c.rnti`.

NGAP UE-related condition:

- `ngap.ue.correlation_id`;
- `ngap.ue.ran_id`;
- `ngap.ue.amf_id`;
- `ngap.ue.context_generation`;
- `ngap.ran.ue.ngap.id`;
- `ngap.amf.ue.ngap.id`.

Node-level messages such as F1 setup or NG setup do not enter the online buffer
and continue to be exported immediately.

Flow:

```text
1. Proxy forwards SCTP payload immediately.
2. Async worker decodes the copied payload.
3. Protocol-local correlator emits F1AP or NGAP UE attributes.
4. If no UE ID/correlation attribute exists, export span immediately.
5. If UE-related and online correlation is enabled, send compact envelope to
   /v1/events.
6. If correlator returns matched/closing/closed, export span with returned
   trace_id.
7. If correlator returns pending, keep the processed span in the local proxy
   buffer until either:
   - a later event resolves the lifecycle to matched/closing/closed;
   - ONLINE_TRACE_BUFFER_MS expires;
   - ONLINE_TRACE_BUFFER_MAX_EVENTS forces oldest buffered spans out.
8. On timeout, proxy calls /v1/resolve once, exports with the latest returned
   trace ID, and marks the span with `ue.online.buffer.timeout=true`.
```

Packet forwarding never waits for online correlation. The buffer only delays
span export.

## Lifecycle States

### `pending`

Only one protocol-local lifecycle is known, or the currently observed evidence
is not enough to safely join F1AP and NGAP.

Trace behavior:

- correlator allocates a trace ID;
- proxy may buffer UE-related spans briefly;
- if buffer timeout expires, the span is exported as a local-only UE trace with
  `ue.online.state=pending`.

### `matched`

F1AP and NGAP lifecycles are linked with cross-protocol evidence.

Trace behavior:

- F1AP and NGAP proxies export subsequent UE spans using the same trace ID;
- buffered spans are resolved and exported using that trace ID when possible.

### `closing`

At least one linked protocol emitted `UEContextReleaseComplete`, but the other
linked protocol has not yet emitted release complete.

Trace behavior:

- keep using the same trace ID;
- wait for the other protocol release or timeout.

### `closed`

All linked observed protocols emitted `UEContextReleaseComplete`, or a
single-protocol lifecycle reached release before any cross-protocol match.

Trace behavior:

- later reused IDs should create a new lifecycle and a new trace ID;
- closed state is retained until eviction.

### `forced_closed`

State was closed without a complete normal release sequence.

Forced-close reasons:

- `idle_timeout`: no new event before `ONLINE_CORRELATION_IDLE_TIMEOUT_MS`;
- `id_reuse`: a closed lifecycle key is reused for a new lifecycle;
- future association/CU restart handling can use the same state.

Trace behavior:

- a future event for the reused/new lifecycle receives a new trace ID;
- the old lifecycle remains closed for debugging until eviction.

## Environment Variables

Service:

| Variable | Default | Description |
| --- | --- | --- |
| `ONLINE_CORRELATOR_HOST` | `0.0.0.0` | HTTP listen address. |
| `ONLINE_CORRELATOR_PORT` | `8080` | HTTP listen port. |
| `ONLINE_CORRELATION_INITIAL_GAP_MS` | `1000` | Max F1AP InitialULRRC to NGAP InitialUE gap for strong match evidence. |
| `ONLINE_CORRELATION_RELEASE_GAP_MS` | `5000` | Release-complete alignment window. |
| `ONLINE_CORRELATION_IDLE_TIMEOUT_MS` | `60000` | Idle forced-close timeout. |
| `ONLINE_CORRELATION_MAX_LIFECYCLES` | `10000` | Max retained global lifecycles before eviction. |

Proxy client:

| Variable | Default | Description |
| --- | --- | --- |
| `ONLINE_CORRELATION_ENABLED` | `1` | Enable client when endpoint is set. |
| `ONLINE_CORRELATION_ENDPOINT` | unset | Correlator base URL, for example `http://control-plane-correlator.oai.svc.cluster.local:8080`. |
| `ONLINE_CORRELATION_TIMEOUT_MS` | `100` | HTTP request timeout from proxy worker to correlator. |
| `ONLINE_CORRELATION_FAIL_OPEN` | `1` | Export spans without online trace ID if correlator is unavailable. |
| `ONLINE_TRACE_BUFFER_MS` | `1000` | Proxy-local UE span export buffer timeout. |
| `ONLINE_TRACE_BUFFER_MAX_EVENTS` | `256` | Max buffered processed spans per proxy worker. |

## Build

```sh
IMAGE=docker.io/genechen0203/control-plane-correlator:latest

cd control-plane-tracing/src
docker build -f correlator/online/Dockerfile -t "$IMAGE" .
docker push "$IMAGE"
```

For an amd64 lab cluster:

```sh
IMAGE=docker.io/genechen0203/control-plane-correlator:latest

cd control-plane-tracing/src
docker buildx build --platform linux/amd64 \
  -f correlator/online/Dockerfile \
  -t "$IMAGE" \
  --push .
```

## Project Deployment

The main deployment scripts keep proxy insertion and online correlation as two
separate choices. Deploy both protocol proxies and the shared correlator with:

```sh
RanProxy=1 CrossProtocolCorrelate=1 ./script/run.sh
```

`CrossProtocolCorrelate=0` is the default. In that mode the correlator is not
deployed, and the F1AP and NGAP manifests receive
`ONLINE_CORRELATION_ENABLED=0` with an empty endpoint. Setting
`CrossProtocolCorrelate=1` without `RanProxy=1` is rejected because there would
be no proxy clients producing correlation events.

When an existing correlator Deployment is reused, `deploy.sh` restarts it to
clear the in-memory lifecycle tables before the new RAN deployment begins.
