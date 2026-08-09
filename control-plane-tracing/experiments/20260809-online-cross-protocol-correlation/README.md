# Online Cross-Protocol Correlation Initial Experiment

## Metadata

- Date: 2026-08-09
- Experiment start: 2026-08-09 10:57:26.344 UTC
- Experiment start: 2026-08-09 18:57:26.344 Asia/Taipei
- Capture end: 2026-08-09 11:14:59.781 UTC
- Git hash under test: `739573a` (`Fix correlator container module startup`)
- Topology: OAI split RAN with F1AP/F1-C through `f1proxy10`, NGAP/N2 through
  `ngapproxy10`, and both proxies connected to the shared
  `control-plane-correlator`
- Scope: first online F1AP/NGAP UE trace correlation run with
  `RanProxy=1` and `CrossProtocolCorrelate=1`

## Objective

Verify that one UE lifecycle receives one shared Jaeger trace ID across the
F1AP and NGAP proxy spans, including both protocol release procedures.

## Raw Evidence

- `jaeger-ngapproxy-traces.raw.json`: raw Jaeger API response for
  `ngapproxy10`.
- `jaeger-f1proxy-traces.raw.json`: raw Jaeger API response for `f1proxy10`.
- `ngapproxy-log.raw.txt`: raw NGAP proxy log.
- `f1proxy-log.raw.txt`: raw F1AP proxy log.
- `correlator-log.raw.txt`: raw online correlator HTTP request log.
- `cu-log.raw.txt`: raw CU log.
- `oai-pods.raw.txt`: raw OAI pod snapshot.

Both Jaeger responses use the same inclusive query window:

```text
start = 1786273046344000
end   = 1786274099781000
```

The earliest returned NGAP span is the requested `NGSetupRequest`:

```text
1786273046344917 = 2026-08-09 10:57:26.344917 UTC
```

No earlier NGAP trace is included in the captured raw data.

## Trace And Decode Summary

The two Jaeger responses contain 12 unique traces and 158 unique spans:

```text
F1AP spans = 96
NGAP spans = 62
UE-associated online-correlation spans = 152
decoder.strategy = pycrate for all 158 spans
decoder.dropped_events max = 0
```

The four observed UE lifecycles produced these trace shapes:

| UE lifecycle | Trace ID | Spans | Outcome |
| --- | --- | ---: | --- |
| 1 attach | `d1399956f421015878063bb59652d72c` | 32 | F1AP/NGAP setup and session traffic matched. |
| 1 F1AP release | `bf3e3ba2daa132eb985f842a715d91ca` | 4 | Incorrectly split into a local F1AP trace. |
| 1 NGAP release | `08f6a68210f08b5267220a819ef5611b` | 4 | Incorrectly split into a local NGAP trace. |
| 2 | `f49c0749368ab021cbb78c5b05b636c5` | 40 | Complete matched lifecycle with both releases. |
| 3 | `b9915bd89c8ded9950a86041ab7bf4c9` | 40 | Complete matched lifecycle with both releases. |
| 4 | `42ef51767aec58b9506cca075de043cc` | 32 | Matched lifecycle still active at capture end. |

The remaining six traces are the two NG setup and four F1 setup/configuration
messages; they have no UE identifiers and correctly remain outside online UE
correlation.

All-span delay statistics:

```text
decoder.queue_delay_ms: min=0.033384 avg=16.260805 max=598.238641
decoder.duration_ms:    min=0.226636 avg=8.260906  max=597.215741
proxy.forward.duration_ms: min=0.008591 avg=0.300688 max=5.282399
```

UE-associated spans only, excluding setup warm-up:

```text
decoder.queue_delay_ms: min=0.033384 avg=3.021423 max=19.319859
decoder.duration_ms:    min=0.849763 avg=2.519940 max=10.801211
proxy.forward.duration_ms: min=0.008591 avg=0.310098 max=5.282399
```

Packet forwarding completed before async decode and online correlation, so the
decoder and correlator delays remain trace annotation latency rather than SCTP
forwarding overhead.

## First UE Release Split

The first UE initially correlated correctly as `ue-online-00000001`. Its 32
spans include both F1AP and NGAP and have
`ue.online.confidence=cross_protocol` and `ue.online.state=matched`.

```text
10:59:22.383071 UTC  F1AP InitialULRRCMessageTransfer
10:59:22.396984 UTC  NGAP InitialUEMessage
10:59:22.992965 UTC  last span in shared trace d1399956...

11:01:10.389421 UTC  first F1AP release-side span
11:01:10.390038 UTC  first NGAP release-side span
```

The quiet interval is `107.606456 s`, exceeding the configured
`ONLINE_CORRELATION_IDLE_TIMEOUT_MS=60000`. The correlator therefore forced the
matched lifecycle closed before either protocol release arrived. The later
F1AP and NGAP events each created a new local lifecycle, yielding the separate
four-span traces shown above:

```text
bf3e3ba2...  F1AP ULRRCMessageTransfer, DLRRCMessageTransfer,
              UEContextReleaseCommand, UEContextReleaseComplete
              ue.correlation_id=ue-online-00000003
              ue.online.confidence=local

08f6a682...  NGAP UplinkNASTransport, DownlinkNASTransport,
              UEContextReleaseCommand, UEContextReleaseComplete
              ue.correlation_id=ue-online-00000004
              ue.online.confidence=local
```

The second and third UE lifecycles each reached both release completions within
the idle window and remained in one 40-span cross-protocol trace. This isolates
the fault to idle handling rather than F1AP/NGAP matching, decoding, or span
export connectivity.

The CU log independently confirms that the first lifecycle used CU UE ID `1`,
DU UE ID `61485`, and RNTI `f02d`, then removed that UE context before the next
UE attach. The main F1AP trace carries DU UE ID `61485` and CU UE ID `1`; the
main NGAP trace carries RAN UE NGAP ID `1` and AMF UE NGAP ID `1`.

## Missing Parent Warning

Every one of the 152 UE-associated spans references the synthetic
`parent_span_id` returned by the correlator, but no span with that ID is
exported. For example, all 32 spans in `d1399956...` reference
`c449f1aaae9cd987`, which is absent from the trace.

Jaeger therefore correctly displays both warnings:

```text
This trace may be incomplete: 32 spans have missing parent spans.
parent span ID=c449f1aaae9cd987 is not in the trace;
skipping clock skew adjustment.
```

The phantom parent does not cause the release split, but it makes the trace
tree invalid and prevents Jaeger clock-skew adjustment. It is a separate bug
that should be fixed together with lifecycle closure behavior.

## Findings

- Online F1AP/NGAP matching successfully produced shared trace IDs for active
  UE procedure spans.
- `ONLINE_CORRELATION_IDLE_TIMEOUT_MS` must not force-close a lifecycle that is
  already matched across both protocols merely because the UE is temporarily
  quiet.
- The correlator must export an actual lifecycle root span, or proxies must
  stop attaching spans to a synthetic parent that does not exist.

The next implementation change should retain matched/closing lifecycles until
explicit release and add an exported lifecycle root span. A follow-up run
should repeat a UE lifecycle with an idle period longer than 60 seconds and
verify one complete F1AP/NGAP trace with no missing-parent warning.
