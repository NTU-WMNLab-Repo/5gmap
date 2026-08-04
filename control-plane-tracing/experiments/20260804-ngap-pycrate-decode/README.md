# NGAP Pycrate Decode Experiment

## Metadata

- Date: 2026-08-04
- Experiment start: 2026-08-04 08:08:28.765 UTC
- Experiment start: 2026-08-04 16:08:28.765 Asia/Taipei
- Capture end: 2026-08-04 08:15:15.734 UTC
- Git hash under test: `7fd9a86`
- Topology: OAI split RAN with NGAP/N2 routed through `ngapproxy10` and F1-C
  routed through `f1proxy10`
- Scope: validate NGAP pycrate APER decode, promoted NGAP identifiers, and F1AP
  health in the same run

## Raw Evidence

- `jaeger-ngapproxy-traces.raw.json`: raw Jaeger API output for `ngapproxy10`,
  using a start time of `1785830908765000` Unix microseconds.
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
  docker-pullable://genechen0203/ngap-sctp-proxy@sha256:934d1534c346af80b9d2ce4d22b95c66e833d6478ffb47799c3201584f29b41e
```

## Jaeger NGAP Summary

The NGAP Jaeger query returned:

```text
trace_count = 14
span_count = 14
earliest span start = 1785830908765192
earliest span start = 2026-08-04 08:08:28.765192 UTC
latest span start = 1785831019706926
latest span start = 2026-08-04 08:10:19.706926 UTC
decode_errors = 0
decoder.dropped_events max = 0
```

The earliest NGAP span is at the requested experiment start timestamp, so this
capture does not include earlier NGAP traces.

Decode strategy and status:

```text
decoder.strategy:
  pycrate = 14

ngap.decode.status:
  decoded = 14

asn1.decode.full = 14
asn1.value count = 0
```

This confirms that pycrate APER decode succeeded for every observed NGAP span
while the large `asn1.value` debug attribute remained disabled.

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

## Promoted NGAP Fields

The pycrate path promoted NGAP IE summaries for all spans:

```text
ngap.ie.count:
  min = 2
  avg = 4.142857
  max = 8
  count = 14
```

Promoted UE and session identifiers:

```text
ngap.ran.ue.ngap.id:
  1 = 12 spans

ngap.amf.ue.ngap.id:
  1 = 11 spans

ngap.rrc.establishment.cause:
  mo-Signalling = 1 span

ngap.pdu.session.id:
  10 = 2 spans
```

`InitialUEMessage` has `RAN-UE-NGAP-ID=1` before `AMF-UE-NGAP-ID` exists, while
later UE-associated messages contain both IDs. This is the expected shape for
the next NGAP UE correlator.

## NGAP Timeline

The Jaeger NGAP spans decode to this top-level timeline:

```text
08:08:28.765 cu_to_amf NGSetupRequest ran=- amf=- pdu_session=-
08:08:28.771 amf_to_cu NGSetupResponse ran=- amf=- pdu_session=-
08:10:19.131 cu_to_amf InitialUEMessage ran=1 amf=- pdu_session=-
08:10:19.173 amf_to_cu DownlinkNASTransport ran=1 amf=1 pdu_session=-
08:10:19.182 cu_to_amf UplinkNASTransport ran=1 amf=1 pdu_session=-
08:10:19.205 amf_to_cu DownlinkNASTransport ran=1 amf=1 pdu_session=-
08:10:19.213 cu_to_amf UplinkNASTransport ran=1 amf=1 pdu_session=-
08:10:19.220 amf_to_cu InitialContextSetupRequest ran=1 amf=1 pdu_session=-
08:10:19.243 cu_to_amf UERadioCapabilityInfoIndication ran=1 amf=1 pdu_session=-
08:10:19.246 cu_to_amf InitialContextSetupResponse ran=1 amf=1 pdu_session=-
08:10:19.254 cu_to_amf UplinkNASTransport ran=1 amf=1 pdu_session=-
08:10:19.462 cu_to_amf UplinkNASTransport ran=1 amf=1 pdu_session=-
08:10:19.678 amf_to_cu PDUSessionResourceSetupRequest ran=1 amf=1 pdu_session=10
08:10:19.706 cu_to_amf PDUSessionResourceSetupResponse ran=1 amf=1 pdu_session=10
```

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

The AMF log confirms the same NGAP procedure codes and control flow:

```text
Decoded NGAP message, procedure code 21
Received NGSetupRequest message, handling
Sending NG_SETUP_RESPONSE Ok
Decoded NGAP message, procedure code 15
Received INITIAL_UE_MESSAGE message, handling
Encoding DOWNLINK NAS TRANSPORT message, sending
Decoded NGAP message, procedure code 46
Received UPLINK_NAS_TRANSPORT message, handling
Encoding INITIAL CONTEXT SETUP REQUEST message, sending
Decoded NGAP message, procedure code 44
Received UE_RADIO_CAP_IND message, handling
Decoded NGAP message, procedure code 14
Handling Initial Context Setup Response
Encoding PDU SESSION RESOURCE SETUP REQUEST message, sending
Decoded NGAP message, procedure code 29
Handle PDU Session Resource Setup Response
```

The CU log confirms the CU-side view of the same flow:

```text
Send NGSetupRequest to AMF
Received NGSetupResponse from AMF
Create UE context (ID 1) for AMF
Initial Context Setup UE RAN ID 1 UE AMF ID 1
Send message to sctp: NGAP_InitialContextSetupResponse
UE 1: received PDU Session Resource Setup Request
PDU Session Setup: ID=10
```

## NGAP Delay Summary

NGAP pycrate decode delay attributes:

```text
decoder.queue_delay_ms:
  min = 0.033873
  avg = 22.215291
  max = 308.709364

decoder.duration_ms:
  min = 0.792610
  avg = 25.473804
  max = 315.015110

proxy.forward.duration_ms:
  min = 0.018438
  avg = 0.102834
  max = 0.340190
```

The high average is caused by the first `NGSetupRequest` pycrate decode:

```text
NGSetupRequest:
  decoder.duration_ms = 315.015110

NGSetupResponse:
  decoder.queue_delay_ms = 308.709364
```

After the initial NG setup warm-up, UE-associated messages decoded in a few
milliseconds. Since forwarding still happens before decode, this warm-up affects
Jaeger decoder attributes only. It is not packet forwarding overhead.

## F1AP Reference Summary

The F1AP Jaeger query over the same window returned:

```text
trace_count = 24
span_count = 24
earliest span start = 2026-08-04 08:09:27.891967 UTC
latest span start = 2026-08-04 08:10:19.710572 UTC
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
correlation_id = f1ap-ue-du-15887
du_id = 15887
cu_id = 1 after the initial DU-only span
c_rnti = 15887
c_rnti_hex = 0x3e0f
release_complete_spans = 0
```

The CU log matches this F1AP context:

```text
Create UE context: CU UE ID 1 DU UE ID 15887 (rnti: 3e0f)
Received RRCSetupComplete (RRC_CONNECTED reached)
UE 1: received PDU Session Resource Setup Request
Received RRCReconfigurationComplete
```

## Finding

This experiment validates the NGAP pycrate APER decoder:

- all 14 observed NGAP messages decoded with `decoder.strategy=pycrate`;
- all 14 NGAP spans had `ngap.decode.status=decoded`;
- no NGAP decode errors, dropped trace events, or proxy restarts were observed;
- `asn1.value` stayed disabled, so Jaeger did not store the full decoded ASN.1
  representation;
- pycrate promoted useful NGAP identifiers, including `RAN-UE-NGAP-ID`,
  `AMF-UE-NGAP-ID`, RRC establishment cause, and PDU session ID;
- F1AP decode and UE correlation remained healthy in the same run.

The next useful step is to implement an NGAP UE correlator that emits
`ngap.ue.correlation_id`, then connect that correlation ID to the existing F1AP
UE correlation state.
