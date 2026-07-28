# F1AP Decoder Notes

This folder contains the F1AP decoder used by the SCTP tracing proxy.

## Current Decoder Level

The current decoder is a lightweight top-level classifier. It is enough to name
common F1AP procedures in Jaeger spans, but it is not a complete ASN.1 PER
decoder.

It currently extracts:

- F1AP PDU type: `initiatingMessage`, `successfulOutcome`, or
  `unsuccessfulOutcome`;
- F1AP procedure code;
- procedure name and message name for the procedures currently listed in
  `decoder.py`.

It does not fully decode:

- protocol IE containers;
- CU/DU UE F1AP IDs;
- transaction IDs;
- nested RRC or NAS payloads;
- extension IEs or release-specific additions.

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

## Full Decode Path

The next step is to generate a pycrate-compatible F1AP ASN.1 module from the
F1AP ASN.1 specification and wire it through
`protocols/asn1_per/pycrate_decoder.py`. Once that exists, this decoder can keep
the lightweight classifier as a fallback and use pycrate output to add fields
such as transaction ID and CU/DU UE F1AP IDs to span attributes.

## References

- 3GPP TS 38.473, F1AP constant definitions:
  https://itecspec.com/3gpp/38.473/s/9.4.7
- Wireshark F1AP ASN.1 PDU descriptions:
  https://gitlab.com/wireshark/wireshark/-/blob/master/epan/dissectors/asn1/f1ap/F1AP-PDU-Descriptions.asn
