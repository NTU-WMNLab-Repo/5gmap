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
