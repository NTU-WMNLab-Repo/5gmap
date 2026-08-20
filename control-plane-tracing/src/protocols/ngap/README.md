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

## PFCP Session To UE Correlation

### Conclusion

PFCP `Cause`, `Node ID`, and CP/UP `F-SEID` are necessary to describe an N4
session, but they are not sufficient to bind that session to the existing
NGAP-F1AP UE lifecycle:

- `Cause` says whether a PFCP procedure was accepted, partially accepted, or
  rejected. It carries no UE or session join identity.
- `Node ID` identifies a PFCP peer. Every UE session served by the same SMF or
  UPF shares that peer identity.
- CP `F-SEID` and UP `F-SEID` identify the two endpoints of a PFCP session,
  but neither is carried by NGAP or F1AP.

3GPP TS 23.502 says that the SMF stores the relation between an N4 Session ID
and a PDU Session for a UE. That relation is SMF state; it is not a portable
PFCP field that an N4-only proxy can directly join with `RAN-UE-NGAP-ID` or
`AMF-UE-NGAP-ID`. Therefore an online proxy must not treat `F-SEID` as a UE
identifier.

The intended binding chain is instead:

```text
F1AP UE lifecycle
  -- existing F1AP/NGAP correlation --> NGAP UE lifecycle
  -- RAN/AMF UE IDs + per-item PDU Session ID --> NGAP PDU session record
  -- N3 endpoint tuple (role, IP address, GTP-TEID) --> PFCP PDR/FAR state
  -- CP/UP F-SEID --> PFCP session lifecycle
```

The N3 endpoint tuple is the candidate cross-interface key. `GTP-TEID` alone
is not sufficient: matching must retain the endpoint role, IP address, and
the containing PFCP/NGAP session state. The exact N3 tuple equality must be
validated against an OAI capture before it is used as an online bind condition.
Timing can support that validation, but concurrent UEs make timing alone unsafe.

### Required Decode Scope

| Interface | Field or nested location | Why it is needed | Correlation role |
| --- | --- | --- | --- |
| NGAP | `RAN-UE-NGAP-ID`, `AMF-UE-NGAP-ID`, and the existing local/global UE lifecycle IDs | Identifies the UE that owns each NGAP PDU session. | Required UE-side scope; already promoted. |
| NGAP | Every PDU-session setup, modify, or release list item and its `PDU Session ID` | Binds an N2 PDU session record to the UE lifecycle. A message can contain multiple items, so one scalar attribute is not a complete representation. | Required UE-to-PDU-session link. |
| NGAP | `PDU Session Resource Setup Request Transfer` -> `UL NG-U UP TNL Information` -> transport-layer address and `GTP-TEID` | Identifies the 5GC/UPF endpoint that the NG-RAN should use for uplink N3 traffic. The transfer is an OCTET STRING carrying a separately APER-encoded structure, so it needs its own decoder. | Primary PFCP join candidate for the UPF-side endpoint. |
| NGAP | `PDU Session Resource Setup Response Transfer` -> `DL NG-U UP TNL Information` -> transport-layer address and `GTP-TEID` | Identifies the NG-RAN endpoint used for downlink N3 traffic. | Primary PFCP join candidate for the NG-RAN-side endpoint. |
| NGAP | PDU session modify and release list items/transfers, including `PDU Session ID` and cause where present | Keeps the per-UE PDU session state correct after setup and closes it without confusing later ID reuse. | Required lifecycle maintenance. |
| NGAP | `S-NSSAI` | Distinguishes slice context when several sessions are otherwise similar. | Supporting scope only; not unique per UE. |
| PFCP | `Node ID`, CP `F-SEID` in Session Establishment Request, UP `F-SEID` and `Cause` in Session Establishment Response | Establishes and names the PFCP session, and records whether it was accepted. | Required PFCP-local state; not a UE join key. |
| PFCP | `Create PDR` / `Created PDR` grouped IEs: `PDR ID`, `PDI`, `Source Interface`, and the relevant `F-TEID` or allocated local F-TEID | Associates a tunnel endpoint with a specific PFCP session and its traffic direction. | Required N3 endpoint extraction. |
| PFCP | `Create FAR` / `Update FAR` grouped IEs: `FAR ID`, `Forwarding Parameters`, `Destination Interface`, and `Outer Header Creation` | Captures the peer N3 destination IP address and GTP-TEID used when the UPF sends traffic toward the NG-RAN. | Required second-direction endpoint extraction. |
| PFCP | `UE IP Address`, `Network Instance`, and `S-NSSAI` when present | Useful for diagnostics and narrowing a candidate set. UE IP allocation may occur inside PFCP PDR state. | Supporting evidence only; never the sole bind key. |

The current NGAP decoder promotes a scalar `ngap.pdu.session.id` when pycrate
finds a matching value. That is useful for a one-session observation, but it
selects one value rather than constructing a record for every list item. Before
online PFCP correlation, the decoder must retain each PDU Session ID together
with its corresponding setup, modify, or release transfer.

### Why Some Fields Are Not Join Keys

- `Cause` proves a response outcome, not identity.
- `Node ID` scopes a PFCP association, not one UE.
- `F-SEID` is the durable PFCP-session key after a bind, but NGAP/F1AP do not
  carry it.
- `PDU Session ID` belongs to the UE's session context and is not a PFCP IE.
  It must remain paired with the NGAP UE lifecycle; it cannot by itself select
  one PFCP session among concurrent UEs.
- `UE IP Address` is not exposed as a normal outer NGAP PDU-session field. It
  can be allocated or reported in PFCP, while an NGAP path may carry related
  user information only inside NAS. Parsing NAS solely for this join would add
  privacy and ciphering concerns, so it is a diagnostic fallback rather than
  the primary design.
- `S-NSSAI` and `Network Instance` are shared by many sessions in a slice.

### Implementation And Validation Order

1. Add a bounded PFCP IE walker and promote the PFCP-local fields: `Cause`,
   `Node ID`, CP/UP `F-SEID`, and grouped PDR/FAR identifiers.
2. Decode only the PFCP nested endpoint fields needed for N3 matching:
   direction, IP address, and GTP-TEID. Do not export complete IE values.
3. Extend NGAP decoding to create one PDU-session record per list item and
   decode the embedded setup/response transfer APER values for the UL and DL
   NG-U UP TNL information.
4. Run an offline capture that proves both direction-specific N3 tuples match
   the expected PFCP session. Reject ambiguous or incomplete candidates.
5. Add an online PFCP-session child trace only after the offline result is
   stable across concurrent UE and PDU-session lifecycles.

The first three PFCP fields alone are still worthwhile because they make PFCP
transactions interpretable. They should be implemented together with the
minimal PDR/FAR tunnel extraction rather than being presented as a complete
cross-protocol correlation solution.

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
- 3GPP TS 23.502 v16.7.1, clause 4.4.1.2: the SMF stores the relation between
  an N4 Session ID and a PDU Session for a UE:
  https://www.etsi.org/deliver/etsi_ts/123500_123599/123502/16.07.01_60/ts_123502v160701p.pdf
- 3GPP TS 23.502 v16.11.0, clause 4.3.2.2.1: PDU-session establishment
  sequences N4 session establishment/modification with N2 setup and response:
  https://www.etsi.org/deliver/etsi_ts/123500_123599/123502/16.11.00_60/ts_123502v161100p.pdf
- 3GPP TS 38.413 v18.5.0, clauses 9.2.1.1, 9.2.1.2, 9.3.2.2, 9.3.2.5, and
  9.3.4.1-9.3.4.4: PDU Session ID list items, NG-U transport information,
  GTP-TEID, and embedded setup/modify transfers:
  https://www.etsi.org/deliver/etsi_ts/138400_138499/138413/18.05.00_60/ts_138413v180500p.pdf
- 3GPP TS 29.244 v18.5.0, clauses 5.6.2, 7.5.2.1, 7.5.3.1, 7.5.2.2,
  7.5.3.2, and the Outer Header Creation IE: PFCP session identity, PDR/FAR
  state, allocated F-TEIDs, and GTP-U destination tunnel information:
  https://www.etsi.org/deliver/etsi_ts/129200_129299/129244/18.05.00_60/ts_129244v180500p.pdf
