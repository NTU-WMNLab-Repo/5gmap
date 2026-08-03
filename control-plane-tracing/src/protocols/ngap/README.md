# NGAP Decoder Notes

This folder contains the NGAP decoder used by the SCTP tracing proxy.

## Current Decoder Level

The current decoder uses a lightweight top-level classifier. It emits one span
per NGAP SCTP message and records protocol name, direction, SCTP metadata,
payload size, forwarding duration, queue delay, and decoder duration.

The lightweight path extracts:

- NGAP PDU type: `initiatingMessage`, `successfulOutcome`, or
  `unsuccessfulOutcome`;
- NGAP procedure code;
- procedure name and message name for procedures observed in the OAI
  registration and PDU session setup path.

The decoder does not yet promote NGAP IEs into first-class span attributes. In
particular, `RAN-UE-NGAP-ID` and `AMF-UE-NGAP-ID` are still future work.

Full pycrate APER decode should come after that, mainly for robust IE extraction
and for procedures whose fields are hard to locate with simple prefix-level
classification.

Currently promoted fields include:

- top-level PDU type, procedure code, procedure name, and message name;
- lightweight decode status;
- NGAP PDU selector and first octet.

## Lightweight Decode Basis

NGAP is carried as an ASN.1 APER encoded `NGAP-PDU`. The top-level PDU is a
CHOICE with these alternatives:

- `initiatingMessage`;
- `successfulOutcome`;
- `unsuccessfulOutcome`.

Each selected alternative is a SEQUENCE containing:

- `procedureCode`;
- `criticality`;
- `value`.

For the observed OAI NG-C payloads, the first two octets are enough to classify
the common registration and PDU session setup messages:

| Payload prefix | PDU type | Procedure code | Decoded message |
| --- | --- | ---: | --- |
| `0015...` | `initiatingMessage` | `21` | `NGSetupRequest` |
| `2015...` | `successfulOutcome` | `21` | `NGSetupResponse` |
| `000f...` | `initiatingMessage` | `15` | `InitialUEMessage` |
| `0004...` | `initiatingMessage` | `4` | `DownlinkNASTransport` |
| `002e...` | `initiatingMessage` | `46` | `UplinkNASTransport` |
| `000e...` | `initiatingMessage` | `14` | `InitialContextSetupRequest` |
| `200e...` | `successfulOutcome` | `14` | `InitialContextSetupResponse` |
| `002c...` | `initiatingMessage` | `44` | `UERadioCapabilityInfoIndication` |
| `001d...` | `initiatingMessage` | `29` | `PDUSessionResourceSetupRequest` |
| `201d...` | `successfulOutcome` | `29` | `PDUSessionResourceSetupResponse` |

These prefixes were validated against the AMF log from the
`20260802-ngap-f1ap-proxy-smoke` experiment. For example, the AMF decoded:

```text
0015... -> procedure code 21 -> NGSetupRequest
000f... -> procedure code 15 -> InitialUEMessage
002e... -> procedure code 46 -> UplinkNASTransport
000e... -> procedure code 14 -> InitialContextSetupRequest
001d... -> procedure code 29 -> PDUSessionResourceSetupRequest
```

The observed NGAP successful outcome prefix is `0x20`, not the `0x40` marker
used by the current F1AP lightweight decoder. Therefore NGAP should not reuse
the F1AP marker table directly. In particular, masking with `payload[0] & 0xC0`
does not preserve the observed NGAP successful outcome bit.

The lightweight decoder uses `payload[0] & 0xE0` as the top-level selector:

| Selector | PDU type |
| --- | --- |
| `0x00` | `initiatingMessage` |
| `0x20` | `successfulOutcome` |
| `0x40` | `unsuccessfulOutcome` |

`unsuccessfulOutcome` was not observed in the current OAI smoke test, so its
prefix should be added only after an error-path capture or a full APER decoder
confirms the encoded value.

## Correlation Candidates

The most important NGAP UE identifiers are:

- `RAN-UE-NGAP-ID`;
- `AMF-UE-NGAP-ID`.

These should become the first promoted attributes for NGAP correlation:

```text
ngap.ran.ue.ngap.id
ngap.amf.ue.ngap.id
ngap.ue.correlation_id
```

For cross-protocol correlation, `InitialUEMessage` is the likely bridge between
F1AP and NGAP because it is sent after the CU receives the UE's initial RRC/NAS
flow. The first implementation should correlate by timing and CU-side context
state before trying to parse NAS contents.

The `NAS-PDU` IE is important for 5GC behavior, but it should not be the first
target for this tracing proxy. The near-term goal is control-plane correlation,
so the decoder should identify the NGAP procedure and UE IDs while leaving NAS
payload parsing disabled unless a later experiment needs it.

## Planned Decode Path

Recommended implementation order:

1. Validate the table-driven lightweight decoder in Jaeger against AMF logs.
2. Promote `RAN-UE-NGAP-ID` and `AMF-UE-NGAP-ID` when they can be extracted
   cheaply and validated against AMF logs.
3. Add a pycrate APER path for robust IE extraction after the lightweight
   classifier is stable.

This mirrors the F1AP strategy: keep forwarding independent of decode, emit
useful spans quickly, then deepen the decoder without increasing packet
forwarding latency.

## References

- 3GPP TS 38.413 specification record:
  https://portal.3gpp.org/desktopmodules/Specifications/SpecificationDetails.aspx?specificationId=3223
- 3GPP TS 38.413 online index, NGAP message and ASN.1 sections:
  https://itecspec.com/3gpp/38.413
- OSS Nokalva NGAP ASN.1 excerpt showing `NGAP-PDU`, `InitiatingMessage`,
  `SuccessfulOutcome`, and `UnsuccessfulOutcome`:
  https://www.oss.com/support/samples/5G-ngap-java.html
- Wireshark NGAP display filter reference:
  https://www.wireshark.org/docs/dfref/n/ngap.html
