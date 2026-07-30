# F1AP Correlation Attribute Validation

## Metadata

- Date: 2026-07-30
- Experiment start: 2026-07-30 13:46:19.634 UTC
- Experiment start: 2026-07-30 21:46:19.634 Asia/Taipei
- Git hash under test: `04c4459`
- Topology: OAI split RAN with F1-C routed through `f1proxy10`
- Scope: validate the first F1AP attributes-based correlation layer

## Objective

Confirm that the F1AP proxy still decodes F1-C messages with pycrate under the
reduced ASN.1 export profile, and that the new correlation layer emits stable
Jaeger-searchable attributes for one UE's F1AP control flow.

## Runtime Settings

The proxy was run with correlation enabled and the reduced ASN.1 export settings
from the previous experiment:

```yaml
- name: F1AP_ENABLE_CORRELATION
  value: "1"
- name: F1AP_CORRELATION_MAX_CONTEXTS
  value: "10000"
- name: ASN1_COPY_ROOT
  value: "0"
- name: ASN1_INCLUDE_VALUE
  value: "0"
```

`ASN1_INCLUDE_VALUE=0` keeps the large decoded ASN.1 tree out of Jaeger. The
correlator uses promoted scalar fields, so it does not require `asn1.value`.

## Raw Evidence

- `cu-log.raw.txt`: raw CU log captured from
  `2026-07-30T13:46:19.634Z`.
- `f1proxy-log.raw.txt`: raw F1 proxy log captured from
  `2026-07-30T13:46:19.634Z`.
- `jaeger-f1proxy-traces.raw.json`: raw Jaeger API output for `f1proxy10`, using
  a start time of `1785419179634000` Unix microseconds.

The Jaeger raw data contains:

```text
trace_count = 24
span_count = 24
F1SetupRequest count = 1
earliest span start = 1785419179634960
earliest span start = 2026-07-30 13:46:19.634960 UTC
latest span start = 1785419231369575
latest span start = 2026-07-30 13:47:11.369575 UTC
```

The earliest span is after the requested experiment start timestamp, so this
capture does not include earlier F1AP traces.

## CU Log Alignment

The CU log begins with the F1 setup phase:

```text
CU_handle_F1_SETUP_REQUEST
Received F1 Setup Request from gNB_DU 3584
sending F1 Setup Response
CU_handle_gNB_DU_CONFIGURATION_UPDATE
F1AP_GNB_DU_CONFIGURATION_UPDATE_ACKNOWLEDGE
```

The UE context creation log for this run was:

```text
Create UE context: CU UE ID 1 DU UE ID 45891 RNTI b343
```

The F1 proxy log and Jaeger spans show the corresponding F1-C sequence:

```text
F1SetupRequest
F1SetupResponse
GNBDUConfigurationUpdate
GNBDUConfigurationUpdateAcknowledge
InitialULRRCMessageTransfer
DLRRCMessageTransfer
ULRRCMessageTransfer
UEContextSetupRequest
UEContextSetupResponse
UEContextModificationRequest
UEContextModificationResponse
```

The Jaeger spans decoded by the proxy contained the same UE identifiers:

```text
InitialULRRCMessageTransfer:
  f1ap.gnb.du.ue.f1ap.id = 45891
  f1ap.c.rnti = 45891
  f1ap.ue.correlation_id = f1ap-ue-du-45891
  f1ap.ue.binding_state = du_only

Later UE-specific F1AP spans:
  f1ap.gnb.cu.ue.f1ap.id = 1
  f1ap.gnb.du.ue.f1ap.id = 45891
  f1ap.ue.correlation_id = f1ap-ue-du-45891
  f1ap.ue.binding_state = cu_du_bound
```

This confirms that the proxy can bind the initial DU-side UE identity to the
later CU/DU UE ID pair and keep using the same correlation ID.

## Jaeger Correlation Evidence

Message counts in the Jaeger capture:

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
f1ap.correlation.kind:
  ue = 20
  transaction = 4

f1ap.ue.correlation_id:
  f1ap-ue-du-45891 = 20

f1ap.ue.binding_state:
  du_only = 1
  cu_du_bound = 19

f1ap.transaction.correlation_id:
  f1ap-txn-F1Setup-1
  f1ap-txn-gNBDUConfigurationUpdate-1
```

The four transaction-correlated spans are the F1 setup and DU configuration
messages, which do not belong to a UE context. The remaining 20 UE-related spans
share the same `f1ap.ue.correlation_id`.

## Decode And Forwarding Measurements

Jaeger query over this experiment window:

```text
pycrate_span_count = 24
asn1.value count = 0

decoder.queue_delay_ms:
  min = 0.027029
  avg = 73.978360125
  max = 590.500014

decoder.duration_ms:
  min = 0.235784
  avg = 26.675916708333332
  max = 590.823169

proxy.forward.duration_ms:
  min = 0.012851
  avg = 0.4986663333333334
  max = 4.041013

decoder.dropped_events:
  max = 0
```

Compared with the previous reduced ASN.1 export run, queue delay and decode
duration stayed in the same range. This is expected because the correlation
layer uses already-promoted scalar fields and runs after packet forwarding.

The Jaeger span duration remains the SCTP forwarding duration. Decode queue
delay, decode duration, and correlation work are trace-worker costs, not
forwarding-path latency.

## Finding

The correlation layer worked for this single-UE F1AP flow:

- the first UE message created `f1ap-ue-du-45891`;
- later messages with both CU and DU UE IDs kept the same correlation ID;
- transaction-only setup/configuration messages were not incorrectly attached to
  the UE context;
- no trace events were dropped;
- disabling `asn1.value` did not block correlation.

Because the F1AP-only correlation attributes are now visible in Jaeger, the next
step should validate the same logic across repeated runs and then extend the
correlation model toward NGAP so one UE's F1AP and NGAP control-plane events can
be searched together.
