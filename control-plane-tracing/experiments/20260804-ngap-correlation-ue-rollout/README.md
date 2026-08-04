# NGAP Correlation Across UE Rollouts

## Metadata

- Date: 2026-08-04
- Experiment start: 2026-08-04 10:39:55.445 UTC
- Experiment start: 2026-08-04 18:39:55.445 Asia/Taipei
- Capture end: 2026-08-04 10:50:24.512 UTC
- Git hash under test: `bf3281b`
- Topology: OAI split RAN with NGAP/N2 routed through `ngapproxy10` and F1-C
  routed through `f1proxy10`
- Scope: validate NGAP UE correlation across repeated NR-UE rollouts while the
  CU, DU, AMF, and proxy pods stay running

## Objective

Confirm that repeated NR-UE rollouts can be represented as separate NGAP UE
contexts, and check whether the NGAP correlator can tolerate UE identifier reuse
after `UEContextReleaseComplete`.

## Rollout Commands

The NR-UE deployment was restarted three times without undeploying the CU, DU,
AMF, or proxy pods:

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
run 1: 2026-08-04T10:43:58.220Z
run 2: 2026-08-04T10:44:51.984Z
run 3: 2026-08-04T10:45:46.110Z
```

## Raw Evidence

- `jaeger-ngapproxy-traces.raw.json`: raw Jaeger API output for `ngapproxy10`,
  using a start time of `1785839995445000` Unix microseconds.
- `jaeger-f1proxy-traces.raw.json`: raw Jaeger API output for `f1proxy10`, using
  the same time window as an F1AP control-flow reference.
- `ngapproxy-log.raw.txt`: raw NGAP proxy log from the capture window.
- `f1proxy-log.raw.txt`: raw F1AP proxy log from the capture window.
- `cu-log.raw.txt`: raw CU log from the capture window.
- `amf-log.raw.txt`: raw AMF log from the capture window.
- `proxy-pods.raw.txt`: raw proxy pod image and restart-count snapshot.
- `oai-pods.raw.txt`: raw OAI pod snapshot.

The proxy pod snapshot showed both proxy containers running with zero restarts:

```text
f1proxy10 restart_count = 0
ngapproxy10 restart_count = 0
```

Image digests under test:

```text
f1proxy10:
  docker-pullable://genechen0203/f1ap-sctp-proxy@sha256:45fc52abccb502d25cc1177b3eba64d5d964eba3ba0760345c776e1ed5219290

ngapproxy10:
  docker-pullable://genechen0203/ngap-sctp-proxy@sha256:8b92c88c88bd1814e17686454cd58691770b6475fa927c35c4cd63b97ae1fbe8
```

## Jaeger NGAP Summary

The NGAP Jaeger query returned:

```text
trace_count = 62
span_count = 62
earliest span start = 1785839995445394
earliest span start = 2026-08-04 10:39:55.445394 UTC
latest span start = 1785840357922881
latest span start = 2026-08-04 10:45:57.922881 UTC
decode_errors = 0
decoder.dropped_events max = 0
```

The earliest span matches the requested `NGSetupRequest` start, so this capture
does not include earlier NGAP traces.

Decode strategy and status:

```text
decoder.strategy:
  pycrate = 62

ngap.decode.status:
  decoded = 62
```

Message counts:

```text
NGSetupRequest = 1
NGSetupResponse = 1
InitialUEMessage = 4
DownlinkNASTransport = 11
UplinkNASTransport = 19
InitialContextSetupRequest = 4
InitialContextSetupResponse = 4
UERadioCapabilityInfoIndication = 4
PDUSessionResourceSetupRequest = 4
PDUSessionResourceSetupResponse = 4
UEContextReleaseCommand = 3
UEContextReleaseComplete = 3
```

Direction counts:

```text
cu_to_amf = 39
amf_to_cu = 23
```

## NGAP Correlation Evidence

The NGAP correlator emitted UE attributes on 60 UE-associated spans:

```text
ngap.correlation.kind:
  ue = 60
  none = 2

ngap.ue.binding_state:
  ran_only = 4
  ran_amf_bound = 56

ngap.ue.binding_released:
  true = 3
```

All UE-associated spans shared the same correlation ID:

```text
ngap.ue.correlation_id:
  ngap-ue-ran-1 = 60 spans
```

The raw Jaeger data shows four separate attach flows, all using
`RAN-UE-NGAP-ID=1`, while the AMF UE NGAP ID increments across contexts:

| Flow | First span UTC | Last span UTC | RAN UE NGAP ID | AMF UE NGAP ID | Spans | Release |
| --- | --- | --- | ---: | ---: | ---: | --- |
| initial attached UE | 10:41:46.487 | 10:43:58.661 | 1 | 1 | 16 | yes |
| rollout run 1 | 10:44:09.206 | 10:44:52.414 | 1 | 2 | 16 | yes |
| rollout run 2 | 10:45:03.388 | 10:45:46.565 | 1 | 3 | 16 | yes |
| rollout run 3 | 10:45:57.374 | 10:45:57.922 | 1 | 4 | 12 | no |

The `ngap.ue.message_count` reset to `1` after each release and the AMF UE NGAP
ID changed from `1` to `4`, so the correlator did process release events and
create fresh in-memory bindings. However, the emitted `ngap.ue.correlation_id`
still used only the RAN UE NGAP ID:

```text
ngap-ue-ran-1
```

That makes Jaeger tag grouping merge multiple released UE contexts into one
correlation bucket whenever `RAN-UE-NGAP-ID` is reused.

## NGAP Timeline

Top-level NGAP setup:

```text
10:39:55.445 cu_to_amf NGSetupRequest ran=- amf=-
10:39:55.451 amf_to_cu NGSetupResponse ran=- amf=-
```

UE-associated timeline grouped by the current correlation ID:

```text
10:41:46.487 cu_to_amf InitialUEMessage ran=1 amf=- state=ran_only msg_count=1
10:41:46.532 amf_to_cu DownlinkNASTransport ran=1 amf=1 state=ran_amf_bound msg_count=2
10:41:47.036 amf_to_cu PDUSessionResourceSetupRequest ran=1 amf=1 state=ran_amf_bound msg_count=11
10:41:47.064 cu_to_amf PDUSessionResourceSetupResponse ran=1 amf=1 state=ran_amf_bound msg_count=12
10:43:58.639 amf_to_cu UEContextReleaseCommand ran=1 amf=1 state=ran_amf_bound msg_count=15
10:43:58.661 cu_to_amf UEContextReleaseComplete ran=1 amf=1 state=ran_amf_bound released=true msg_count=16

10:44:09.206 cu_to_amf InitialUEMessage ran=1 amf=- state=ran_only msg_count=1
10:44:09.231 amf_to_cu DownlinkNASTransport ran=1 amf=2 state=ran_amf_bound msg_count=2
10:44:09.736 amf_to_cu PDUSessionResourceSetupRequest ran=1 amf=2 state=ran_amf_bound msg_count=11
10:44:09.765 cu_to_amf PDUSessionResourceSetupResponse ran=1 amf=2 state=ran_amf_bound msg_count=12
10:44:52.390 amf_to_cu UEContextReleaseCommand ran=1 amf=2 state=ran_amf_bound msg_count=15
10:44:52.414 cu_to_amf UEContextReleaseComplete ran=1 amf=2 state=ran_amf_bound released=true msg_count=16

10:45:03.388 cu_to_amf InitialUEMessage ran=1 amf=- state=ran_only msg_count=1
10:45:03.412 amf_to_cu DownlinkNASTransport ran=1 amf=3 state=ran_amf_bound msg_count=2
10:45:03.910 amf_to_cu PDUSessionResourceSetupRequest ran=1 amf=3 state=ran_amf_bound msg_count=11
10:45:03.941 cu_to_amf PDUSessionResourceSetupResponse ran=1 amf=3 state=ran_amf_bound msg_count=12
10:45:46.542 amf_to_cu UEContextReleaseCommand ran=1 amf=3 state=ran_amf_bound msg_count=15
10:45:46.565 cu_to_amf UEContextReleaseComplete ran=1 amf=3 state=ran_amf_bound released=true msg_count=16

10:45:57.374 cu_to_amf InitialUEMessage ran=1 amf=- state=ran_only msg_count=1
10:45:57.395 amf_to_cu DownlinkNASTransport ran=1 amf=4 state=ran_amf_bound msg_count=2
10:45:57.893 amf_to_cu PDUSessionResourceSetupRequest ran=1 amf=4 state=ran_amf_bound msg_count=11
10:45:57.922 cu_to_amf PDUSessionResourceSetupResponse ran=1 amf=4 state=ran_amf_bound msg_count=12
```

## CU And AMF Cross-Check

The CU log confirms that CU UE ID `1` and NGAP RAN UE ID `1` were reused, while
the F1AP DU UE ID and RNTI changed on each UE attach:

```text
Create UE context: CU UE ID 1 DU UE ID 7731 (rnti: 1e33)
Initial Context Setup UE RAN ID 1 UE AMF ID 1
removed UE CU UE ID 1/RNTI 1e33

Create UE context: CU UE ID 1 DU UE ID 54662 (rnti: d586)
Initial Context Setup UE RAN ID 1 UE AMF ID 2
removed UE CU UE ID 1/RNTI d586

Create UE context: CU UE ID 1 DU UE ID 202 (rnti: 00ca)
Initial Context Setup UE RAN ID 1 UE AMF ID 3
removed UE CU UE ID 1/RNTI 00ca

Create UE context: CU UE ID 1 DU UE ID 3094 (rnti: 0c16)
Initial Context Setup UE RAN ID 1 UE AMF ID 4
```

The AMF log confirms three NGAP release completions during the rollout window:

```text
Received UE_CONTEXT_RELEASE_COMPLETE message, handling
Received UE_CONTEXT_RELEASE_COMPLETE message, handling
Received UE_CONTEXT_RELEASE_COMPLETE message, handling
```

## NGAP Delay Summary

All NGAP spans:

```text
decoder.queue_delay_ms:
  min = 0.032895
  avg = 5.127208
  max = 305.458455

decoder.duration_ms:
  min = 0.801909
  avg = 7.912525
  max = 311.686831

proxy.forward.duration_ms:
  min = 0.011943
  avg = 0.143305
  max = 0.513888
```

The high all-span average is caused by the first NG setup pycrate warm-up:

```text
10:39:55.445 NGSetupRequest:
  decoder.duration_ms = 311.686831

10:39:55.451 NGSetupResponse:
  decoder.queue_delay_ms = 305.458455
```

UE-associated NGAP spans only:

```text
decoder.queue_delay_ms:
  min = 0.032895
  avg = 0.206361
  max = 0.765104

decoder.duration_ms:
  min = 1.086720
  avg = 2.968130
  max = 8.623639

proxy.forward.duration_ms:
  min = 0.011943
  avg = 0.144862
  max = 0.513888
```

Forwarding still completed before decode and correlation work, so these decoder
attributes are trace annotation latency rather than packet forwarding overhead.

## F1AP Reference Summary

The F1AP Jaeger query over the same window returned:

```text
trace_count = 96
span_count = 96
decode_errors = 0
decoder.dropped_events max = 0
```

Observed F1AP UE correlation IDs:

| Correlation ID | First span UTC | Last span UTC | DU UE ID | CU UE ID | RNTI hex | Spans | Release |
| --- | --- | --- | ---: | ---: | --- | ---: | --- |
| `f1ap-ue-du-7731` | 10:41:46.476 | 10:43:58.661 | 7731 | 1 | 0x1e33 | 24 | yes |
| `f1ap-ue-du-54662` | 10:44:09.194 | 10:44:52.413 | 54662 | 1 | 0xd586 | 24 | yes |
| `f1ap-ue-du-202` | 10:45:03.379 | 10:45:46.565 | 202 | 1 | 0x00ca | 24 | yes |
| `f1ap-ue-du-3094` | 10:45:57.365 | 10:45:57.928 | 3094 | 1 | 0x0c16 | 20 | no |

This confirms that the F1AP proxy stayed healthy in the same window and that
F1AP correlation did not regress.

## Finding

This experiment validates the NGAP pycrate decoder and confirms that the NGAP
correlator sees UE binding and release events:

- all 62 NGAP spans decoded with `decoder.strategy=pycrate`;
- all 60 UE-associated NGAP spans had `ngap.correlation.kind=ue`;
- three `UEContextReleaseComplete` spans set `ngap.ue.binding_released=true`;
- message counts reset after each release, showing that in-memory bindings were
  cleared;
- no proxy restarts, decode errors, or dropped trace events were observed.

However, this experiment also exposes a correlation ID design issue. OAI reused
`RAN-UE-NGAP-ID=1` for every rollout, so the current correlation ID
`ngap-ue-ran-1` merged four separate UE contexts into one Jaeger tag group. The
next change should make NGAP correlation IDs generation-scoped, for example by
allocating a new stable context ID at each `InitialUEMessage` after release and
then keeping that ID after the AMF UE NGAP ID is learned.
