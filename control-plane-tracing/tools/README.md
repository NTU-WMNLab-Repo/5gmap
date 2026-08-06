# Control-Plane Tracing Tools

## F1AP Jaeger Raw Analyzer

`analyze_jaeger_f1ap.py` summarizes Jaeger `/api/traces` raw JSON captured from
the F1AP proxy.

```sh
python control-plane-tracing/tools/analyze_jaeger_f1ap.py \
  control-plane-tracing/experiments/20260730-f1ap-correlation-ue-rollout/jaeger-f1proxy-traces.raw.json
```

Use `--no-timeline` for a shorter per-correlation summary:

```sh
python control-plane-tracing/tools/analyze_jaeger_f1ap.py \
  control-plane-tracing/experiments/20260730-f1ap-correlation-ue-rollout/jaeger-f1proxy-traces.raw.json \
  --no-timeline
```

The output groups spans by `f1ap.ue.correlation_id` and reports:

- timeline;
- DU/CU UE IDs;
- RNTI in decimal and hexadecimal form;
- release status;
- decoder and forwarding delay statistics.

## F1AP/NGAP Cross-Protocol Analyzer

`analyze_cross_protocol_correlation.py` compares F1AP and NGAP Jaeger raw JSON
offline. It builds one UE lifecycle per protocol-local correlation ID, then
scores one-to-one matches using multiple pieces of evidence:

- F1AP CU UE F1AP ID equals NGAP RAN UE NGAP ID;
- F1AP `InitialULRRCMessageTransfer` precedes NGAP `InitialUEMessage`;
- F1AP and NGAP lifecycle windows overlap;
- release-complete events align, or both lifecycles are still active at capture
  end.

```sh
python control-plane-tracing/tools/analyze_cross_protocol_correlation.py \
  --f1ap control-plane-tracing/experiments/20260804-ngap-generation-correlation-ue-rollout/jaeger-f1proxy-traces.raw.json \
  --ngap control-plane-tracing/experiments/20260804-ngap-generation-correlation-ue-rollout/jaeger-ngapproxy-traces.raw.json
```

Use `--timeline` to print a merged F1AP/NGAP control-message timeline for each
matched UE lifecycle:

```sh
python control-plane-tracing/tools/analyze_cross_protocol_correlation.py \
  --f1ap control-plane-tracing/experiments/20260804-ngap-generation-correlation-ue-rollout/jaeger-f1proxy-traces.raw.json \
  --ngap control-plane-tracing/experiments/20260804-ngap-generation-correlation-ue-rollout/jaeger-ngapproxy-traces.raw.json \
  --timeline
```

Use `--format json` when the output should be consumed by another script.

The analyzer treats CU UE ID and RAN UE NGAP ID equality as strong OAI evidence,
not a portable standards guarantee. Future online same-trace rendering would
need shared UE-session state before span export, and should close a trace when
release is observed, a protocol-local generation is reused, an SCTP/CU restart
invalidates state, or an idle timeout ends an incomplete lifecycle.
