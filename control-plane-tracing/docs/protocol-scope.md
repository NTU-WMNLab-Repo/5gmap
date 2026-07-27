# Protocol Scope

## NGAP

- Interface: CU-CP/gNB to AMF.
- Transport: SCTP.
- Encoding: ASN.1 PER.
- Trace approach: classify NGAP procedures and correlate by AMF UE NGAP ID,
  RAN UE NGAP ID, procedure code, and PDU session information.
- Do not inject custom fields into NGAP messages.

## F1AP / F1-C

- Interface: DU to CU-CP.
- Transport: SCTP.
- Encoding: ASN.1 PER.
- Trace approach: SCTP proxy or observer, then classify F1AP procedures.
- Background: gene466 previously built a similar F1 proxy, so we already know
  SCTP F1-C interception is feasible in this deployment style.
- Useful identifiers: CU UE F1AP ID, DU UE F1AP ID, transaction/procedure,
  tunnel endpoint information carried by control messages.

## E1AP

- Interface: CU-CP to CU-UP.
- Transport: SCTP.
- Encoding: ASN.1 PER.
- Trace approach: similar to F1AP, but focused on bearer/session setup between
  control and user-plane CU components.

## PFCP

- Interface: SMF to UPF.
- Transport: UDP.
- Trace approach: parse PFCP control messages only.
- Useful identifiers: SEID, F-SEID, sequence number, Node ID, PDR/FAR/QER IDs,
  and TEIDs assigned inside session establishment/modification messages.
- Avoid vendor/private IE injection unless there is a specific interoperability
  experiment.

## GTP-U

- Interface: data plane.
- Transport: UDP.
- Decision: out of scope.
- Reason: it carries user data and creates very high packet volume. Tracing it
  packet-by-packet is noisy, expensive, and not needed for the current goal.

## PDCP

- Decision: undecided.
- Current assumption: not a sidecar target.
- Reason: PDCP is lower in the RAN stack and may not appear as a clean external
  network interface for this tracing model.
- Next step: inspect the OAI CU/DU implementation only if we need PDCP-related
  control events.
