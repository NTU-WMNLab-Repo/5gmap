# PFCP Transaction Trace Experiment

## Metadata

- Date: 2026-08-20
- Experiment start: 2026-08-20 09:17:38.869 UTC
- Experiment start: 2026-08-20 17:17:38.869 Asia/Taipei
- Jaeger capture end: 2026-08-20 09:24:57.781537 UTC
- Jaeger capture end: 2026-08-20 17:24:57.781537 Asia/Taipei
- Git hash under test: 0d311a5 (Fix PFCP proxy image packaging)
- Proxy image: genechen0203/pfcp-udp-proxy:latest
- Proxy image ID:
  sha256:c508e48962210266677fc0c0ea7d0a564f5dc09fee708304d89b60d259c66957
- Topology: SMF -> pfcpproxy10 -> UPF over N4/PFCP UDP port 8805
- Scope: validate header-based PFCP request/response transaction traces after
  the proxy image was fixed to include the local transaction correlator package.

## Objective

Verify that the live PFCP proxy:

1. forwards N4 traffic unchanged before asynchronous tracing work;
2. creates one trace for each supported PFCP request/response transaction;
3. parents the request, response, and terminal summary under one immediately
   exported transaction root; and
4. keeps the transaction identifier, message-type pair, and sequence number
   consistent across the request and response.

The deployed transaction settings were:

~~~text
PFCP_TRANSACTION_TIMEOUT_MS            = 30000
PFCP_TRANSACTION_CLOSED_RETENTION_MS   = 5000
PFCP_TRANSACTION_MAX_CONTEXTS          = 10000
~~~

## Raw Evidence

- jaeger-pfcpproxy-traces.raw.json: unmodified Jaeger API response for the
  strict capture window.
- pfcp-proxy-log.raw.txt: unmodified PFCP proxy log collected with the stated
  lower bound.
- smf-log.raw.txt and upf-log.raw.txt: unmodified N4 endpoint logs collected
  with the same lower bound.
- pfcp-proxy-deployment.raw.yaml and pfcp-proxy-pod.raw.yaml: deployed proxy
  configuration, image ID, and runtime state.
- oai-pods.raw.txt: pod snapshot collected with the other evidence.

The Jaeger query was:

~~~text
service = pfcpproxy10
start   = 1787217458869000 = 2026-08-20 09:17:38.869000 UTC
end     = 1787217897781537 = 2026-08-20 09:24:57.781537 UTC
limit   = 2000
~~~

The first and last returned span starts are:

~~~text
1787217458869127 = 2026-08-20 09:17:38.869127 UTC
1787217889034042 = 2026-08-20 09:24:49.034042 UTC
~~~

The first span begins 0.127 ms after the requested lower bound. The raw
Kubernetes logs have only the lower bound and therefore contain a small amount
of traffic later than the strict Jaeger window; all counts and timing statistics
below use only the raw Jaeger response.

## Trace Structure Result

Jaeger returned 55 traces containing 220 spans. Every trace has exactly four
spans:

~~~text
PFCP <procedure> transaction
  PFCP <direction> <Request>
  PFCP <direction> <Response>
  PFCP <procedure> transaction summary
~~~

For all 55 traces, the root has no parent and each of the three other spans has
a CHILD_OF reference to that root. This validates the immediate-root design:
the root is exported before its children, while the request/response packet
spans retain their own receive-to-forward timestamps.

The root and summary deliberately end one nanosecond after their start. Jaeger
renders these anchor spans as 0 us because it stores durations in microseconds.
The request-to-terminal observation is instead recorded on the summary as
pfcp.transaction.observed_duration_ms.

The transaction procedure counts are:

~~~text
AssociationSetup       1
Heartbeat             43
SessionEstablishment   4
SessionModification    4
SessionDeletion        3
total                 55
~~~

Each transaction contains one request span with
pfcp.transaction.state=opened and one response span with
pfcp.transaction.state=matched. All 55 summaries have:

~~~text
pfcp.transaction.state        = matched
pfcp.transaction.close_reason = response
pfcp.transaction.attempts     = 1
~~~

There are no observed retransmission, timed_out, late_response,
late_duplicate_request, or orphan_response spans in this strict window. Both
tracing.dropped_events and decoder.dropped_events are zero for all message
spans.

## Request/Response Matching Evidence

For every one of the 55 traces:

~~~text
matching PFCP request/response message-type pair = 55 / 55
matching pfcp.sequence_number                    = 55 / 55
matching pfcp.transaction.id                     = 55 / 55
~~~

No mismatch was found. This validates the online correlator matching key for
the observed one-SMF/one-UPF topology.

The first Association Setup transaction is a concrete example:

~~~text
root:     PFCP AssociationSetup transaction
          span ID = d5b942f47e4d8607
          transaction ID = pfcp-1-5-85b80f-1

request:  PFCP smf_to_upf AssociationSetupRequest
          sequence = 8763407
          10.42.2.61:8805 -> 10.42.2.62:8805
          parent = d5b942f47e4d8607

response: PFCP upf_to_smf AssociationSetupResponse
          sequence = 8763407
          10.42.2.62:8805 -> 10.42.2.61:8805
          parent = d5b942f47e4d8607
          pfcp.transaction.response.matched = true

summary:  PFCP AssociationSetup transaction summary
          parent = d5b942f47e4d8607
          observed duration = 4.403628 ms
~~~

The proxy raw log records the same header prefixes and route:

~~~text
09:17:38.871  20 05 ... 85 b8 0f ...  AssociationSetupRequest
09:17:38.873  20 06 ... 85 b8 0f ...  AssociationSetupResponse
~~~

The SMF log records the received N4 Association Setup Response at
09:17:38.873749 UTC. It also records matching Session Establishment, Session
Modification, and Session Deletion responses for the later UE session
procedures. This corroborates that the proxy remained in the live N4 path while
the transaction traces were produced.

## Observed Transaction Duration

pfcp.transaction.observed_duration_ms measures from the first request receive
timestamp at the proxy to the response forwarding-complete timestamp at the
proxy. It is a proxy-observed request/response interval, not an end-to-end
NF-to-NF latency measurement.

~~~text
procedure              count  min ms    avg ms    max ms
AssociationSetup           1  4.403628  4.403628  4.403628
Heartbeat                 43  0.960039  3.560168  5.806519
SessionEstablishment       4  2.036706  2.597574  3.736009
SessionModification        4  1.884337  2.043968  2.345332
SessionDeletion            3  2.023524  2.743881  3.854507
~~~

## Forwarding And Decode Timing

The following statistics use the 110 packet message spans only and exclude the
immediate roots and summaries:

~~~text
proxy.forward.duration_ms: min=0.016505 avg=1.121382 max=4.287614
decoder.queue_delay_ms:    min=0.022784 avg=1.003358 max=9.213081
decoder.duration_ms:       min=0.009154 avg=0.057822 max=0.144005
~~~

The relay forwards the original UDP datagram before it enters the trace queue.
Therefore queue delay, header decode, transaction matching, and OTLP export are
observability work after forwarding; they are not added to
proxy.forward.duration_ms.

## Retransmission Scope

The SMF log reports:

~~~text
2026-08-20T09:17:38.868772
Failed to receive PFCP Association Response, Retrying .....!!
~~~

This is immediately before the strict Jaeger lower bound. The capture contains
only the subsequent Association Setup request observed by the healthy proxy, so
that transaction has attempts=1. This experiment validates normal matching and
closing, but does not validate the runtime retransmission path. A later
fault-injection experiment should drop an Association Setup or Heartbeat
response after the proxy has started, then verify that the repeated request is
tagged pfcp.transaction.state=retransmission, increments the attempt count, and
remains in the original trace.

## Result

The PFCP transaction tracer works for the observed live N4 path. It groups every
captured Association Setup, Heartbeat, Session Establishment, Session
Modification, and Session Deletion request/response pair into one complete
four-span trace. The parent relationships, transaction identifiers, sequence
numbers, and request/response type mappings are all consistent, with no queue
drops, timeouts, or unmatched responses in this run.

The next focused validation is retransmission handling under a controlled
response-loss fault. The later PFCP IE parsing work remains independent of this
transaction-trace result.

