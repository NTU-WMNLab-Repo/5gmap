# OAI Control-Plane Correlator Manifest

For the API contract, state tables, matching flow, lifecycle states, and image
build commands, see:

```text
../../control-plane-tracing/src/correlator/online/README.md
```

This folder contains the Kubernetes manifest used by the deployment scripts
when both `RanProxy=1` and `CrossProtocolCorrelate=1` are enabled.

The deployment script renders the image from
`CROSS_PROTOCOL_CORRELATOR_IMAGE`, deploys one shared
`control-plane-correlator` service, and configures every F1AP and NGAP proxy to
call `http://control-plane-correlator:8080` by default.

The manifest also configures OTLP export for the correlator's `UE lifecycle`
root spans. The root exports immediately after a cross-protocol match, so F1AP
and NGAP proxy spans use a visible shared parent. A later release exports a
`UE lifecycle summary` child span with the final lifecycle state.

If the Deployment already exists, `deploy.sh` restarts it after applying the
manifest so each deployment run starts with an empty in-memory correlation
state.

With `CrossProtocolCorrelate=0`, the correlator is removed and the proxy
manifests receive `ONLINE_CORRELATION_ENABLED=0` with an empty endpoint. The
proxies then retain their protocol-local tracing behavior.
