# NGAP Lightweight Decode Experiment

## Metadata

- Date: 2026-08-03
- Experiment start: 2026-08-03 13:14:59.016 UTC
- Experiment start: 2026-08-03 21:14:59.016 Asia/Taipei
- Capture end: 2026-08-03 13:22:07.971 UTC
- Git hash under test: `2e746eb`
- Topology: OAI split RAN with NGAP/N2 routed through `ngapproxy10` and F1-C
  routed through `f1proxy10`
- Scope: validate NGAP lightweight top-level decode after replacing opaque NGAP
  spans with classified procedure names

## Raw Evidence

- `jaeger-ngapproxy-traces.raw.json`: raw Jaeger API output for `ngapproxy10`,
  using a start time of `1785762899016000` Unix microseconds.
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
  docker-pullable://genechen0203/ngap-sctp-proxy@sha256:b61a3b36d1d51c9797f1042302032b694f6edf44a376640e8488a75a70f5b277
```

## Jaeger NGAP Summary

The NGAP Jaeger query returned:

```text
trace_count = 14
span_count = 14
earliest span start = 1785762899016494
earliest span start = 2026-08-03 13:14:59.016494 UTC
latest span start = 1785763010400385
latest span start = 2026-08-03 13:16:50.400385 UTC
decode_errors = 0
decoder.dropped_events max = 0
```

The earliest NGAP span is after the requested experiment start timestamp, so
this capture does not include earlier NGAP traces.

Message counts:

```text
NGSetupRequest = 1
NGSetupResponse = 1
InitialUEMessage = 1
DownlinkNASTransport = 2
UplinkNASTransport = 4
InitialContextSetupRequest = 1
InitialContextSetupResponse = 1
UERadioCapabilityInfoIndication = 1
PDUSessionResourceSetupRequest = 1
PDUSessionResourceSetupResponse = 1
```

Direction counts:

```text
cu_to_amf = 9
amf_to_cu = 5
```

Decode status:

```text
ngap.decode.status:
  classified = 14

decoder.strategy:
  lightweight = 14
```

PDU type counts:

```text
initiatingMessage = 11
successfulOutcome = 3
```

Observed procedure counts:

```text
4:DownlinkNASTransport = 2
14:InitialContextSetup = 2
15:InitialUEMessage = 1
21:NGSetup = 2
29:PDUSessionResourceSetup = 2
44:UERadioCapabilityInfoIndication = 1
46:UplinkNASTransport = 4
```

## NGAP Timeline

The Jaeger NGAP spans decode to this top-level timeline:

```text
13:14:59.016 cu_to_amf NGSetupRequest
13:14:59.020 amf_to_cu NGSetupResponse
13:16:49.819 cu_to_amf InitialUEMessage
13:16:49.863 amf_to_cu DownlinkNASTransport
13:16:49.872 cu_to_amf UplinkNASTransport
13:16:49.904 amf_to_cu DownlinkNASTransport
13:16:49.912 cu_to_amf UplinkNASTransport
13:16:49.919 amf_to_cu InitialContextSetupRequest
13:16:49.942 cu_to_amf UERadioCapabilityInfoIndication
13:16:49.943 cu_to_amf InitialContextSetupResponse
13:16:49.952 cu_to_amf UplinkNASTransport
13:16:50.159 cu_to_amf UplinkNASTransport
13:16:50.376 amf_to_cu PDUSessionResourceSetupRequest
13:16:50.400 cu_to_amf PDUSessionResourceSetupResponse
```

Successful outcomes were classified with the NGAP selector value `32`
(`0x20`):

```text
NGSetupResponse:
  ngap.pdu.selector = 32
InitialContextSetupResponse:
  ngap.pdu.selector = 32
PDUSessionResourceSetupResponse:
  ngap.pdu.selector = 32
```

This validates the NGAP-specific top-level selector mapping used by the light
decoder. It also confirms that the old F1AP-style `du_to_cu` / `cu_to_du`
direction labels were gone in this image.

## NGAP Log Cross-Check

The NGAP proxy log shows payload prefixes matching the Jaeger message names:

```text
0015... -> NGSetupRequest
2015... -> NGSetupResponse
000f... -> InitialUEMessage
0004... -> DownlinkNASTransport
002e... -> UplinkNASTransport
000e... -> InitialContextSetupRequest
200e... -> InitialContextSetupResponse
002c... -> UERadioCapabilityInfoIndication
001d... -> PDUSessionResourceSetupRequest
201d... -> PDUSessionResourceSetupResponse
```

The AMF log confirms the same control flow:

```text
Decoded NGAP message, procedure code 15
Received INITIAL_UE_MESSAGE message, handling
Encoding DOWNLINK NAS TRANSPORT message, sending
Decoded NGAP message, procedure code 46
Received UPLINK_NAS_TRANSPORT message, handling
Encoding INITIAL CONTEXT SETUP REQUEST message, sending
Decoded NGAP message, procedure code 44
Received UE_RADIO_CAP_IND message, handling
Decoded NGAP message, procedure code 14
Encoding PDU SESSION RESOURCE SETUP REQUEST message, sending
Decoded NGAP message, procedure code 29
```

The CU log confirms the CU-side view of the same flow:

```text
Send NGSetupRequest to AMF
Received NGSetupResponse from AMF
Create UE context (ID 1) for AMF
Initial Context Setup UE RAN ID 1 UE AMF ID 1
Send message to sctp: NGAP_InitialContextSetupResponse
UE 1: received PDU Session Resource Setup Request
```

## NGAP Delay Summary

NGAP lightweight decode delay attributes:

```text
decoder.queue_delay_ms:
  min = 0.034920
  avg = 0.168096
  max = 0.531051

decoder.duration_ms:
  min = 0.005587
  avg = 0.035234
  max = 0.106923

proxy.forward.duration_ms:
  min = 0.017669
  avg = 0.099027
  max = 0.262453
```

The light decoder is substantially cheaper than F1AP pycrate decode in this
run. Since forwarding still happens before decode, these decoder timings are
observability costs and not packet forwarding overhead.

## F1AP Reference Summary

The F1AP Jaeger query over the same window returned:

```text
trace_count = 24
span_count = 24
earliest span start = 2026-08-03 13:15:58.358125 UTC
latest span start = 2026-08-03 13:16:50.402143 UTC
decode_errors = 0
decoder.dropped_events max = 0
```

F1AP message counts:

```text
F1SetupRequest = 1
F1SetupResponse = 1
GNBDUConfigurationUpdate = 1
GNBDUConfigurationUpdateAcknowledge = 1
InitialULRRCMessageTransfer = 1
DLRRCMessageTransfer = 7
ULRRCMessageTransfer = 8
UEContextSetupRequest = 1
UEContextSetupResponse = 1
UEContextModificationRequest = 1
UEContextModificationResponse = 1
```

F1AP UE correlation summary:

```text
correlation_id = f1ap-ue-du-63472
du_id = 63472
cu_id = 1 after the initial DU-only span
c_rnti = 63472
c_rnti_hex = 0xf7f0
release_complete_spans = 0
```

The CU log matches this F1AP correlation context:

```text
Create UE context: CU UE ID 1 DU UE ID 63472 (rnti: f7f0)
Received RRCSetupComplete (RRC_CONNECTED reached)
received PDU Session Resource Setup Request
Received RRCReconfigurationComplete
```

## Finding

This experiment validates the first NGAP lightweight decoder:

- NGAP spans are no longer opaque;
- all 14 observed NGAP messages were classified;
- direction labels are protocol-correct: `cu_to_amf` and `amf_to_cu`;
- successful outcomes use the expected NGAP selector `0x20`;
- no NGAP decode errors, dropped trace events, or proxy restarts were observed;
- F1AP decode and UE correlation remained healthy in the same run.

The next useful step is to promote NGAP UE identifiers, especially
`RAN-UE-NGAP-ID` and `AMF-UE-NGAP-ID`, then start correlating NGAP UE spans with
the existing F1AP UE correlation state.
