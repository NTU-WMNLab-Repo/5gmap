# F1AP Pycrate Decode Validation

## Metadata

- Date: 2026-07-29
- Observation window: around 11:48-11:50 UTC+0
- Git hash under test: `727c548`
- Topology: OAI split RAN with F1-C routed through `f1proxy10`
- Scope: validate F1AP proxy decode correctness against CU logs and Jaeger spans

## Objective

Confirm that the F1AP SCTP proxy can decode F1AP with pycrate, that decoded
messages match the CU-side F1AP control flow, and that the decoded UE identifiers
are usable for the next correlation step.

## Proxy Log Evidence

The proxy observed the following F1-C SCTP messages:

| Proxy time | Direction | Payload prefix | Decoded message |
| --- | --- | --- | --- |
| 2026-07-29 11:48:59 | DU to CU | `0001...` | `F1SetupRequest` |
| 2026-07-29 11:48:59 | CU to DU | `4001...` | `F1SetupResponse` |
| 2026-07-29 11:48:59 | DU to CU | `0003...` | `GNBDUConfigurationUpdate` |
| 2026-07-29 11:48:59 | CU to DU | `4003...` | `GNBDUConfigurationUpdateAcknowledge` |
| 2026-07-29 11:49:50 | DU to CU | `000b...` | `InitialULRRCMessageTransfer` |
| 2026-07-29 11:49:50 | CU to DU | `000c...` | `DLRRCMessageTransfer` |
| 2026-07-29 11:49:50 | DU to CU | `000d...` | `ULRRCMessageTransfer` |
| 2026-07-29 11:49:50 | CU to DU | `0005...` | `UEContextSetupRequest` |
| 2026-07-29 11:49:50 | DU to CU | `4005...` | `UEContextSetupResponse` |
| 2026-07-29 11:49:51 | CU to DU | `0007...` | `UEContextModificationRequest` |
| 2026-07-29 11:49:51 | DU to CU | `4007...` | `UEContextModificationResponse` |

This sequence matches the expected OAI F1-C setup and single-UE attach flow.

## CU Log Alignment

The CU log showed the corresponding F1AP handlers and sends:

| CU log evidence | Expected proxy observation |
| --- | --- |
| `CU_handle_F1_SETUP_REQUEST` | `DU to CU F1SetupRequest` |
| `sending F1 Setup Response` | `CU to DU F1SetupResponse` |
| `CU_handle_gNB_DU_CONFIGURATION_UPDATE` | `DU to CU GNBDUConfigurationUpdate` |
| `F1AP_GNB_DU_CONFIGURATION_UPDATE_ACKNOWLEDGE` | `CU to DU GNBDUConfigurationUpdateAcknowledge` |
| `CU send DL_RRC_MESSAGE_TRANSFER` | `CU to DU DLRRCMessageTransfer` |
| `CU_handle_UL_RRC_MESSAGE_TRANSFER` | `DU to CU ULRRCMessageTransfer` |
| `F1AP_UE_CONTEXT_SETUP_REQ` | `CU to DU UEContextSetupRequest` |
| `F1AP_UE_CONTEXT_MODIFICATION_REQ` | `CU to DU UEContextModificationRequest` |

The CU also logged:

```text
Create UE context: CU UE ID 1 DU UE ID 63610 RNTI f87a
```

Jaeger spans decoded by the proxy contained the same UE identifiers:

```text
InitialULRRCMessageTransfer:
  f1ap.gnb.du.ue.f1ap.id = 63610

Later UE-specific F1AP spans:
  f1ap.gnb.cu.ue.f1ap.id = 1
  f1ap.gnb.du.ue.f1ap.id = 63610
```

This confirms that the pycrate decode output is extracting useful identifiers
for F1AP correlation.

## Jaeger Decode Evidence

Recent Jaeger spans for `f1proxy10` showed:

```text
decoder.strategy = pycrate
asn1.decode.full = true
decoder.dropped_events max = 0
```

The decoded spans also included useful F1AP IE summaries, for example:

```text
F1SetupRequest:
  f1ap.ie.names = TransactionID,GNB-DU-ID,GNB-DU-Name,GNB-DU-Served-Cells-List,...
  f1ap.transaction.id = 1

InitialULRRCMessageTransfer:
  f1ap.ie.names = GNB-DU-UE-F1AP-ID,NRCGI,C-RNTI,RRCContainer,DUtoCURRCContainer,TransactionID
  f1ap.gnb.du.ue.f1ap.id = 63610
  f1ap.transaction.id = 0

UEContextSetupRequest:
  f1ap.ie.names = GNB-CU-UE-F1AP-ID,GNB-DU-UE-F1AP-ID,NRCGI,ServCellIndex,...
  f1ap.gnb.cu.ue.f1ap.id = 1
  f1ap.gnb.du.ue.f1ap.id = 63610
```

## Decode Delay Measurements

Jaeger query over recent `f1proxy10` traces:

```text
pycrate_span_count = 24

decoder.queue_delay_ms:
  min = 0.045676
  avg = 14864.900832125
  max = 34852.841044

decoder.duration_ms:
  min = 415.991619
  avg = 1667.46902675
  max = 2024.553954

decoder.dropped_events:
  max = 0
```

Interpretation:

- Packet forwarding was not blocked by this delay because the proxy forwards the
  SCTP payload before enqueueing the trace job.
- The trace queue did not overflow in this run.
- pycrate APER decode is CPU-heavy enough that the single async worker can fall
  behind during bursts of F1AP/RRC control messages.

## Changes Made After This Observation

Because the decoded F1AP fields matched CU log evidence, the next useful step is
correlation rather than changing the basic decode strategy.

Because the queue delay was high while `decoder.dropped_events` remained zero,
small local decode-cost reductions were added:

- `ASN1_COPY_ROOT=0` is now the default, so the single trace worker reuses the
  pycrate root object instead of deep-copying it for every packet.
- `ASN1_INCLUDE_VALUE` was added. Setting `ASN1_INCLUDE_VALUE=0` disables the
  large `asn1.value` debug attribute while keeping promoted F1AP attributes such
  as IE names and UE IDs.

These changes are intended to reduce decode-worker cost without changing packet
forwarding behavior. They still need to be measured in a follow-up run after the
proxy image is rebuilt and redeployed.

## Next Step

Start F1AP-only correlation:

1. Use `InitialULRRCMessageTransfer` to create a correlation entry from
   `gNB-DU-UE-F1AP-ID` and `C-RNTI`.
2. Use `UEContextSetupRequest` to bind `gNB-CU-UE-F1AP-ID` to the same
   `gNB-DU-UE-F1AP-ID`.
3. Tag later F1AP messages with a stable `f1ap.ue.correlation_id` so Jaeger can
   group one UE's F1AP control flow.
