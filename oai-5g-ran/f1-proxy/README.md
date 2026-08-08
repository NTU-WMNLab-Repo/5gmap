# OAI F1AP Proxy Manifest

For detailed proxy behavior, build commands, and the full environment variable
reference, see:

```text
../../control-plane-tracing/src/proxies/f1ap-sctp-proxy/README.md
```

This folder contains the OAI deployment manifest used by the RAN deployment
scripts when the F1AP proxy is enabled.

## Manifest

- `oai-f1ap-proxy.yaml`: Service and Deployment template for one F1-C SCTP proxy.

The deployment script renders placeholders such as `__PROXY_NAME__`,
`__CU_HOST__`, `__F1C_PORT__`, `__OTEL_ENDPOINT__`,
`__ONLINE_CORRELATION_ENABLED__`, `__ONLINE_CORRELATION_ENDPOINT__`, and
`__RAN_LOC__` before applying the manifest.

## Common Runtime Settings

The manifest lists all proxy runtime environment variables with their current
defaults. The most commonly adjusted values are:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CU_HOST` | rendered | Real CU F1-C endpoint behind the proxy. |
| `CU_PORT` | rendered | Real CU F1-C SCTP port. |
| `LISTEN_PORT` | rendered | Proxy F1-C SCTP listen port. |
| `OTEL_SERVICE_NAME` | rendered | Service name shown in Jaeger. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | rendered | OTLP endpoint used by the proxy. |
| `TRACE_QUEUE_SIZE` | `10000` | Async decode/tracing queue depth. |
| `ONLINE_CORRELATION_ENABLED` | rendered | `1` only when `CrossProtocolCorrelate=1`; otherwise `0`. |
| `ONLINE_CORRELATION_ENDPOINT` | rendered | Shared correlator URL when enabled; otherwise empty. |
| `ONLINE_TRACE_BUFFER_MS` | `1000` | Max local wait for a shared cross-protocol trace ID. |
| `F1AP_ENABLE_CORRELATION` | `1` | Add UE-context and transaction correlation attributes to spans. |
| `F1AP_CORRELATION_MAX_CONTEXTS` | `10000` | Maximum tracked UE bindings before old contexts are evicted. |
| `F1AP_ENABLE_PYCRATE` | `1` | Enable full pycrate APER decode. |
| `ASN1_INCLUDE_VALUE` | `0` | Include truncated `asn1.value`; keep disabled to reduce decode-worker cost. |
| `ASN1_VALUE_REPR_LIMIT` | `2048` | Character limit for `asn1.value` and `asn1.show`. |

Packet forwarding does not wait for F1AP decode. Decode-related settings affect
trace detail and worker cost, not the forwarding hot path.
