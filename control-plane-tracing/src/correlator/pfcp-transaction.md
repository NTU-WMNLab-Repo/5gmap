# PFCP Transaction Correlation

`pfcp_transaction.py` groups one PFCP request, its retransmissions, and its
matching response into a single OpenTelemetry trace. It is local state inside
the PFCP proxy process: packet forwarding is already complete before the async
trace worker decodes a PFCP header or updates this state.

The current deployment has one PFCP proxy replica per slice. If that changes,
all datagrams for an SMF/UPF pair must remain sticky to one replica or this
state must move to a shared store.

## Input And Output

For every header-decoded PFCP message, the async UDP worker supplies:

- the decoded message type, request/response class, and 24-bit sequence number;
- the individual PFCP message bytes, even when an `FO=1` UDP datagram carries
  more than one message;
- the observed UDP source and destination IP address and port; and
- the packet receive and forwarding-complete timestamps recorded by the relay.

The correlator returns a parent context and scalar `pfcp.transaction.*`
attributes for that message span. It does not receive or export decoded PFCP
IE values, and it never changes the original UDP payload.

## Matching Key

TS 29.244 scopes a PFCP sequence number to outstanding requests sent from a
local IP address and UDP port to a remote PFCP peer. It is not globally unique.
The proxy keeps a local key containing:

```text
association epoch
request source IP and UDP port
request destination IP and UDP port
request message type
24-bit PFCP sequence number
```

The response must have the corresponding response type, the same sequence
number, and the reverse observed UDP tuple. A SHA-256 fingerprint of the
individual PFCP message is kept in memory only. It distinguishes an identical
request retransmission from an unexpected reuse of the same scoped sequence
number; no fingerprint or raw PFCP payload is exported to Jaeger.

An `AssociationSetupRequest` starts a new local association epoch for that peer
pair after a non-duplicate setup request. Existing active transactions for the
pair are force-closed as `association_reset`, so a restarted association cannot
inherit old sequence-number state.

## Trace Shape

When the first request is observed, the correlator immediately exports a
one-nanosecond root span named `PFCP <procedure> transaction`. The immediate
root gives later child spans a parent that Jaeger can already resolve; it is not
the request-to-response latency measurement.

The request, every retransmission, and the matching response are direct children
of that root. Their own start/end timestamps still describe when the proxy
received and forwarded their packets. On terminal state, the correlator exports
a child `PFCP <procedure> transaction summary` span. Its
`pfcp.transaction.observed_duration_ms` is the elapsed wall-clock time from the
first request receive timestamp to the terminal observation.

## State Tables And Transitions

The active table stores the matching key, the first request timestamp, request
fingerprint, trace identity, attempt count, and an idle deadline. The closed
table is a short-lived tombstone storing the same identity, terminal state, and
fingerprints.

| Observed message | Active-table result | Span state |
| --- | --- | --- |
| First supported request | Create a transaction and immediate root. | `opened` |
| Identical request with an active key | Increment attempt count and reset the idle deadline. | `retransmission` |
| Matching response | Export the response as a child, then close active state and export a `matched` summary. | `matched` |
| No request/retransmission before idle deadline | Remove active state and export a `timed_out` summary. | `timed_out` |
| Same active key but different request bytes | Force-close the old state, then open a new transaction marked sequence reuse. | `forced_closed` / `opened` |
| Duplicate request or response during closed retention | Preserve the original trace parent without reopening active state. | `late_duplicate_request` / `late_response` |
| Response with no active or closed request | Emit the ordinary message span without a shared transaction trace. | `orphan_response` |

A matching response normally closes the active transaction. PFCP retransmission
happens while the sender still considers a request outstanding; TS 29.244 says
the request is retained until its matching response is received or the sender
stops retransmitting. The closed tombstone is therefore not an active retry
window. It only keeps the trace identity briefly for late or duplicate UDP
traffic after normal closure.

If the async trace queue drops a packet, the correlator never sees it. A dropped
request can therefore leave a later response as `orphan_response`, and a dropped
response can leave an active request to time out. This is observability loss
only: the relay has already forwarded the original datagram before queueing.

## Retention Configuration

| Variable | Default | Meaning |
| --- | ---: | --- |
| `PFCP_TRANSACTION_TIMEOUT_MS` | `30000` | Idle time after the last request or retransmission before the proxy marks the active transaction `timed_out`. |
| `PFCP_TRANSACTION_CLOSED_RETENTION_MS` | `5000` | Time to retain a closed trace identity for late duplicate requests or responses. |
| `PFCP_TRANSACTION_MAX_CONTEXTS` | `10000` | Maximum active transactions, and separately the maximum retained closed tombstones. The oldest active transaction is force-closed as `capacity_evicted`; the oldest closed tombstone is discarded when its table is full. |

`T1` and `N1` are implementation-specific in TS 29.244; the specification does
not define a universal retry timer or retry count. The defaults above are proxy
memory bounds, not standard PFCP values. Once the deployed SMF and UPF expose
their actual retry budget, set `PFCP_TRANSACTION_TIMEOUT_MS` longer than the
largest expected gap between retransmissions and use
`PFCP_TRANSACTION_MAX_CONTEXTS` to cap memory under faults.

## Attributes

Every supported PFCP message span receives:

```text
pfcp.transaction.enabled
pfcp.transaction.id
pfcp.transaction.state
pfcp.transaction.role
pfcp.transaction.association_epoch
pfcp.transaction.attempt
pfcp.transaction.retransmission
```

Response spans additionally expose `pfcp.transaction.response.matched`. Late
traffic adds `pfcp.transaction.late_duplicate` and the original closed state.
Sequence-number conflicts add `pfcp.transaction.sequence_reuse`.

The transaction root records `pfcp.transaction.root=true`. The summary records
`pfcp.transaction.summary=true`, terminal state, close reason, attempt count,
and the observed request-to-terminal duration.

## References

- 3GPP TS 29.244, clause 6.4, Reliable Delivery of PFCP messages: sequence
  number scope, matching response behavior, retransmission, and
  implementation-specific `T1`/`N1`:
  https://www.etsi.org/deliver/etsi_ts/129200_129299/129244/19.04.00_60/ts_129244v190400p.pdf
- 3GPP TS 29.244, Table 7.3-1, PFCP request/response message types:
  https://portal.3gpp.org/desktopmodules/Specifications/SpecificationDetails.aspx?specificationId=3111
