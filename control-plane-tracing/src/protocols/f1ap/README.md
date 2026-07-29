# F1AP Decoder Notes

This folder contains the F1AP decoder used by the SCTP tracing proxy.

## Current Decoder Level

The current decoder has two paths:

- pycrate APER decode: enabled by default through pycrate's built-in
  `pycrate_asn1dir.F1AP` module;
- lightweight top-level classification: used as a fallback when pycrate is not
  available or a payload cannot be decoded.

The pycrate path decodes the F1AP ASN.1 PDU and stores a truncated representation
of the decoded value in the `asn1.value` span attribute. It also promotes
selected fields into dedicated attributes.

The lightweight path extracts:

- F1AP PDU type: `initiatingMessage`, `successfulOutcome`, or
  `unsuccessfulOutcome`;
- F1AP procedure code;
- procedure name and message name for the procedures currently listed in
  `decoder.py`.

The decoder does not yet promote every decoded IE into a first-class span
attribute. It also does not decode nested RRC or NAS payloads.

Currently promoted fields include:

- pycrate module/object metadata;
- top-level PDU type, procedure code, criticality, and message name;
- protocol IE IDs and IE value names;
- common control identifiers when present, such as transaction ID,
  gNB-CU-UE-F1AP-ID, gNB-DU-UE-F1AP-ID, C-RNTI, SRB/DRB IDs, and PDU session ID.

## Lightweight Decode Basis

F1AP is carried as an ASN.1 APER encoded `F1AP-PDU`. The top-level PDU is a
CHOICE with these common alternatives:

- `initiatingMessage`;
- `successfulOutcome`;
- `unsuccessfulOutcome`.

For the observed OAI F1-C payloads, the first octet's high bits identify this
top-level CHOICE:

| Marker | PDU type |
| --- | --- |
| `0x00` | `initiatingMessage` |
| `0x40` | `successfulOutcome` |
| `0x80` | `unsuccessfulOutcome` |

The following octet is used as the procedure code for the currently observed
procedure-code range. This matches the F1AP constant definitions for common
procedures such as:

| Procedure code | Procedure |
| --- | --- |
| `0` | `Reset` |
| `1` | `F1Setup` |
| `2` | `ErrorIndication` |
| `3` | `gNBDUConfigurationUpdate` |
| `4` | `gNBCUConfigurationUpdate` |
| `5` | `UEContextSetup` |
| `6` | `UEContextRelease` |
| `7` | `UEContextModification` |
| `8` | `UEContextModificationRequired` |
| `10` | `UEContextReleaseRequest` |
| `11` | `InitialULRRCMessageTransfer` |
| `12` | `DLRRCMessageTransfer` |
| `13` | `ULRRCMessageTransfer` |
| `16` | `gNBDUResourceCoordination` |

`decoder.py` maps each procedure code and PDU type to the explicit F1AP message
name. This matters because not every `initiatingMessage` should be called a
`Request`. For example, `DLRRCMessageTransfer` and `ULRRCMessageTransfer` are
initiating messages, but they are not request/response pairs.

## Validation Examples

Observed OAI F1-C payload prefixes decode as:

| Payload prefix | Decoded message |
| --- | --- |
| `0001...` | `F1SetupRequest` |
| `4001...` | `F1SetupResponse` |
| `0003...` | `GNBDUConfigurationUpdate` |
| `4003...` | `GNBDUConfigurationUpdateAcknowledge` |
| `0005...` | `UEContextSetupRequest` |
| `4005...` | `UEContextSetupResponse` |
| `0007...` | `UEContextModificationRequest` |
| `4007...` | `UEContextModificationResponse` |
| `000b...` | `InitialULRRCMessageTransfer` |
| `000c...` | `DLRRCMessageTransfer` |
| `000d...` | `ULRRCMessageTransfer` |

## Pycrate Decode Path

pycrate 0.8.1 ships a generated F1AP module. The default runtime configuration
uses:

```text
F1AP_PYCRATE_MODULE=pycrate_asn1dir.F1AP
F1AP_PYCRATE_OBJECT=F1AP_PDU_Descriptions.F1AP_PDU
```

`protocols/asn1_per/pycrate_decoder.py` imports that root object, decodes the
payload with APER, then returns the pycrate `get_val()` structure to the F1AP
decoder. The F1AP decoder keeps the lightweight classification as a fallback and
uses the pycrate value to add richer attributes.

pycrate decode is CPU-heavy. The adapter keeps `ASN1_COPY_ROOT=0` by default
because the tracing worker is single-threaded, so each decode can reuse the same
root object. If Jaeger does not need the large `asn1.value` debug attribute, set
`ASN1_INCLUDE_VALUE=0` and keep the promoted F1AP attributes only.

The next useful step is not generating the F1AP module anymore; it is expanding
the field extraction policy. In particular, UE correlation needs robust
promotion of CU/DU UE F1AP IDs, transaction ID, and bearer/session identifiers
from every relevant message type.

## References

- 3GPP TS 38.473, F1AP constant definitions:
  https://itecspec.com/3gpp/38.473/s/9.4.7
- Wireshark F1AP ASN.1 PDU descriptions:
  https://gitlab.com/wireshark/wireshark/-/blob/master/epan/dissectors/asn1/f1ap/F1AP-PDU-Descriptions.asn
