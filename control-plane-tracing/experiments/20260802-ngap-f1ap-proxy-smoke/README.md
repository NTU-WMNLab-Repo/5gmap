# NGAP And Rebuilt F1AP Proxy Smoke Test

## Metadata

- Date: 2026-08-02
- Capture window: 2026-08-02 08:17:30 UTC to 2026-08-02 08:31:43.057 UTC
- Git hash under test: `a908fc9`
- F1AP proxy image digest:
  `docker-pullable://genechen0203/f1ap-sctp-proxy@sha256:45fc52abccb502d25cc1177b3eba64d5d964eba3ba0760345c776e1ed5219290`
- NGAP proxy image digest:
  `docker-pullable://genechen0203/ngap-sctp-proxy@sha256:3ed9687fc5d95344949a61cf61f60b4450cd9ff69417ff7f25855cba44d1de4f`
- Scope: smoke test the new NGAP SCTP proxy skeleton and verify that rebuilding
  and pushing the F1AP proxy image did not break F1AP decode or correlation.

## Raw Evidence

- `jaeger-f1proxy-traces.raw.json`: raw Jaeger API response for `f1proxy10`.
- `jaeger-ngapproxy-traces.raw.json`: raw Jaeger API response for
  `ngapproxy10`.
- `f1proxy-log.raw.txt`: raw F1AP proxy log from the capture window.
- `ngapproxy-log.raw.txt`: raw NGAP proxy log from the capture window.
- `cu-log.raw.txt`: raw CU log from the capture window.
- `amf-log.raw.txt`: raw AMF log from the capture window.
- `proxy-pods.raw.txt`: raw proxy pod image and restart-count snapshot.

The proxy pod snapshot showed both proxy containers running with zero restarts:

```text
f1proxy10 restart_count = 0
ngapproxy10 restart_count = 0
```

## Jaeger F1AP Summary

The F1AP Jaeger query returned:

```text
trace_count = 24
span_count = 24
earliest span start = 2026-08-02 08:18:51.027144 UTC
latest span start = 2026-08-02 08:19:43.306726 UTC
decode_errors = 0
decoder.dropped_events max = 0
```

Message counts:

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

Correlation summary:

```text
correlated_span_count = 20
uncorrelated_span_count = 4
correlation_id_count = 1
correlation_id = f1ap-ue-du-16520
du_id = 16520
cu_id = 1 after the initial DU-only span
c_rnti = 16520
c_rnti_hex = 0x4088
release_complete_spans = 0
```

The four uncorrelated spans are expected setup/configuration messages:

```text
F1SetupRequest
F1SetupResponse
GNBDUConfigurationUpdate
GNBDUConfigurationUpdateAcknowledge
```

## F1AP CU Log Cross-Check

The CU log confirms the same F1AP control flow observed by the proxy:

```text
Received F1 Setup Request from gNB_DU 3584 (oai-gnb-du10-rfsim)
DU 3584 (oai-gnb-du10-rfsim): sending F1 Setup Response
Create UE context: CU UE ID 1 DU UE ID 16520 (rnti: 4088, random ue id ...)
Received RRCSetupComplete (RRC_CONNECTED reached)
received PDU Session Resource Setup Request
Received RRCReconfigurationComplete
```

This matches the Jaeger F1AP timeline:

```text
F1SetupRequest -> F1SetupResponse
InitialULRRCMessageTransfer
DLRRCMessageTransfer / ULRRCMessageTransfer exchange
UEContextSetupRequest -> UEContextSetupResponse
UEContextModificationRequest -> UEContextModificationResponse
```

The rebuilt F1AP proxy image therefore did not visibly break the F1AP light
decode, pycrate decode, basic UE correlation, or transparent SCTP forwarding in
this run.

## F1AP Delay Summary

Overall F1AP delay attributes:

```text
decoder.queue_delay_ms:
  min = 0.026121
  avg = 73.588463
  max = 587.979042

decoder.duration_ms:
  min = 0.287259
  avg = 26.501351
  max = 586.985962

proxy.forward.duration_ms:
  min = 0.028216
  avg = 0.413213
  max = 3.138969
```

The high overall averages are caused by the initial F1 setup decode warm-up.
The slowest span was:

```text
F1SetupRequest:
  decoder.duration_ms = 586.985962
```

The next setup/configuration messages then waited behind that first decode:

```text
F1SetupResponse:
  decoder.queue_delay_ms = 586.786
GNBDUConfigurationUpdate:
  decoder.queue_delay_ms = 587.507
GNBDUConfigurationUpdateAcknowledge:
  decoder.queue_delay_ms = 587.979
```

The UE-related correlated spans were much lighter:

```text
decoder.queue_delay_ms:
  min = 0.026121
  avg = 0.190165
  max = 0.547560

decoder.duration_ms:
  min = 0.924356
  avg = 2.371729
  max = 8.736718

proxy.forward.duration_ms:
  min = 0.051054
  avg = 0.478242
  max = 3.138969
```

Since forwarding does not wait for decode, this decode warm-up delay affects
Jaeger attribute timing only. It is not packet forwarding overhead.

## Jaeger NGAP Summary

The NGAP Jaeger query returned:

```text
trace_count = 14
span_count = 14
earliest span start = 2026-08-02 08:17:46.724569 UTC
latest span start = 2026-08-02 08:19:43.303013 UTC
decode_errors = 0
decoder.dropped_events max = 0
```

Message counts in Jaeger:

```text
NGAP du_to_cu opaque_ngap_sctp_message = 9
NGAP cu_to_du opaque_ngap_sctp_message = 5
ngap.decode.status = not_decoded for all 14 spans
```

Direction-label observation:

```text
observed ngap.direction values = du_to_cu, cu_to_du
expected ngap.direction values = cu_to_amf, amf_to_cu
```

This was a direction-label bug in the shared SCTP relay. The relay still used
the F1AP names for downstream-to-upstream and upstream-to-downstream traffic.
For NGAP, downstream is the CU-CP and upstream is the AMF, so the correct labels
are `cu_to_amf` and `amf_to_cu`.

The bug affects Jaeger span names, `ngap.direction`, and NGAP proxy log labels
only. It does not change the packet forwarding path, SCTP metadata, payload
bytes, OTLP export, or the conclusion that the NGAP proxy was positioned on the
CU-CP to AMF path.

After this observation, the shared SCTP relay was adjusted to accept
protocol-specific direction names while keeping F1AP defaults unchanged. The
NGAP wrapper now sets:

```text
downstream_to_upstream_direction = cu_to_amf
upstream_to_downstream_direction = amf_to_cu
```

NGAP delay attributes:

```text
decoder.queue_delay_ms:
  min = 0.025702
  avg = 0.219847
  max = 0.593585

decoder.duration_ms:
  min = 0.004609
  avg = 0.012157
  max = 0.034921

proxy.forward.duration_ms:
  min = 0.032476
  avg = 0.199553
  max = 0.911575
```

The current NGAP proxy intentionally emits opaque spans only. It confirms that
SCTP forwarding and OTLP export work, but it does not yet decode NGAP procedure
names.

## NGAP AMF Log Cross-Check

The AMF log confirms that the opaque NGAP spans cover real N2 control messages:

```text
Received NGSetupRequest message, handling
Sending NG_SETUP_RESPONSE Ok
Received INITIAL_UE_MESSAGE message, handling
Encoding DOWNLINK NAS TRANSPORT message, sending
Received UPLINK_NAS_TRANSPORT message, handling
```

Therefore the NGAP skeleton is correctly positioned on the CU-to-AMF path and
is exporting spans to Jaeger. The missing piece is procedure-level NGAP decode
and later NGAP-to-F1AP correlation.

## Finding

This smoke test supports two conclusions:

- the NGAP SCTP proxy skeleton can transparently forward N2 SCTP traffic and
  emit opaque spans to Jaeger;
- the rebuilt F1AP proxy image still decodes F1AP setup and UE control
  messages, maintains the expected UE correlation ID, and forwards packets with
  no visible crash or dropped trace events.

The next useful step is to add NGAP light decode or pycrate-based NGAP APER
decode, then correlate NGAP UE identifiers with the existing F1AP UE correlation
state.
