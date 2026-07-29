# F1AP Pycrate Decode Without ASN.1 Value Export

## Metadata

- Date: 2026-07-29
- Experiment start: 2026-07-29 13:10:20.214 UTC
- Experiment start: 2026-07-29 21:10:20.214 Asia/Taipei
- Git hash under test: `960b09b`
- Topology: OAI split RAN with F1-C routed through `f1proxy10`
- Scope: measure F1AP pycrate decode cost after disabling large ASN.1 value
  export

## Runtime Decode Settings

The F1AP proxy was run with:

```yaml
- name: ASN1_COPY_ROOT
  value: "0"
- name: ASN1_INCLUDE_VALUE
  value: "0"
```

`ASN1_COPY_ROOT=0` keeps the single trace worker from deep-copying the pycrate
root object before every decode. `ASN1_INCLUDE_VALUE=0` keeps the proxy from
placing the large truncated pycrate `get_val()` representation into the
`asn1.value` Jaeger span attribute.

## Raw Evidence

- `cu-log.raw.txt`: raw CU log captured with Kubernetes log filtering from
  `2026-07-29T13:10:20.214Z`.
- `jaeger-f1proxy-traces.raw.json`: raw Jaeger API output for `f1proxy10`, using
  a start time of `1785330620214000` Unix microseconds.

The Jaeger raw data contains:

```text
trace_count = 24
span_count = 24
F1SetupRequest count = 1
earliest span start = 1785330620214900
```

The earliest span is after the requested experiment start timestamp, so this
capture does not include earlier F1AP traces.

## CU Log Alignment

The CU log begins at the F1 setup phase for this experiment window:

```text
CU_handle_F1_SETUP_REQUEST
Received F1 Setup Request from gNB_DU 3584
sending F1 Setup Response
CU_handle_gNB_DU_CONFIGURATION_UPDATE
F1AP_GNB_DU_CONFIGURATION_UPDATE_ACKNOWLEDGE
```

The UE context creation log for this run was:

```text
Create UE context: CU UE ID 1 DU UE ID 41295 RNTI a14f
```

The Jaeger F1AP spans decoded by the proxy contained matching identifiers:

```text
InitialULRRCMessageTransfer:
  f1ap.gnb.du.ue.f1ap.id = 41295
  f1ap.transaction.id = 0

Later UE-specific F1AP spans:
  f1ap.gnb.cu.ue.f1ap.id = 1
  f1ap.gnb.du.ue.f1ap.id = 41295
```

This shows the reduced-export configuration still preserves the identifiers
needed for F1AP correlation.

## Jaeger Decode Evidence

All spans in this capture used pycrate:

```text
pycrate_count = 24
asn1.decode.full = true
asn1.value count = 0
decoder.dropped_events max = 0
```

The important difference from the previous run is `asn1.value count = 0`.
Jaeger no longer contains the large debug representation of the complete pycrate
decoded tree.

Promoted attributes still remain available, including:

```text
f1ap.ie.names
f1ap.transaction.id
f1ap.gnb.cu.ue.f1ap.id
f1ap.gnb.du.ue.f1ap.id
```

## Delay Measurements

Jaeger query over this experiment window:

```text
pycrate_span_count = 24

decoder.queue_delay_ms:
  min = 0.02654
  avg = 74.8212519583333
  max = 598.018521

decoder.duration_ms:
  min = 0.221887
  avg = 26.7685915416667
  max = 596.852091

decoder.dropped_events:
  max = 0
```

Compared with the previous pycrate run:

| Metric | Previous run | This run | Change |
| --- | ---: | ---: | ---: |
| queue delay avg | 14864.900832125 ms | 74.8212519583333 ms | about 199x lower |
| queue delay max | 34852.841044 ms | 598.018521 ms | about 58x lower |
| decode duration avg | 1667.46902675 ms | 26.7685915416667 ms | about 62x lower |
| decode duration max | 2024.553954 ms | 596.852091 ms | about 3.4x lower |
| dropped events max | 0 | 0 | unchanged |

The first `F1SetupRequest` still took about 596 ms to decode. After that initial
cost, most F1AP messages decoded in the low millisecond range.

## Trade-Off

What was sacrificed:

- Jaeger no longer shows `asn1.value`.
- The full decoded pycrate tree cannot be inspected from the span attributes.
- Debugging unknown or newly promoted fields from Jaeger alone is harder.

What remains:

- pycrate full decode still runs.
- `asn1.decode.full=true` is still present.
- message names, IE summaries, transaction ID, CU UE F1AP ID, and DU UE F1AP ID
  remain available as promoted attributes.

Impact on correlation:

- This should not block F1AP correlation.
- Correlation only needs stable promoted identifiers such as
  `f1ap.gnb.cu.ue.f1ap.id`, `f1ap.gnb.du.ue.f1ap.id`, transaction ID, and
  possibly C-RNTI.
- `asn1.value` is useful for debugging extraction gaps, but it is not required
  for normal correlation once the needed fields are promoted.

## Finding

Because disabling `asn1.value` and avoiding pycrate root copying greatly reduced
decode-worker delay while preserving the identifiers needed for correlation, the
next implementation step should use this reduced-export mode as the default
runtime profile for F1AP correlation experiments.
