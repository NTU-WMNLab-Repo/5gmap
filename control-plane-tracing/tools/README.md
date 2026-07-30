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
