# F1AP SCTP Tracing Proxy

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

## Local Run

The proxy needs SCTP support and the Python `pysctp` package.

```sh
pip install -r requirements.txt
python3 -u f1ap_sctp_proxy.py
```

## Container

```sh
docker build -t f1ap-sctp-proxy:dev .
```

## Notes

The current classifier is a lightweight heuristic. It recognizes a few observed
F1AP prefixes such as setup and UE context setup messages, but a full ASN.1 PER
decoder should replace this once the transport path is stable.

This proxy is intentionally F1-C only. If F1-U forwarding is needed for a
specific topology, keep it separate from tracing and do not emit per-packet
spans.
