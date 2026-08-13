# PFCP UDP Proxy Smoke Experiment

## Metadata

- Date: 2026-08-13
- Experiment start: 2026-08-13 15:26:49.070 UTC
- Experiment start: 2026-08-13 23:26:49.070 Asia/Taipei
- Jaeger capture end: 2026-08-13 15:39:05.378 UTC
- Git hash under test: `b7811e3` (`Deploy PFCP tracing proxy with RanProxy`)
- Topology: SMF -> `pfcpproxy10` -> UPF on N4/PFCP UDP port `8805`
- Scope: validate the first raw-only PFCP UDP relay. PFCP decoding and
  cross-protocol correlation are intentionally outside this experiment.

## Objective

Verify that the proxy can transparently forward both directions of PFCP
traffic, emit raw OpenTelemetry spans to Jaeger, and remain on the N4 path for
association, heartbeat, and UE session traffic.

## Raw Evidence

- `jaeger-pfcpproxy-traces.raw.json`: unmodified Jaeger API response for
  `pfcpproxy10`.
- `pfcp-proxy-log.raw.txt`: unmodified PFCP proxy container log.
- `smf-log.raw.txt`: unmodified SMF container log.
- `upf-log.raw.txt`: unmodified UPF container log.
- `oai-pods.raw.txt`: pod snapshot taken during evidence collection.

The Jaeger query window was inclusive:

```text
start = 1786634809070000 = 2026-08-13 15:26:49.070000 UTC
end   = 1786635545378000 = 2026-08-13 15:39:05.378000 UTC
```

The earliest returned PFCP span begins at:

```text
1786634809070123 = 2026-08-13 15:26:49.070123 UTC
```

This is `0.123 ms` after the requested lower bound and agrees with the stated
first PFCP message time. The Kubernetes log snapshots use the same lower bound
but have no upper bound; they continue until they were collected and therefore
may contain later traffic than the Jaeger window.

## Raw Relay Result

The proxy successfully relayed and exported the first four Association Setup
request/response pairs:

```text
unique traces = 8
unique spans  = 8
smf_to_upf    = 4
upf_to_smf    = 4
```

All spans have `pfcp.decode.enabled=false`, as expected for the raw-only
prototype. Their logical endpoints are consistently:

```text
SMF 10.42.2.249:8805 -> UPF 10.42.2.250:8805
UPF 10.42.2.250:8805 -> SMF 10.42.2.249:8805
```

The outgoing Association Setup datagrams are `34` bytes and the responses are
`53` bytes. Every captured span reports `tracing.dropped_events=0`.

```text
proxy.forward.duration_ms: min=0.021080 avg=0.537746 max=1.937977
tracing.queue_delay_ms:    min=0.028383 avg=0.105317 max=0.226352
```

Forwarding completes before the asynchronous span queue is used, so
`tracing.queue_delay_ms` is observability latency rather than PFCP forwarding
overhead.

## Full N4 Interception Result

The smoke test proves the relay and Jaeger export path, but **does not prove a
complete PFCP interception path**. After the fourth relayed response, traffic
bypassed `pfcpproxy10`.

The last proxy log event is the response at `15:26:55.072764 UTC`. The SMF
starts a PFCP heartbeat at `15:27:05.073840 UTC`, and the UPF receives it at
`15:27:05.074229 UTC`, but the proxy has no corresponding log or Jaeger span.
The same pattern holds for traffic that matters more than heartbeats:

```text
UPF received Session Establishment Request:  2
UPF received Session Modification Request:   1
UPF received Session Deletion Request:       1
UPF received Heartbeat Request:             52
PFCP proxy spans after 15:26:55 UTC:         0
```

## Root-Cause Evidence

The SMF log explains the bypass mechanism. Immediately after receiving an
Association Setup Response, it reads the UPF Node ID FQDN from that response:

```text
15:26:49.071742 UTC  FQDN oai-spgwu-tiny10-svc
15:26:49.072916 UTC  Resolve FQDN oai-spgwu-tiny10-svc, IP Addr 10.42.2.250
```

`10.42.2.250` is the UPF Pod IP shown in `oai-pods.raw.txt`. The static proxy
endpoint successfully directs the initial Association Setup packet to the
relay, but OAI SMF then learns the real UPF identity from the response and
uses that direct address for subsequent PFCP procedures. The continuous UPF
heartbeats and session operations without matching proxy events rule out a
Jaeger export-only problem.

## Conclusion And Follow-Up

This first deployment validates that the UDP relay preserves Association Setup
datagrams in both directions and exports the expected raw spans with no queue
drops. It is not yet suitable for PFCP tracing because it loses the N4 path
after Association Setup.

The next implementation should retain the proxy as the SMF-visible UPF
endpoint after Association Setup. A likely topology is to make the FQDN the
UPF advertises resolve to the proxy, while giving the proxy a separate direct
service name for the real UPF. That avoids packet rewriting in the first fix
and keeps the SMF's response-driven FQDN resolution on the interception path.
Only after this is verified with heartbeats and session procedures should PFCP
light decoding begin.
