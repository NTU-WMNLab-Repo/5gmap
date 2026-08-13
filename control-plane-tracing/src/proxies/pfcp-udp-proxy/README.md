# PFCP UDP Tracing Proxy

## Prototype Status

This first PFCP proxy is a transparent UDP relay between an SMF and a UPF. It
forwards each original datagram before enqueueing observability work and exports
one raw OpenTelemetry span per forwarded datagram.

It intentionally does **not** decode PFCP yet. Therefore it does not export a
PFCP message type, sequence number, SEID, F-SEID, PDR, FAR, TEID, transaction
correlation, or a UE/cross-protocol trace relationship. The first deployment
goal is only to prove that changing the discovered UPF FQDN to the proxy keeps
the SMF-UPF PFCP path functional.

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
This avoids depending on whether a particular NRF/UPF version returns a FQDN or
a Pod IP for UPF selection. The proxy's `UPF_HOST` still targets the real
`oai-spgwu-tiny<slice>-svc` endpoint. With `RanProxy=0`, the script removes the
proxy, clears the static endpoint, and re-enables the original SMF discovery
mode.

## Span Semantics

The span name is one of:

```text
PFCP smf_to_upf raw_datagram
PFCP upf_to_smf raw_datagram
```

Every raw span includes `network.transport=udp`, `pfcp.direction`, payload
size, UDP source/destination addresses and ports, `proxy.forward.duration_ms`,
`tracing.queue_delay_ms`, and `tracing.dropped_events`.

The span starts when the proxy receives the datagram and ends when the proxy
finishes forwarding it. Queue delay is not forwarding overhead because export
is asynchronous. No datagram payload or decoded field is sent to Jaeger in
this version.

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
