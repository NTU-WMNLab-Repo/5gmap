# NGAP SCTP Tracing Proxy

## Prototype Status

This proxy is the NGAP/N2 skeleton for control-plane tracing. It transparently
relays SCTP traffic between the CU-CP and AMF, forwards the original packet
before tracing work, and emits one OpenTelemetry span per observed NGAP SCTP
message.

NGAP decoding uses pycrate APER decode by default, with the lightweight
top-level classifier kept as a fallback. Spans identify the protocol as `ngap`,
record direction, SCTP metadata, payload size, forwarding duration, queue delay,
decoder duration, top-level PDU type, procedure code, procedure name, message
name, IE summaries, selected NGAP identifiers, and NGAP UE correlation
attributes.

Direction labels are protocol-specific:

```text
CU-CP -> AMF = cu_to_amf
AMF   -> CU-CP = amf_to_cu
```

## Traffic Path

```text
CU-CP -> NGAP tracing proxy -> AMF
AMF   -> NGAP tracing proxy -> CU-CP
```

The CU-CP must be configured so its AMF endpoint points to the proxy service.
The proxy's `AMF_HOST` points to the real AMF service or pod IP.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `AMF_HOST` | `oai-amf` | Real AMF host or service name. |
| `AMF_PORT` | `38412` | Real AMF NGAP SCTP port. |
| `LISTEN_HOST` | `0.0.0.0` | Address to listen on for CU-CP connections. |
| `LISTEN_PORT` | `38412` | Proxy NGAP SCTP listen port. |
| `SCTP_PPID` | `60` | NGAP SCTP PPID. |
| `OTEL_SERVICE_NAME` | `ngap-sctp-proxy` | OpenTelemetry service name. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Optional OTLP gRPC endpoint. |
| `LOG_HEX_BYTES` | `32` | Number of payload bytes shown in logs. |
| `AMF_CONNECT_RETRIES` | `60` | AMF connection retry count at startup. |
| `AMF_CONNECT_RETRY_SECONDS` | `2` | Seconds between AMF connection retries. |
| `TRACE_QUEUE_SIZE` | `10000` | Async decode/tracing queue depth. |
| `NGAP_ENABLE_CORRELATION` | `1` | Enable NGAP UE correlation attributes. |
| `NGAP_CORRELATION_MAX_CONTEXTS` | `10000` | Maximum in-memory NGAP UE bindings. |
| `ONLINE_CORRELATION_ENABLED` | `1` | Enable online cross-protocol correlation when `ONLINE_CORRELATION_ENDPOINT` is set. |
| `ONLINE_CORRELATION_ENDPOINT` | unset | Optional online correlator base URL. Leave unset to keep the current per-span trace behavior. |
| `ONLINE_CORRELATION_TIMEOUT_MS` | `100` | HTTP timeout from the trace worker to the online correlator. |
| `ONLINE_CORRELATION_FAIL_OPEN` | `1` | Export spans without an online trace ID if the correlator is unavailable. |
| `ONLINE_TRACE_BUFFER_MS` | `1000` | UE-related span export buffer timeout while waiting for cross-protocol evidence. |
| `ONLINE_TRACE_BUFFER_MAX_EVENTS` | `256` | Max processed UE spans buffered by this proxy worker. |
| `NGAP_ENABLE_PYCRATE` | `1` | Enable pycrate APER decode. Set `0` to use lightweight decode only. |
| `NGAP_PYCRATE_MODULE` | `pycrate_asn1dir.NGAP` | pycrate NGAP module to import. |
| `NGAP_PYCRATE_OBJECT` | `NGAP_PDU_Descriptions.NGAP_PDU` | pycrate NGAP root object. |
| `ASN1_COPY_ROOT` | `0` | Deep-copy the pycrate root object per decode. Usually unnecessary with the single worker. |
| `ASN1_INCLUDE_VALUE` | `0` | Include a truncated `asn1.value` debug attribute. Keep disabled for normal runs. |
| `ASN1_VALUE_REPR_LIMIT` | `2048` | Maximum size of `asn1.value` or `asn1.show` attributes. |
| `ASN1_INCLUDE_SHOW` | `0` | Include pycrate `show()` output for short debugging captures. |

## Container

Build and push the NGAP proxy image separately from the F1AP proxy image:

```sh
IMAGE=docker.io/genechen0203/ngap-sctp-proxy:latest

cd control-plane-tracing/src
docker login
docker build -f proxies/ngap-sctp-proxy/Dockerfile -t "$IMAGE" .
docker push "$IMAGE"
```

For an amd64 lab cluster, build explicitly for amd64 when building from a
different architecture:

```sh
IMAGE=docker.io/genechen0203/ngap-sctp-proxy:latest

cd control-plane-tracing/src
docker login
docker buildx build --platform linux/amd64 \
  -f proxies/ngap-sctp-proxy/Dockerfile \
  -t "$IMAGE" \
  --push .
```

The image still copies the shared `protocols`, `proxies`, and `correlator`
packages, but it is tagged as `ngap-sctp-proxy` and starts:

```sh
python3 -u proxies/ngap-sctp-proxy/ngap_sctp_proxy.py
```
