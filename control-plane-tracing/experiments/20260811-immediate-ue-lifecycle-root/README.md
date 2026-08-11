# Immediate UE Lifecycle Root Experiment

## Metadata

- Date: 2026-08-11
- Jaeger query start: 2026-08-11 12:58:02.616 UTC
- Jaeger query start: 2026-08-11 20:58:02.616 Asia/Taipei
- Jaeger query end: 2026-08-11 13:09:00.000 UTC
- Git hash under test: `5c69e6d` (`Export UE lifecycle roots at binding`)
- Topology: OAI split RAN with F1AP/F1-C through `f1proxy10`, NGAP/N2 through
  `ngapproxy10`, and both proxies connected to `control-plane-correlator`
- Scope: validate immediate export of a real UE lifecycle root and terminal
  release summary with `RanProxy=1` and `CrossProtocolCorrelate=1`

## Objective

Verify that a cross-protocol F1AP/NGAP match immediately produces a real,
visible Jaeger parent span, while a later complete release emits a summary in
the same trace. The experiment also checks that a matched UE remains in one
trace after more than the previous 60-second pending idle timeout.

## Raw Evidence

- `jaeger-ngapproxy-traces.raw.json`: raw Jaeger API response for
  `ngapproxy10`.
- `jaeger-f1proxy-traces.raw.json`: raw Jaeger API response for `f1proxy10`.
- `jaeger-correlator-traces.raw.json`: raw Jaeger API response for
  `control-plane-correlator`.
- `ngapproxy-log.raw.txt`: raw NGAP proxy log from the capture period.
- `f1proxy-log.raw.txt`: raw F1AP proxy log from the capture period.
- `correlator-log.raw.txt`: raw online-correlator HTTP log from the capture
  period.
- `cu-log.raw.txt`: raw CU log from the capture period.
- `oai-pods.raw.txt`: raw OAI pod snapshot.

The three Jaeger responses use this inclusive window:

```text
start = 1786453082616000
end   = 1786453740000000
```

The earliest returned NGAP span is the requested `NGSetupRequest`:

```text
1786453082616874 = 2026-08-11 12:58:02.616874 UTC
```

The CU log independently records `Send NGSetupRequest to AMF` at
`2026-08-11 12:58:02.616578862 UTC`. No earlier NGAP trace is included in the
captured Jaeger data.

## Trace Summary

After de-duplicating the three Jaeger service responses by trace and span ID,
the capture contains:

```text
unique traces = 10
unique spans = 165
F1AP/NGAP proxy spans = 158
UE-associated F1AP/NGAP spans = 152
correlator spans = 7 (4 roots, 3 summaries)
decoder.dropped_events max = 0
```

Four UE lifecycles were matched across F1AP and NGAP. Every lifecycle has one
real `UE lifecycle` root span from `control-plane-correlator`; the first three
also completed and have one `UE lifecycle summary` child span. The fourth UE
was still active at the end of the query window, so it correctly has no
terminal summary yet.

| UE lifecycle | Trace ID | F1AP DU UE ID / RNTI | NGAP generation / AMF ID | Root / summary result |
| --- | --- | --- | --- | --- |
| `ue-online-00000001` | `a42232ecd137c02804d849ad79b16eea` | `45827` / `0xb303` | `1` / `1` | Root duration `12.760 ms`; closed summary duration `107953.291 ms`. |
| `ue-online-00000003` | `3e16d97b7d3daf26761218a42e9f931a` | `42858` / `0xa76a` | `2` / `2` | Root duration `14.226 ms`; closed summary duration `43063.242 ms`. |
| `ue-online-00000005` | `e46ec343d98035f2c33678400d4b6c4e` | `51890` / `0xcab2` | `3` / `3` | Root duration `12.486 ms`; closed summary duration `43321.555 ms`. |
| `ue-online-00000007` | `bd33016af7a12a7dc9c8908cb1730754` | `14140` / `0x373c` | `4` / `4` | Root duration `8.666 ms`; active at capture end, no summary expected. |

The offline cross-protocol analyzer independently matched every F1AP and NGAP
lifecycle. The three released UEs each scored `95/100`; their
`InitialULRRCMessageTransfer -> InitialUEMessage` gaps were `12.761 ms`,
`14.227 ms`, and `12.487 ms`, and their release-complete gaps were
`0.256 ms`, `0.312 ms`, and `0.615 ms`. The active UE scored `90/100` from UE
ID equality, initial-message ordering, and overlapping windows.

## Immediate Root And Release Summary

For the first UE trace, Jaeger contains:

```text
UE lifecycle root
  span ID     = 4e693174614f3d59
  service     = control-plane-correlator
  start       = 2026-08-11 12:59:53.044936 UTC
  duration    = 12.760 ms
  bound time  = 2026-08-11 12:59:53.057697708 UTC

UE lifecycle summary
  span ID     = a189d58a020fd273
  parent ID   = 4e693174614f3d59
  state       = closed
  reason      = release_complete
  duration    = 107953.291485 ms
```

All 40 F1AP/NGAP UE spans in that trace, together with the summary, reference
the real root span. The trace has `42` spans in total: `24` F1AP, `16` NGAP,
one root, and one summary.

The CU log provides an independent alignment check for this same UE:

```text
12:59:53.045626 UTC  Create UE context: CU UE ID 1, DU UE ID 45827, RNTI b303
12:59:53.057666 UTC  Create UE context (ID 1) for AMF
13:01:40.998316 UTC  Remove UE context
```

The root begins about `0.690 ms` before the CU's context-create log and its
binding time is about `0.032 ms` after the NGAP context-create log. The summary
ends about `0.089 ms` before the CU context-removal log. This is consistent
with packet-receive timestamps being close to the CU application log times.

Most importantly, the first lifecycle remained quiet for about `107.953 s`
between binding and final release. It still produced one trace with one root
and one release summary, validating that a matched lifecycle is no longer
force-closed by `ONLINE_CORRELATION_IDLE_TIMEOUT_MS`.

## Parent Integrity And Clock Skew

Every `CHILD_OF` reference whose parent belongs to the same trace resolves to
an exported span. The four UE traces have zero missing-parent references, and
the raw Jaeger responses contain no missing-parent warning. This fixes the
synthetic-parent problem from the 2026-08-09 experiment.

Jaeger does, however, return `534` warnings of this form:

```text
clock skew adjustment disabled; not applying calculated delta of ...
```

The largest requested adjustment is `107.946956202 s`, which closely matches
the first UE's post-binding lifetime. This is expected from the current model:
the root ends and exports at binding, while later protocol child spans remain
in the same trace until release. The warning is not a missing-parent error and
does not discard spans, but it means the root does not temporally enclose its
later children for Jaeger's clock-skew presentation logic.

## Delay And Health

All F1AP/NGAP proxy spans:

```text
decoder.queue_delay_ms:      min=0.032965 avg=16.837437 max=588.373959
decoder.duration_ms:         min=0.235155 avg=8.261283 max=587.411548
proxy.forward.duration_ms:   min=0.014666 avg=0.262229 max=5.143024
```

UE-associated spans only:

```text
decoder.queue_delay_ms:      min=0.032965 avg=3.887202 max=22.820486
decoder.duration_ms:         min=0.695198 avg=2.658101 max=11.442481
proxy.forward.duration_ms:   min=0.014666 avg=0.268747 max=5.143024
```

The proxy and correlator logs contain no `ERROR`, `Exception`, `Traceback`, or
failed-request line in the capture period. The pod snapshot shows the
correlator, both proxies, CU, DU, and UE running with zero restarts.

Packet forwarding still completes before decode, correlation, and OTLP export;
the immediate root export occurs in the asynchronous tracing path and does not
add to SCTP forwarding duration.

## Findings

- Immediate export creates a real visible parent before UE release and removes
  missing-parent references from completed and active UE traces.
- A release summary is emitted once both protocol release completions arrive
  and correctly remains a child of the same root.
- Matched lifecycles survive a post-binding idle interval longer than 60
  seconds and do not split their release messages into a new trace.
- Ending the root at binding introduces Jaeger clock-skew adjustment warnings
  because later child spans outlive their parent interval. The trace contents
  are complete, but this UI/timing behavior needs a deliberate follow-up design
  decision before treating the model as final.
