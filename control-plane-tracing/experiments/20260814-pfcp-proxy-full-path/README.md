# PFCP Proxy Full-Path Experiment

## Metadata

- Date: 2026-08-14
- Experiment start: 2026-08-13 17:21:18.272 UTC
- Experiment start: 2026-08-14 01:21:18.272 Asia/Taipei
- Jaeger capture end: 2026-08-13 17:25:52.748 UTC
- Jaeger capture end: 2026-08-14 01:25:52.748 Asia/Taipei
- Git hash under test: `d5ae5d8` (`Keep PFCP traffic on tracing proxy`)
- Topology: SMF -> `pfcpproxy10` -> UPF over N4/PFCP UDP port `8805`
- Scope: validate that the raw PFCP proxy remains on the complete N4 path
  after Association Setup, including heartbeat and session procedures.

## Objective

Validate the deployment change that makes the UPF advertise the proxy Service
name as its PFCP Node ID FQDN. The previous smoke experiment proved that the
UDP relay could forward Association Setup, but OAI SMF then learned the real
UPF FQDN from the response and bypassed the proxy for later traffic.

This experiment checks that Association Setup, heartbeat, session
establishment, session modification, and session deletion all continue through
the proxy without PFCP payload rewriting.

## Effective Topology

The captured Kubernetes resources confirm the intended two-name arrangement:

```text
SMF UPF_LIST
  IPV4_ADDRESS = 10.43.215.40
  FQDN         = pfcpproxy10
  DISCOVER_UPF = no

UPF PFCP Node ID advertised in Association Setup Response
  UPF_FQDN_5G = pfcpproxy10

PFCP proxy upstream
  UPF_HOST = oai-spgwu-tiny10-svc
  SMF_HOST = oai-smf10-svc
```

`pfcp-proxy-service.raw.yaml` confirms that `10.43.215.40` is the
`pfcpproxy10` ClusterIP. Thus the SMF resolves the FQDN learned from the UPF
response back to the proxy, while the proxy still resolves a separate real-UPF
service for its upstream path.

## Raw Evidence

- `jaeger-pfcpproxy-traces-01.raw.json` through
  `jaeger-pfcpproxy-traces-04.raw.json`: four unmodified, valid Jaeger API
  responses for adjacent time windows covering the whole capture.
- `pfcp-proxy-log.raw.txt`: unmodified PFCP proxy container log.
- `smf-log.raw.txt`: unmodified SMF container log.
- `upf-log.raw.txt`: unmodified UPF container log.
- `smf-configmap.raw.yaml`: effective SMF configuration.
- `upf-configmap.raw.yaml`: effective UPF configuration.
- `pfcp-proxy-service.raw.yaml`: PFCP proxy Service definition.
- `pfcp-proxy-pod.raw.yaml`: PFCP proxy Pod specification and environment.
- `oai-pods.raw.txt`: OAI pod snapshot.

The Jaeger API result is partitioned rather than assembled after capture. Each
file is a standalone raw API response; their adjacent query windows are:

```text
01: 1786641678272000 .. 1786641750000000
02: 1786641750000000 .. 1786641830000000
03: 1786641830000000 .. 1786641890000000
04: 1786641890000000 .. 1786641952748000
```

After de-duplicating by span ID, the four valid responses contain `66` unique
traces and `66` unique spans with `0` duplicate spans. The first and last span
starts are:

```text
1786641678272057 = 2026-08-13 17:21:18.272057 UTC
1786641948356450 = 2026-08-13 17:25:48.356450 UTC
```

The first span begins `0.057 ms` after the requested lower bound. The last
heartbeat response falls before the fixed capture end. The Kubernetes logs use
the same lower bound but do not have an upper bound, so their raw files may
contain a small amount of later traffic; all statistics below use the strict
Jaeger window and proxy-log timestamps no later than the stated capture end.

## Relay And Span Summary

Every forwarded datagram is exported as one independent raw span in this
prototype, so one span per trace is expected until PFCP transaction correlation
is implemented.

```text
PFCP smf_to_upf raw_datagram = 33
PFCP upf_to_smf raw_datagram = 33
total                         = 66
tracing.dropped_events max    = 0
```

All span endpoint metadata has the same logical route:

```text
smf_to_upf: 10.42.2.19:8805 -> 10.42.2.20:8805 (33)
upf_to_smf: 10.42.2.20:8805 -> 10.42.2.19:8805 (33)
```

The raw proxy does not decode PFCP into span attributes:
`pfcp.message.name=raw_datagram` and `pfcp.decode.enabled=false` for every
span. The following header classification is therefore evidence derived from
the logged raw packet prefixes, and is corroborated by the SMF and UPF logs;
it is not a capability claimed by the proxy implementation yet.

```text
Association Setup Request / Response       = 1 / 1
Heartbeat Request / Response               = 27 / 27
Session Establishment Request / Response   = 2 / 2
Session Modification Request / Response    = 2 / 2
Session Deletion Request / Response        = 1 / 1
```

The non-heartbeat sequence observed at the proxy is:

```text
17:21:18.274  Association Setup Request       SMF -> UPF   34 bytes
17:21:18.275  Association Setup Response      UPF -> SMF   44 bytes

17:23:31.081  Session Establishment Request   SMF -> UPF  132 bytes
17:23:31.082  Session Establishment Response  UPF -> SMF   78 bytes
17:23:31.117  Session Modification Request    SMF -> UPF  100 bytes
17:23:31.118  Session Modification Response   UPF -> SMF   31 bytes

17:25:18.094  Session Deletion Request        SMF -> UPF   16 bytes
17:25:18.095  Session Deletion Response       UPF -> SMF   21 bytes

17:25:29.793  Session Establishment Request   SMF -> UPF  132 bytes
17:25:29.793  Session Establishment Response  UPF -> SMF   78 bytes
17:25:29.827  Session Modification Request    SMF -> UPF  100 bytes
17:25:29.828  Session Modification Response   UPF -> SMF   31 bytes
```

The proxy log's Association Setup Response prefix includes the ASCII bytes
`7066637070726f78793130`, which spell `pfcpproxy10`. This aligns with the
effective UPF `UPF_FQDN_5G` configuration and shows that the new Node ID FQDN
is present in the actual response observed by the proxy.

## Delay And Health

All 66 Jaeger spans report:

```text
proxy.forward.duration_ms: min=0.019160 avg=0.941065 max=2.571801
tracing.queue_delay_ms:    min=0.013992 avg=0.106102 max=0.255276
```

The forwarding duration ends before the asynchronous tracing queue is
submitted. Consequently, queue delay is export annotation latency, not added
PFCP forwarding delay. All proxy, SMF, and UPF pods in the snapshot are
running with zero restarts.

## Result

The response-driven PFCP bypass observed in the 2026-08-13 smoke experiment is
fixed for this deployment. The proxy carried the initial Association Setup
exchange, 27 complete heartbeat exchanges over more than four minutes, and two
session establishment/modification sequences separated by a complete session
deletion sequence.

No PFCP payload was modified by the relay. The routing behavior changed only
because the UPF was configured to generate `pfcpproxy10` as its own PFCP Node
ID FQDN, while the proxy retained a distinct upstream service name for the real
UPF.

## Remaining Scope

- PFCP spans remain raw datagrams: no message-type, sequence-number, SEID,
  F-SEID, PDR, FAR, or TEID attributes are exported yet.
- PFCP request/response transaction correlation is not implemented.
- PFCP has not yet been joined to F1AP/NGAP UE lifecycles.
- Proxy restart and PFCP association recovery behavior remain untested.

The next implementation step can now safely be PFCP light decoding, beginning
with the PFCP header and message type, because the proxy has been shown to stay
in the live N4 path for both keepalive and session control traffic.
