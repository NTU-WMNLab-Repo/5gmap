# F1AP Correlation Across UE Rollouts

## Metadata

- Date: 2026-07-30
- Experiment start: 2026-07-30 14:38:09.717 UTC
- Experiment start: 2026-07-30 22:38:09.717 Asia/Taipei
- Git hash under test: `04c4459`
- Topology: OAI split RAN with F1-C routed through `f1proxy10`
- Scope: validate F1AP correlation across repeated NR-UE rollouts while the
  CU, DU, and F1 proxy stay running

## Objective

Confirm that repeated NR-UE rollouts create distinct F1AP UE correlation IDs
when the DU UE ID and C-RNTI change, and confirm that reused CU UE ID `1` does
not cause the correlator to attach a new UE to an old context.

## Rollout Commands

The NR-UE deployment was restarted three times without undeploying the CU, DU,
or F1 proxy:

```sh
for i in 1 2 3; do
  echo "=== UE rollout run $i ==="
  date -u +"START_UTC=%Y-%m-%dT%H:%M:%S.%3NZ"

  kubectl rollout restart deployment/oai-nr-ue10 -n oai
  kubectl rollout status deployment/oai-nr-ue10 -n oai --timeout=420s

  sleep 45
done
```

Observed rollout starts:

```text
run 1: 2026-07-30T14:38:09.717Z
run 2: 2026-07-30T14:39:03.892Z
run 3: 2026-07-30T14:39:57.810Z
```

## Raw Evidence

- `cu-log.raw.txt`: raw CU log captured from
  `2026-07-30T14:38:09.717Z`.
- `f1proxy-log.raw.txt`: raw F1 proxy log captured from
  `2026-07-30T14:38:09.717Z`.
- `jaeger-f1proxy-traces.raw.json`: raw Jaeger API output for `f1proxy10`, using
  a start time of `1785422289717000` Unix microseconds.

The Jaeger raw data contains:

```text
trace_count = 72
span_count = 72
earliest span start = 1785422290031587
earliest span start = 2026-07-30 14:38:10.031587 UTC
latest span start = 1785422409306673
latest span start = 2026-07-30 14:40:09.306673 UTC
```

The earliest span is after the requested experiment start timestamp, so this
capture does not include earlier F1AP traces.

## CU Log Evidence

Each rollout first released the currently attached UE, then created a new UE
context. The CU reused CU UE ID `1`, while DU UE ID and RNTI changed:

```text
old context released:
  removed UE CU UE ID 1/RNTI b343

run 1 new context:
  Create UE context: CU UE ID 1 DU UE ID 24320 (rnti: 5f00)

run 2 old context released:
  removed UE CU UE ID 1/RNTI 5f00

run 2 new context:
  Create UE context: CU UE ID 1 DU UE ID 65120 (rnti: fe60)

run 3 old context released:
  removed UE CU UE ID 1/RNTI fe60

run 3 new context:
  Create UE context: CU UE ID 1 DU UE ID 39150 (rnti: 98ee)
```

The first release belongs to the UE that was already attached before this
rollout experiment started. It is useful evidence because the F1 proxy had to
clear that old binding before observing the next attach.

## Jaeger Correlation Evidence

Jaeger message counts:

```text
ULRRCMessageTransfer = 27
DLRRCMessageTransfer = 24
UEContextReleaseCommand = 3
UEContextReleaseComplete = 3
InitialULRRCMessageTransfer = 3
UEContextSetupRequest = 3
UEContextSetupResponse = 3
UEContextModificationRequest = 3
UEContextModificationResponse = 3
```

Correlation summary:

```text
f1ap.correlation.kind:
  ue = 72

f1ap.ue.binding_state:
  cu_du_bound = 69
  du_only = 3

f1ap.ue.binding_released:
  true = 3
```

Observed UE correlation IDs:

| Correlation ID | Spans | First span UTC | Last span UTC | Meaning |
| --- | ---: | --- | --- | --- |
| `f1ap-ue-du-45891` | 4 | 14:38:10.031 | 14:38:10.268 | Old UE released by rollout run 1 |
| `f1ap-ue-du-24320` | 24 | 14:38:21.209 | 14:39:04.349 | New UE from rollout run 1 |
| `f1ap-ue-du-65120` | 24 | 14:39:15.026 | 14:39:58.261 | New UE from rollout run 2 |
| `f1ap-ue-du-39150` | 20 | 14:40:08.939 | 14:40:09.306 | New UE from rollout run 3 |

The three new UE contexts map to three different correlation IDs:

```text
DU UE ID 24320 / RNTI 5f00 -> f1ap-ue-du-24320
DU UE ID 65120 / RNTI fe60 -> f1ap-ue-du-65120
DU UE ID 39150 / RNTI 98ee -> f1ap-ue-du-39150
```

Although CU UE ID `1` was reused in every rollout, the correlator did not keep
using the old UE correlation ID. Each new `InitialULRRCMessageTransfer` started
as `du_only`, then later messages became `cu_du_bound` after the CU UE ID was
observed.

Release evidence in Jaeger:

```text
14:38:10.268 UEContextReleaseComplete f1ap-ue-du-45891 binding_released=true
14:39:04.349 UEContextReleaseComplete f1ap-ue-du-24320 binding_released=true
14:39:58.261 UEContextReleaseComplete f1ap-ue-du-65120 binding_released=true
```

No later span reused those released correlation IDs after their
`UEContextReleaseComplete` span.

## Follow-Up Debug Questions

Two questions came up while inspecting this capture in the Jaeger UI.

### Why does Jaeger show `f1ap.ue.c_rnti = 39150` instead of `98ee`?

This is a display-format issue, not evidence that the decoder changed the RNTI.
The CU log prints RNTI in hexadecimal:

```text
RNTI 98ee
```

Jaeger stores numeric span attributes as numbers and displays them in decimal:

```text
0x98ee = 39150
0x5f00 = 24320
0xfe60 = 65120
0xb343 = 45891
```

The raw Jaeger JSON confirms that the first `InitialULRRCMessageTransfer` of
each new UE has both the DU UE ID and C-RNTI as the same numeric value:

```text
InitialULRRCMessageTransfer:
  f1ap.gnb.du.ue.f1ap.id = 24320
  f1ap.c.rnti = 24320
  f1ap.ue.c_rnti = 24320

InitialULRRCMessageTransfer:
  f1ap.gnb.du.ue.f1ap.id = 65120
  f1ap.c.rnti = 65120
  f1ap.ue.c_rnti = 65120

InitialULRRCMessageTransfer:
  f1ap.gnb.du.ue.f1ap.id = 39150
  f1ap.c.rnti = 39150
  f1ap.ue.c_rnti = 39150
```

In this OAI run, the DU UE F1AP ID was numerically equal to the C-RNTI. That can
make the Jaeger UI look like the proxy copied the DU UE ID into the RNTI field,
but the CU log's hexadecimal RNTI values match the same integers.

After this observation, the proxy was adjusted to emit display-friendly hex
attributes for future traces:

```text
f1ap.c.rnti.hex
f1ap.ue.c_rnti.hex
```

The raw JSON in this experiment was captured before that display-only change, so
those hex attributes are not present in this file.

### Why does the trace view not show `UEContextReleaseComplete`?

The raw Jaeger JSON contains three `UEContextReleaseComplete` spans:

```text
14:38:10.268 UEContextReleaseComplete f1ap-ue-du-45891 binding_released=true
14:39:04.349 UEContextReleaseComplete f1ap-ue-du-24320 binding_released=true
14:39:58.261 UEContextReleaseComplete f1ap-ue-du-65120 binding_released=true
```

However, each F1AP message is currently emitted as its own OpenTelemetry trace:

```text
trace_sizes:
  one span per trace = 72
  multi-span traces = 0
```

So the Jaeger trace detail page for one F1AP span will not automatically show
the matching `UEContextReleaseComplete`. The current correlation model is
attributes-based: use Jaeger search tags such as `f1ap.ue.correlation_id` to find
all spans for one UE. It is not yet using shared trace IDs, links, or
parent-child relationships.

The last rollout's new UE, `f1ap-ue-du-39150`, also has no release span in this
capture because the experiment ended while that UE was still attached:

```text
f1ap-ue-du-39150:
  release_complete_spans = 0
```

That is expected unless another rollout or undeploy is performed after run 3.

## Decode And Forwarding Measurements

Jaeger query over this rollout experiment window:

```text
pycrate_span_count = 72
asn1.value count = 0

decoder.queue_delay_ms:
  min = 0.028565
  avg = 0.3165512638888889
  max = 5.51588

decoder.duration_ms:
  min = 0.655812
  avg = 2.553969611111111
  max = 10.113554

proxy.forward.duration_ms:
  min = 0.01334
  avg = 0.79794875
  max = 5.452674

decoder.dropped_events:
  max = 0
```

The decoder worker delay is lower than earlier pycrate experiments because the
proxy process was already warm and the large `asn1.value` export remained
disabled. Packet forwarding still completed independently of decode and
correlation work.

## Finding

The repeated rollout experiment supports the current F1AP correlation design:

- different DU UE IDs and RNTIs produced distinct `f1ap.ue.correlation_id`
  values;
- CU UE ID reuse did not cause visible cross-run miscorrelation;
- `UEContextReleaseComplete` spans set `f1ap.ue.binding_released=true`;
- released correlation IDs were not reused by later UE attach flows;
- no trace events were dropped.

The next step should be to add a small trace analysis helper that can summarize
Jaeger raw output by `f1ap.ue.correlation_id`. This will make future NGAP and
cross-protocol correlation experiments easier to validate without repeatedly
writing one-off parsing scripts.

## Analysis Helper

After this experiment, a small helper was added for Jaeger raw JSON files:

```sh
python control-plane-tracing/tools/analyze_jaeger_f1ap.py \
  control-plane-tracing/experiments/20260730-f1ap-correlation-ue-rollout/jaeger-f1proxy-traces.raw.json
```

It groups spans by `f1ap.ue.correlation_id` and prints each group's timeline,
DU/CU UE IDs, RNTI, release status, and delay statistics.
