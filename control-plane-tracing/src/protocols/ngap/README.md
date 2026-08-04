# NGAP Decoder Notes

This folder contains the NGAP decoder used by the SCTP tracing proxy.

## Current Decoder Level

The current decoder has two paths:

- pycrate APER decode: enabled by default through pycrate's built-in
  `pycrate_asn1dir.NGAP` module;
- lightweight top-level classification: used as a fallback when pycrate is not
  available or a payload cannot be decoded.

The pycrate path decodes the NGAP ASN.1 PDU, records pycrate module/object
metadata, and promotes selected fields into dedicated span attributes. The
lightweight path extracts:

- NGAP PDU type: `initiatingMessage`, `successfulOutcome`, or
  `unsuccessfulOutcome`;
- NGAP procedure code;
- procedure name and message name for procedures observed in the OAI
  registration and PDU session setup path.

Currently promoted fields include:

- pycrate module/object metadata;
- top-level PDU type, procedure code, criticality, and message name;
- protocol IE IDs and IE value names;
- common NGAP identifiers when present, such as `RAN-UE-NGAP-ID`,
  `AMF-UE-NGAP-ID`, global RAN node ID, RAN node name, NR CGI, TAI,
  RRC establishment cause, and PDU session ID.

`ngap.decode.status` is `decoded` when pycrate succeeds and `classified` when
the lightweight fallback is used.

The decoder intentionally does not promote raw `NAS-PDU` into Jaeger attributes
by default. The near-term goal is control-plane message classification and UE
correlation, not exposing inner NAS payload content.

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

These are promoted by the pycrate path when present:

```text
ngap.ran.ue.ngap.id
ngap.amf.ue.ngap.id
```

The NGAP correlator uses these promoted IDs to emit:

```text
ngap.ue.correlation_id
ngap.ue.correlation_basis
ngap.ue.context_generation
ngap.ue.binding_state
ngap.ue.message_count
```

When `RAN-UE-NGAP-ID` is available, `ngap.ue.correlation_id` is scoped by a
proxy-local generation counter:

```text
ngap-ue-ran-1-gen-1
ngap-ue-ran-1-gen-2
```

This is necessary because the RAN/CU can reuse `RAN-UE-NGAP-ID` after
`UEContextReleaseComplete`. The generation is not a protocol field; it is local
correlation state used to keep separate UE lifetimes from collapsing into one
Jaeger tag group.

For cross-protocol correlation, `InitialUEMessage` is the likely bridge between
F1AP and NGAP because it is sent after the CU receives the UE's initial RRC/NAS
flow. The first implementation should correlate by timing and CU-side context
state before trying to parse NAS contents.

The `NAS-PDU` IE is important for 5GC behavior, but it should not be the first
target for this tracing proxy. The near-term goal is control-plane correlation,
so the decoder should identify the NGAP procedure and UE IDs while leaving NAS
payload parsing disabled unless a later experiment needs it.

## Pycrate Decode Path

pycrate 0.8.1 ships a generated NGAP module. The default runtime configuration
uses:

```text
NGAP_ENABLE_PYCRATE=1
NGAP_PYCRATE_MODULE=pycrate_asn1dir.NGAP
NGAP_PYCRATE_OBJECT=NGAP_PDU_Descriptions.NGAP_PDU
```

`protocols/asn1_per/pycrate_decoder.py` imports that root object, decodes the
payload with APER, then returns the pycrate `get_val()` structure to the NGAP
decoder. The NGAP decoder keeps the lightweight classification as a fallback and
uses the pycrate value to add richer attributes.

The low-overhead default is:

```text
ASN1_COPY_ROOT=0
ASN1_INCLUDE_VALUE=0
ASN1_INCLUDE_SHOW=0
```

This keeps the promoted scalar attributes without exporting the large
`asn1.value` debug representation. Enable `ASN1_INCLUDE_VALUE=1` or
`ASN1_INCLUDE_SHOW=1` only for short debugging captures.

## Planned Decode Path

Recommended implementation order:

1. Validate NGAP UE correlation in Jaeger against AMF and CU logs.
2. Confirm `RAN-UE-NGAP-ID` and `AMF-UE-NGAP-ID` binding behavior across attach,
   PDU session setup, release, and UE rollout experiments.
3. Correlate NGAP UE spans with the existing F1AP UE correlation state.

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
- pycrate ASN.1 runtime notes:
  https://github-wiki-see.page/m/pycrate-org/pycrate/wiki/Using-the-pycrate-asn1-runtime
- Wireshark NGAP display filter reference:
  https://www.wireshark.org/docs/dfref/n/ngap.html
