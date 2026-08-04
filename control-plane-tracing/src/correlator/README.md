# Control-Plane Correlators

Correlators consume decoded control-plane messages from the async trace worker
and return extra span attributes. They run after packet forwarding, so
correlation cost is trace-worker cost, not forwarding-path latency.

## F1AP

`f1ap.py` tracks UE bindings using scalar fields promoted by the F1AP decoder:

- `f1ap.gnb.du.ue.f1ap.id`
- `f1ap.gnb.cu.ue.f1ap.id`
- `f1ap.c.rnti`
- `f1ap.transaction.id`

When a UE identifier is present, the correlator emits:

- `f1ap.correlation.kind=ue`
- `f1ap.ue.correlation_id`
- `f1ap.ue.binding_state`
- `f1ap.ue.message_count`

`UEContextReleaseComplete` keeps the same UE correlation attributes on its span
and then removes the binding from memory, so later reused F1AP IDs do not
inherit the old UE context.

When no UE identifier is present but a transaction ID exists, it emits a
transaction-level fallback key:

- `f1ap.correlation.kind=transaction`
- `f1ap.transaction.correlation_id`

The first version is intentionally attributes-based. Jaeger can search and group
spans by these tags, while later work can use the same state to create explicit
OpenTelemetry links or parent-child relationships across protocols.

## NGAP

`ngap.py` tracks UE bindings using scalar fields promoted by the NGAP decoder:

- `ngap.ran.ue.ngap.id`
- `ngap.amf.ue.ngap.id`

When a UE identifier is present, the correlator emits:

- `ngap.correlation.kind=ue`
- `ngap.ue.correlation_id`
- `ngap.ue.correlation_basis`
- `ngap.ue.context_generation`
- `ngap.ue.binding_state`
- `ngap.ue.message_count`
- `ngap.ue.ran_id`
- `ngap.ue.amf_id`

`InitialUEMessage` usually starts as `ran_only` because the AMF UE NGAP ID has
not been allocated yet. Later UE-associated messages become `ran_amf_bound` when
both IDs have been observed.

The correlation ID is generation-scoped when a `RAN-UE-NGAP-ID` is available:

```text
ngap-ue-ran-1-gen-1
ngap-ue-ran-1-gen-2
```

This keeps separate UE context lifetimes apart when the CU/RAN reuses the same
RAN UE NGAP ID after release. The original protocol IDs are still exported as
`ngap.ue.ran_id` and `ngap.ue.amf_id`.

When no UE identifier is present, it emits:

- `ngap.correlation.kind=none`

`UEContextReleaseComplete` keeps the same UE correlation attributes on its span
and then removes the binding from memory. Generation counters are not reset, so
later reused NGAP IDs create a new correlation ID instead of inheriting the old
UE context.
