# Architecture Notes

## Existing HTTP Sidecar

The current sidecar in `src/` is HTTP-oriented:

- it accepts `net/http` requests;
- it extracts trace context from HTTP headers;
- it injects trace context into forwarded HTTP headers;
- its init container redirects TCP service traffic to the proxy.

That model is a good fit for 5GC SBA APIs, but it does not directly apply to
NGAP, F1AP, PFCP, or lower-layer RAN traffic.

## Proposed Control-Plane Model

Use protocol-aware observers or proxies that produce telemetry without requiring
wire-level trace context injection.

```text
protocol proxy / observer
  -> decode message envelope
  -> extract stable identifiers
  -> ask correlator for trace/span relationship
  -> emit OpenTelemetry span or span event
  -> forward original message unchanged when acting as a proxy
```

## Correlator

The correlator is the key difference from HTTP propagation.

Instead of reading `traceparent` from a header, it builds relationships from
control-plane identifiers:

- node pair and interface;
- procedure code / message type;
- RAN UE NGAP ID and AMF UE NGAP ID;
- CU/DU UE identifiers;
- PDU Session ID;
- SEID / F-SEID from PFCP;
- TEID values that are assigned by control messages;
- timestamp window.

When the relationship is certain, the span can use a parent context selected by
the correlator. When the relationship is probable but not exact, use span links
and attributes instead of forcing a misleading parent-child tree.

## First Implementation Slice

1. Reuse the F1 proxy idea for SCTP control-plane interception.
2. Add lightweight F1AP message classification first, even before full ASN.1
   decoding.
3. Add a shared correlator API.
4. Add NGAP and PFCP after the F1-C path is stable.
