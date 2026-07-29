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
`__CU_HOST__`, `__F1C_PORT__`, `__OTEL_ENDPOINT__`, and `__RAN_LOC__` before
applying the manifest.

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
| `F1AP_ENABLE_PYCRATE` | `1` | Enable full pycrate APER decode. |
| `ASN1_INCLUDE_VALUE` | `1` | Include truncated `asn1.value`; set to `0` to reduce decode-worker cost. |
| `ASN1_VALUE_REPR_LIMIT` | `2048` | Character limit for `asn1.value` and `asn1.show`. |

Packet forwarding does not wait for F1AP decode. Decode-related settings affect
trace detail and worker cost, not the forwarding hot path.
