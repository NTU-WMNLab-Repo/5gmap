# F1AP SCTP Tracing Proxy

## Prototype Status

This proxy is usable as an F1-C SCTP relay and can emit OpenTelemetry spans for
observed F1AP messages. Packet forwarding is non-blocking with respect to
decoding: the proxy forwards the original SCTP payload first, then sends a copied
payload to an async trace worker.

The F1AP decoder is not a complete ASN.1 PER decoder yet. The current default
decoder only performs lightweight top-level classification from observed OAI
F1AP APER payloads, such as F1 setup, UE context setup, and selected RRC transfer
procedures. It does not fully decode all F1AP information elements, UE IDs,
transaction fields, or nested RRC/NAS payloads.

Full F1AP decoding still requires generating and wiring a pycrate-compatible
F1AP ASN.1 module, then validating the decoded fields against OAI traffic. The
shared pycrate adapter is present, but no generated F1AP ASN.1 module is bundled
with this proxy yet.

This prototype proxies F1-C traffic between a DU and CU over SCTP and emits
control-plane tracing information.

The first version intentionally forwards F1AP messages unchanged. It does not
modify F1AP payloads and does not proxy or trace F1-U/GTP-U data-plane traffic.

## Traffic Path

```text
DU -> F1AP tracing proxy -> CU
CU -> F1AP tracing proxy -> DU
```

The DU must be configured so its F1-C remote endpoint points to the proxy
service. The proxy then connects to the real CU.

For OAI DU deployments, both the high-level CU host value and the generated
`MACRLCs.remote_n_address` should point to the proxy service. The proxy's
`CU_HOST` should point to the real CU service.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `CU_HOST` | `oai-cu` | Real CU host or service name. |
| `CU_PORT` | `38472` | Real CU F1-C SCTP port. |
| `LISTEN_HOST` | `0.0.0.0` | Address to listen on for DU connections. |
| `LISTEN_PORT` | `38472` | Proxy F1-C SCTP listen port. |
| `SCTP_PPID` | `62` | F1AP SCTP PPID. |
| `OTEL_SERVICE_NAME` | `f1ap-sctp-proxy` | OpenTelemetry service name. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Optional OTLP gRPC endpoint. |
| `LOG_HEX_BYTES` | `32` | Number of payload bytes shown in logs. |
| `CU_CONNECT_RETRIES` | `60` | CU connection retry count at startup. |
| `CU_CONNECT_RETRY_SECONDS` | `2` | Seconds between CU connection retries. |
| `TRACE_QUEUE_SIZE` | `10000` | Async decode/tracing queue depth. |
| `F1AP_PYCRATE_MODULE` | unset | Optional pycrate-generated F1AP module name. |
| `F1AP_PYCRATE_OBJECT` | `F1AP_PDU` | Optional pycrate F1AP root object name. |

For this repository's OAI split-RAN deployment, the CU process listens for F1-C
SCTP on port `38472`. Keep the proxy service name short because the DU-side OAI
configuration path can truncate longer hostnames.

## Local Run

The proxy needs SCTP support and the Python `pysctp` package.

```sh
cd control-plane-tracing/src
pip install -r proxies/f1ap-sctp-proxy/requirements.txt
python3 -u proxies/f1ap-sctp-proxy/f1ap_sctp_proxy.py
```

## Container

```sh
IMAGE=docker.io/genechen0203/f1ap-sctp-proxy:latest

cd control-plane-tracing/src
docker login
docker build -f proxies/f1ap-sctp-proxy/Dockerfile -t "$IMAGE" .
docker push "$IMAGE"
```

Docker Hub can create a missing repository on first push for a user namespace,
subject to the account or organization privacy settings. Creating the repository
manually first is still useful when you want to choose visibility and metadata
explicitly.

For an amd64 lab cluster, build explicitly for amd64 when building from a
different architecture:

```sh
IMAGE=docker.io/genechen0203/f1ap-sctp-proxy:latest

cd control-plane-tracing/src
docker login
docker buildx build --platform linux/amd64 \
  -f proxies/f1ap-sctp-proxy/Dockerfile \
  -t "$IMAGE" \
  --push .
```

## Notes

The current F1AP decoder is asynchronous. It does a lightweight top-level F1AP
decode by default and can also call a pycrate-generated APER decoder when
`F1AP_PYCRATE_MODULE` is configured. Packet forwarding does not wait for either
decoder path.

This proxy is intentionally F1-C only. If F1-U forwarding is needed for a
specific topology, keep it separate from tracing and do not emit per-packet
spans.
