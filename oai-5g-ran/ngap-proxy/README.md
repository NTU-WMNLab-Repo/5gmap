# OAI NGAP Proxy Manifest

For detailed proxy behavior and runtime variables, see:

```text
../../control-plane-tracing/src/proxies/ngap-sctp-proxy/README.md
```

This folder contains the OAI deployment manifest used by the RAN deployment
scripts when the RAN proxy option is enabled.

## Manifest

- `oai-ngap-proxy.yaml`: Service and Deployment template for one NGAP/N2 SCTP
  proxy.

The deployment script renders placeholders such as `__PROXY_NAME__`,
`__AMF_HOST__`, `__NGAP_PORT__`, `__OTEL_ENDPOINT__`, and `__RAN_LOC__` before
applying the manifest.

The default image is:

```text
docker.io/genechen0203/ngap-sctp-proxy:latest
```

Override it at deployment time with `RAN_PROXY_NGAP_IMAGE`.
