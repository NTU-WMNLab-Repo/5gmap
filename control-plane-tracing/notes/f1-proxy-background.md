# F1 Proxy Background

## What It Already Shows

gene466 previously built a similar F1 proxy for fault-tolerance experiments.
That work demonstrates a useful control-plane interception pattern:

- listens for DU connections on SCTP port `38472`;
- connects onward to the CU;
- forwards F1-C messages between DU and CU;
- preserves SCTP PPID handling by forcing PPID `62`;
- observes and modifies selected F1AP message bytes for fault-tolerance
  experiments;
- separately forwards F1-U/GTP-U on UDP port `2153`;
- moves the UDP data-plane forwarding to a worker thread to avoid blocking the
  SCTP control-plane path.

## Lessons For Tracing

For the new tracing work, that F1 proxy is most useful as a transport-level
starting point, not as a final protocol parser.

Useful parts to reuse conceptually:

- SCTP accept/connect/forward loop;
- active DU and standby DU state;
- CU and DU address tracking;
- isolated UDP forwarding path when needed for connectivity;
- deployment shape with SCTP and UDP service ports.

Parts to avoid for tracing:

- tracing or logging every GTP-U packet;
- modifying F1AP bytes unless the experiment requires it;
- relying only on hex prefix matching once we need robust procedure
  classification.

## First Adaptation Idea

Create an F1-C tracing proxy that forwards messages unchanged:

```text
DU -> tracing proxy -> CU
CU -> tracing proxy -> DU
```

For each SCTP message:

1. capture direction and metadata;
2. classify the F1AP procedure;
3. extract UE/session identifiers when available;
4. emit an OpenTelemetry span or event;
5. forward the original bytes unchanged.
