# NGAP Generation-Scoped Correlation Across UE Rollouts

## Metadata

- Date: 2026-08-04
- Experiment start: 2026-08-04 14:45:06.793 UTC
- Experiment start: 2026-08-04 22:45:06.793 Asia/Taipei
- Capture end: 2026-08-04 14:56:10.442 UTC
- Git hash under test: `22c4390`
- Topology: OAI split RAN with NGAP/N2 routed through `ngapproxy10`
- Scope: validate NGAP generation-scoped UE correlation across repeated NR-UE
  rollouts

## Objective

Confirm that reused `RAN-UE-NGAP-ID` values no longer collapse multiple UE
lifetimes into one Jaeger correlation bucket after adding local NGAP context
generations.

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
run 1: 2026-08-04T14:48:45.144Z
run 2: 2026-08-04T14:49:38.730Z
run 3: 2026-08-04T14:50:32.875Z
```

## Raw Evidence

- `jaeger-ngapproxy-traces.raw.json`: raw Jaeger API output for `ngapproxy10`,
  using a start time of `1785854706793000` Unix microseconds.
- `ngapproxy-log.raw.txt`: raw NGAP proxy log from the capture window.
- `cu-log.raw.txt`: raw CU log from the capture window.
- `amf-log.raw.txt`: raw AMF log from the capture window.
- `proxy-pod.raw.txt`: raw NGAP proxy pod image and restart-count snapshot.
- `oai-pods.raw.txt`: raw OAI pod snapshot.

F1AP raw traces and logs were not stored for this experiment because the check
was focused on NGAP generation-scoped correlation. The OAI pod snapshot still
showed the F1AP proxy pod running with zero restarts during the same window.

The NGAP proxy pod snapshot showed the container running with zero restarts:

```text
ngapproxy10 restart_count = 0
```

Image digest under test:

```text
ngapproxy10:
  docker-pullable://genechen0203/ngap-sctp-proxy@sha256:d7f8e0683c584128b5214f38b8ac566f11e54d0a51034635e7d32d3cc3b36e12
```

## Jaeger NGAP Summary

The NGAP Jaeger query returned:

```text
trace_count = 62
span_count = 62
earliest span start = 1785854706793268
earliest span start = 2026-08-04 14:45:06.793268 UTC
latest span start = 1785855044873704
latest span start = 2026-08-04 14:50:44.873704 UTC
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

## Generation Correlation Evidence

The NGAP correlator emitted UE attributes on 60 UE-associated spans:

```text
ngap.correlation.kind:
  ue = 60
  none = 2

ngap.ue.binding_state:
  ran_only = 4
  ran_amf_bound = 56

ngap.ue.correlation_basis:
  ran_id_generation = 60

ngap.ue.binding_released:
  true = 3
```

The previous NGAP rollout experiment merged every UE context into
`ngap-ue-ran-1`. In this run, the same reused `RAN-UE-NGAP-ID=1` was split into
four generation-scoped correlation IDs:

| Correlation ID | First span UTC | Last span UTC | RAN UE NGAP ID | AMF UE NGAP ID | Generation | Spans | Release |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `ngap-ue-ran-1-gen-1` | 14:46:57.544 | 14:48:45.628 | 1 | 1 | 1 | 16 | yes |
| `ngap-ue-ran-1-gen-2` | 14:48:56.202 | 14:49:39.255 | 1 | 2 | 2 | 16 | yes |
| `ngap-ue-ran-1-gen-3` | 14:49:50.258 | 14:50:33.327 | 1 | 3 | 3 | 16 | yes |
| `ngap-ue-ran-1-gen-4` | 14:50:44.314 | 14:50:44.873 | 1 | 4 | 4 | 12 | no |

The context generation attribute matched the correlation ID for every
UE-associated span:

```text
ngap.ue.context_generation:
  1 = 16 spans
  2 = 16 spans
  3 = 16 spans
  4 = 12 spans
```

This confirms that the proxy still exports the original protocol identifier
`ngap.ue.ran_id=1`, while the Jaeger grouping key now separates each UE
lifetime.

## NGAP Timeline

Top-level NGAP setup:

```text
14:45:06.793 cu_to_amf NGSetupRequest ran=- amf=-
14:45:06.799 amf_to_cu NGSetupResponse ran=- amf=-
```

Generation-scoped UE timeline:

```text
14:46:57.544 cu_to_amf InitialUEMessage ngap-ue-ran-1-gen-1 ran=1 amf=- msg_count=1
14:46:58.095 amf_to_cu PDUSessionResourceSetupRequest ngap-ue-ran-1-gen-1 ran=1 amf=1 msg_count=11
14:46:58.123 cu_to_amf PDUSessionResourceSetupResponse ngap-ue-ran-1-gen-1 ran=1 amf=1 msg_count=12
14:48:45.606 amf_to_cu UEContextReleaseCommand ngap-ue-ran-1-gen-1 ran=1 amf=1 msg_count=15
14:48:45.628 cu_to_amf UEContextReleaseComplete ngap-ue-ran-1-gen-1 ran=1 amf=1 released=true msg_count=16

14:48:56.202 cu_to_amf InitialUEMessage ngap-ue-ran-1-gen-2 ran=1 amf=- msg_count=1
14:48:56.725 amf_to_cu PDUSessionResourceSetupRequest ngap-ue-ran-1-gen-2 ran=1 amf=2 msg_count=11
14:48:56.758 cu_to_amf PDUSessionResourceSetupResponse ngap-ue-ran-1-gen-2 ran=1 amf=2 msg_count=12
14:49:39.231 amf_to_cu UEContextReleaseCommand ngap-ue-ran-1-gen-2 ran=1 amf=2 msg_count=15
14:49:39.255 cu_to_amf UEContextReleaseComplete ngap-ue-ran-1-gen-2 ran=1 amf=2 released=true msg_count=16

14:49:50.258 cu_to_amf InitialUEMessage ngap-ue-ran-1-gen-3 ran=1 amf=- msg_count=1
14:49:50.781 amf_to_cu PDUSessionResourceSetupRequest ngap-ue-ran-1-gen-3 ran=1 amf=3 msg_count=11
14:49:50.810 cu_to_amf PDUSessionResourceSetupResponse ngap-ue-ran-1-gen-3 ran=1 amf=3 msg_count=12
14:50:33.303 amf_to_cu UEContextReleaseCommand ngap-ue-ran-1-gen-3 ran=1 amf=3 msg_count=15
14:50:33.327 cu_to_amf UEContextReleaseComplete ngap-ue-ran-1-gen-3 ran=1 amf=3 released=true msg_count=16

14:50:44.314 cu_to_amf InitialUEMessage ngap-ue-ran-1-gen-4 ran=1 amf=- msg_count=1
14:50:44.845 amf_to_cu PDUSessionResourceSetupRequest ngap-ue-ran-1-gen-4 ran=1 amf=4 msg_count=11
14:50:44.873 cu_to_amf PDUSessionResourceSetupResponse ngap-ue-ran-1-gen-4 ran=1 amf=4 msg_count=12
```

## CU And AMF Cross-Check

The CU log confirms that CU UE ID `1` and NGAP RAN UE ID `1` were reused, while
each UE attach had a different DU UE ID and RNTI:

```text
Create UE context: CU UE ID 1 DU UE ID 30295 (rnti: 7657)
Initial Context Setup UE RAN ID 1 UE AMF ID 1
removed UE CU UE ID 1/RNTI 7657

Create UE context: CU UE ID 1 DU UE ID 4153 (rnti: 1039)
Initial Context Setup UE RAN ID 1 UE AMF ID 2
removed UE CU UE ID 1/RNTI 1039

Create UE context: CU UE ID 1 DU UE ID 17432 (rnti: 4418)
Initial Context Setup UE RAN ID 1 UE AMF ID 3
removed UE CU UE ID 1/RNTI 4418

Create UE context: CU UE ID 1 DU UE ID 11658 (rnti: 2d8a)
Initial Context Setup UE RAN ID 1 UE AMF ID 4
```

The AMF log confirms the same NGAP flow and three release completions during
the rollout window:

```text
Received NGSetupRequest message, handling
Sending NG_SETUP_RESPONSE Ok
Received INITIAL_UE_MESSAGE message, handling
Received UE_CONTEXT_RELEASE_COMPLETE message, handling
Received INITIAL_UE_MESSAGE message, handling
Received UE_CONTEXT_RELEASE_COMPLETE message, handling
Received INITIAL_UE_MESSAGE message, handling
Received UE_CONTEXT_RELEASE_COMPLETE message, handling
Received INITIAL_UE_MESSAGE message, handling
```

## NGAP Delay Summary

All NGAP spans:

```text
decoder.queue_delay_ms:
  min = 0.037645
  avg = 5.330089
  max = 314.247177

decoder.duration_ms:
  min = 0.813022
  avg = 8.176278
  max = 320.365271

proxy.forward.duration_ms:
  min = 0.009429
  avg = 0.194260
  max = 3.357199
```

The high all-span average is caused by the first NG setup pycrate warm-up:

```text
14:45:06.793 NGSetupRequest:
  decoder.duration_ms = 320.365271

14:45:06.799 NGSetupResponse:
  decoder.queue_delay_ms = 314.247177
```

UE-associated NGAP spans only:

```text
decoder.queue_delay_ms:
  min = 0.037645
  avg = 0.269554
  max = 2.693498

decoder.duration_ms:
  min = 0.941740
  avg = 3.095849
  max = 7.952685

proxy.forward.duration_ms:
  min = 0.009429
  avg = 0.197212
  max = 3.357199
```

Forwarding still completed before decode and correlation work, so these decoder
attributes are trace annotation latency rather than packet forwarding overhead.

## Finding

This experiment validates the generation-scoped NGAP correlation change:

- all 62 NGAP spans decoded with `decoder.strategy=pycrate`;
- all 60 UE-associated NGAP spans used `ngap.ue.correlation_basis=ran_id_generation`;
- reused `RAN-UE-NGAP-ID=1` produced four distinct correlation IDs from
  `ngap-ue-ran-1-gen-1` through `ngap-ue-ran-1-gen-4`;
- the first three generations ended with `UEContextReleaseComplete` and
  `ngap.ue.binding_released=true`;
- the fourth generation had no release because the capture ended while that UE
  was still attached;
- no proxy restarts, decode errors, or dropped trace events were observed.

The next step is to use these generation-scoped NGAP UE contexts as one side of
cross-protocol correlation with F1AP UE contexts. The likely bridge is CU UE ID
and timing around `InitialUEMessage`, `InitialULRRCMessageTransfer`, and
`UEContextSetupRequest`.
