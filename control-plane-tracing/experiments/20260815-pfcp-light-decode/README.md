# PFCP Header Light Decode Experiment

## Metadata

- Date: 2026-08-15
- Experiment start: 2026-08-15 10:07:57.903 UTC
- Experiment start: 2026-08-15 18:07:57.903 Asia/Taipei
- Jaeger capture end: 2026-08-15 10:15:19.763742 UTC
- Jaeger capture end: 2026-08-15 18:15:19.763742 Asia/Taipei
- Git hash under test: `babef28` (`Fix PFCP proxy image packaging`)
- Proxy image: `genechen0203/pfcp-udp-proxy:latest`
- Proxy image ID: `sha256:1ecbc0a26b5ef2fe15bb2bb8543ee77f5de08b70ecdca3bb0b5e001cae202c1d`
- Topology: SMF -> `pfcpproxy10` -> UPF over N4/PFCP UDP port `8805`
- Scope: validate asynchronous PFCP header light decoding after the proxy-image
  packaging fix.

## Objective

Verify that the live PFCP proxy continues to forward N4 traffic while it
exports one decoded span per PFCP message. The decoder is intentionally limited
to the PFCP common header: version, flags, message type, declared length, SEID
when present, and sequence number. It does not parse PFCP Information Elements.

## Raw Evidence

- `jaeger-pfcpproxy-traces.raw.json`: unmodified Jaeger API response for the
  strict capture window.
- `pfcp-proxy-log.raw.txt`: unmodified PFCP proxy log captured from the stated
  lower bound.
- `smf-log.raw.txt` and `upf-log.raw.txt`: unmodified N4 endpoint logs
  captured from the same lower bound.
- `pfcp-proxy-deployment.raw.yaml` and `pfcp-proxy-pod.raw.yaml`: deployed
  proxy configuration and running image evidence.
- `oai-pods.raw.txt`: pod snapshot collected with the other evidence.

The Jaeger query was:

```text
service = pfcpproxy10
start   = 1786788477903000 = 2026-08-15 10:07:57.903000 UTC
end     = 1786788919763742 = 2026-08-15 10:15:19.763742 UTC
limit   = 2000
```

The first and last returned span starts are:

```text
1786788477903341 = 2026-08-15 10:07:57.903341 UTC
1786788918054850 = 2026-08-15 10:15:18.054850 UTC
```

The first span begins `0.341 ms` after the requested lower bound. The raw
Kubernetes logs have only a lower bound and may contain a small amount of later
traffic; all counts and delay statistics below use only the strict Jaeger
window.

## Decoder And Relay Result

Jaeger returned `112` independent traces containing `112` spans. This is
expected: PFCP request/response transaction correlation has not been
implemented yet, so each decoded message remains its own trace.

Every span has:

```text
pfcp.decode.enabled = true
pfcp.decode.status  = header_decoded
decoder.error       = absent
tracing.dropped_events = 0
decoder.dropped_events = 0
```

The decoded procedure counts are balanced in both directions:

```text
PFCP AssociationSetupRequest / Response       = 1 / 1
PFCP HeartbeatRequest / Response               = 44 / 44
PFCP SessionEstablishmentRequest / Response    = 4 / 4
PFCP SessionModificationRequest / Response     = 4 / 4
PFCP SessionDeletionRequest / Response         = 3 / 3
total                                           = 112
```

All observed messages have `pfcp.fo_flag=false` and
`pfcp.datagram.bundled=false`; this live capture contains no PFCP Follow-On
bundles. The decoder's multi-message datagram path is covered by its unit test,
but still needs a live or generated `FO=1` validation case. All observed
messages also have `pfcp.mp_flag=false`. Node-related Association Setup and
Heartbeat messages have `pfcp.s_flag=false` (`90` spans); session messages have
`pfcp.s_flag=true` (`22` spans).

The proxy log and decoded tags agree on the first Association Setup exchange:

```text
proxy raw prefix                   decoded fields
20 05 00 1e 98 50 aa 00            type=5  AssociationSetupRequest
                                    S=0, declared length=30, size=34
                                    sequence=9982122

20 06 00 28 98 50 aa 00            type=6  AssociationSetupResponse
                                    S=0, declared length=40, size=44
                                    sequence=9982122
```

The same agreement holds for the first session establishment exchange:

```text
21 32 00 80 [SEID=0] 98 50 b8 00    type=50 SessionEstablishmentRequest
                                    S=1, declared length=128, size=132
                                    sequence=9982136, seid=0x0000000000000000

21 33 00 4a [SEID=1] 98 50 b8 00    type=51 SessionEstablishmentResponse
                                    S=1, declared length=74, size=78
                                    sequence=9982136, seid=0x0000000000000001
```

The SMF log records the matching message-type `6` Association Setup Response,
then resolves the advertised `pfcpproxy10` Node ID FQDN. It also records the
Session Establishment and Session Modification Responses as types `51` and
`53`. The UPF log records four FAR/PDR additions for SEIDs `0x1` through
`0x4`, plus three session deletion requests for SEIDs `0x1` through `0x3`.
Together with the decoded spans, this confirms that the proxy stayed in the
full N4 path while the UE session procedures completed.

## Sequence-Number Observation

An offline comparison of the captured attributes finds `56` request/response
pairs. Each pair has the expected request/response message-type pair and the
same `pfcp.sequence_number`; there are no unpaired messages in this window.
There is also no duplicate `(smf_to_upf, PFCP message type, sequence number)`
request key in this capture.

This is evidence that the header fields needed for a future PFCP transaction
correlator are available. It is not yet an online correlation or retransmission
detector: a future implementation must scope sequence numbers by the PFCP peer
association and treat a repeated request key as a retransmission event rather
than a new transaction.

## Delay And Health

```text
proxy.forward.duration_ms: min=0.013448 avg=1.096775 max=2.979987
decoder.queue_delay_ms:    min=0.009505 avg=0.176118 max=0.852773
decoder.duration_ms:       min=0.006835 avg=0.061403 max=0.134226
```

`proxy.forward.duration_ms` ends before the forwarded datagram is submitted to
the asynchronous trace worker. `decoder.queue_delay_ms` is time spent waiting
after forwarding, and `decoder.duration_ms` is worker-side header decoding
time. Neither metric is packet-forwarding overhead. The running proxy pod has
zero restarts.

## Result

The PFCP header light decoder is working on the live N4 path. It correctly
classifies Association Setup, Heartbeat, Session Establishment, Session
Modification, and Session Deletion messages; exports sequence numbers and
SEIDs when the S flag is present; and leaves forwarding asynchronous with no
observed queue drops.

## Remaining Scope

- Parse selected PFCP Information Elements such as F-SEID, PDR/FAR, and TEID.
- Implement request/response transaction traces using the scoped sequence
  number and peer-association identity.
- Mark retransmissions without creating a second transaction.
- Validate `FO=1` multi-message datagrams with live or generated traffic.
