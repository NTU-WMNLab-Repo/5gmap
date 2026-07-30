# Control-Plane Tracing Source

This folder contains the control-plane tracing prototype code.

## Layout

```text
control-plane-tracing/src/
  correlator/
    f1ap.py
  proxies/
    sctp/
      relay.py
      async_trace_worker.py
    f1ap-sctp-proxy/
      f1ap_sctp_proxy.py
  protocols/
    asn1_per/
      pycrate_decoder.py
    f1ap/
      decoder.py
    ngap/
      decoder.py
    e1ap/
      decoder.py
```

## Responsibility Split

- `proxies/sctp/relay.py` handles generic SCTP forwarding.
- `proxies/sctp/async_trace_worker.py` handles async decode and span emission.
- `correlator/f1ap.py` keeps lightweight F1AP UE-context correlation state and
  emits span attributes for Jaeger filtering.
- `protocols/f1ap/decoder.py` handles F1AP message classification and decode.
- `protocols/asn1_per/pycrate_decoder.py` is the optional pycrate APER adapter.
- `proxies/f1ap-sctp-proxy/f1ap_sctp_proxy.py` is only a thin wrapper that wires
  config, SCTP relay, F1AP decoder, correlator, and the tracing worker together.

The SCTP relay does not wait for F1AP decoding. It forwards the original bytes
first, then enqueues a copied payload for the tracing worker.

## Forwarding And Decode Timing

The hot path is:

```text
SCTP recv
  -> record recv_time_ns with time.time_ns()
  -> forward original bytes
  -> compute forwarding duration with time.monotonic_ns()
  -> derive send_done_time_ns from recv_time_ns + forwarding duration
  -> enqueue copied payload and metadata
```

The worker path is:

```text
dequeue event
  -> measure queue delay with time.monotonic_ns()
  -> decode F1AP
  -> measure decoder duration with time.monotonic_ns()
  -> emit OpenTelemetry span
```

If the queue is full, the trace event is dropped and packet forwarding continues.
Decode delay should not become packet forwarding overhead.

## Jaeger Time Semantics

For each proxied F1AP message, the span timestamps are set explicitly:

- span start time: when the proxy received the SCTP message;
- span end time: when the proxy finished forwarding the original bytes;
- Jaeger duration: proxy forwarding duration, not decode duration;
- `proxy.forward.duration_ms`: same forwarding duration shown as an attribute;
- `decoder.queue_delay_ms`: time spent waiting in the async trace queue;
- `decoder.duration_ms`: time spent decoding and preparing span attributes.

`decoder.queue_delay_ms` and `decoder.duration_ms` are observability costs, not
packet forwarding latency. They are intentionally excluded from the Jaeger span
duration because packet forwarding happens before decode.

The receive timestamp uses `time.time_ns()`, which is Unix epoch wall-clock time
in nanoseconds. OpenTelemetry Python span `start_time` and `end_time` also expect
Unix epoch nanoseconds, so the recorded event time and the exported span time use
the same time basis. The forwarding duration itself is measured with
`time.monotonic_ns()` and added to the receive timestamp for the span end time,
so small system clock adjustments do not distort the forwarding-duration
attribute. Queue delay and decoder duration are also elapsed-time measurements,
so they use `time.monotonic_ns()` as well.

Across pods or nodes, timestamp alignment depends on the hosts' system clocks.
With normal NTP or chrony synchronization, spans from different pods should be
aligned well enough for this tracing view. If host clocks drift, Jaeger can show
cross-pod ordering skew even though this proxy records its own packet timestamps
correctly.

## F1AP Correlation

The first correlation layer is attributes-based. It does not change
OpenTelemetry trace IDs or parent-child relationships yet. Instead, the async
worker adds stable Jaeger-searchable tags after decode:

- `f1ap.correlation.kind`: `ue`, `transaction`, or `none`;
- `f1ap.ue.correlation_id`: stable UE-context key, usually based on
  `gNB-DU-UE-F1AP-ID`;
- `f1ap.ue.binding_state`: whether DU and CU UE IDs have both been observed;
- `f1ap.ue.message_count`: number of observed F1AP messages in that binding;
- `f1ap.ue.binding_released`: present on `UEContextReleaseComplete` when the
  in-memory binding is removed;
- `f1ap.transaction.correlation_id`: fallback key for non-UE transaction
  messages such as setup/configuration procedures.

This keeps the current low-overhead setting from the reduced ASN.1 export
experiment: `ASN1_COPY_ROOT=0` and `ASN1_INCLUDE_VALUE=0`. The correlator only
uses promoted scalar fields extracted by the decoder, so it does not need the
full `asn1.value` attribute.

## F1AP Decode Status

The current F1AP decoder has two paths:

- pycrate APER decode: enabled by default with pycrate's built-in
  `pycrate_asn1dir.F1AP` module;
- lightweight top-level decode: fallback that extracts PDU type, procedure code,
  and procedure name from observed OAI F1AP APER payloads.

The pycrate adapter is shared by future NGAP and E1AP decoders. The F1AP decoder
currently exports the decoded ASN.1 value in truncated form and promotes selected
fields into span attributes. It does not yet promote every IE into a dedicated
attribute or decode nested RRC/NAS payloads.

## References

- OpenTelemetry Trace API Specification
  - https://opentelemetry.io/docs/specs/otel/trace/api/

- pycrate (PyPI)
  - https://pypi.org/project/pycrate/
