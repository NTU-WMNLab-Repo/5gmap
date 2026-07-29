# F1AP SCTP Tracing Proxy

## Prototype Status

This proxy is usable as an F1-C SCTP relay and can emit OpenTelemetry spans for
observed F1AP messages. Packet forwarding is non-blocking with respect to
decoding: the proxy forwards the original SCTP payload first, then sends a copied
payload to an async trace worker.

The F1AP decoder uses pycrate's built-in F1AP ASN.1 module by default and falls
back to lightweight top-level classification if pycrate is unavailable or a
payload cannot be decoded. The full APER-decoded F1AP value is available as a
truncated `asn1.value` span attribute; selected fields such as IE names,
procedure metadata, and common UE identifiers are promoted to dedicated
attributes.

The decoder does not yet promote every decoded IE into first-class Jaeger
attributes, and it does not decode nested RRC or NAS payloads. Those payloads are
kept opaque because they require their own protocol decoders and may contain
data outside the F1AP control-message layer.

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
| `F1AP_ENABLE_PYCRATE` | `1` | Enable pycrate APER decode. Set to `0` for lightweight-only decode. |
| `F1AP_PYCRATE_MODULE` | `pycrate_asn1dir.F1AP` | pycrate F1AP module name. |
| `F1AP_PYCRATE_OBJECT` | `F1AP_PDU_Descriptions.F1AP_PDU` | pycrate F1AP root object path. |
| `ASN1_VALUE_REPR_LIMIT` | `2048` | Maximum characters stored in the `asn1.value` span attribute. |
| `ASN1_INCLUDE_SHOW` | `0` | Include pycrate `show()` output in `asn1.show` when set to `1`. |

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

The current F1AP decoder is asynchronous. It uses pycrate APER decoding by
default and keeps the lightweight classifier as a fallback. Packet forwarding
does not wait for either decoder path.

This proxy is intentionally F1-C only. If F1-U forwarding is needed for a
specific topology, keep it separate from tracing and do not emit per-packet
spans.
