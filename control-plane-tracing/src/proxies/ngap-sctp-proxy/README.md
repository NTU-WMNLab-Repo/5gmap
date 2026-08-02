# NGAP SCTP Tracing Proxy

## Prototype Status

This proxy is the NGAP/N2 skeleton for control-plane tracing. It transparently
relays SCTP traffic between the CU-CP and AMF, forwards the original packet
before tracing work, and emits one OpenTelemetry span per observed NGAP SCTP
message.

NGAP decoding is intentionally minimal in this first version. Spans identify the
protocol as `ngap`, record direction, SCTP metadata, payload size, forwarding
duration, queue delay, and decoder duration. Procedure-level NGAP decode and
correlation are future work.

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
