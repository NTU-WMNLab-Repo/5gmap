# OAI PFCP Proxy Manifest

For proxy behavior, image build commands, and the complete runtime environment
reference, see:

```text
../../control-plane-tracing/src/proxies/pfcp-udp-proxy/README.md
```

This manifest is rendered by `script/deploy.sh` when `RanProxy=1`. It creates
one `pfcpproxy<slice>` Service and Deployment on `CORE_LOC` rather than
`RAN_LOC`.

In the same mode, the deployment script configures the UPF to advertise this
Service name as its PFCP Node ID FQDN. The proxy itself continues to use the
real `oai-spgwu-tiny<slice>-svc` service as its upstream target.

The script replaces `__PROXY_NAME__`, `__UPF_HOST__`, `__SMF_HOST__`,
`__PFCP_PORT__`, `__OTEL_ENDPOINT__`, `__OTEL_INSECURE__`, and `__CORE_LOC__`
before applying the manifest.
