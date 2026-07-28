# 5GMAP Control-Plane Tracing

This folder is for our control-plane tracing design and experiments.

The original `src/` folder is kept as the author's HTTP sidecar proxy. That
proxy works for 5GC SBA/core traffic because HTTP can carry OpenTelemetry trace
context in headers. The control-plane interfaces here are different: most of
them do not have HTTP-like headers, and modifying their payloads can break
protocol compatibility.

## Goal

Trace 5G control procedures across RAN and core components without relying on
HTTP header injection.

The first design direction is:

- keep the original HTTP sidecar path for SBA/core APIs;
- observe or proxy control-plane protocols with protocol-aware handlers;
- avoid tracing user-plane packet streams such as GTP-U;
- correlate spans using protocol identifiers such as UE IDs, procedure codes,
  SEIDs, TEIDs created by control messages, and node addresses;
- use OpenTelemetry spans, span links, and attributes to represent relationships
  when true context propagation is not available.

## Current Scope

In scope:

- NGAP over SCTP;
- F1AP/F1-C over SCTP;
- E1AP over SCTP;
- PFCP over UDP;
- control messages that create, modify, release, or bind UE/session context.

Out of scope for now:

- GTP-U packet tracing;
- per-packet data-plane spans;
- payload inspection of user traffic;
- modifying standardized protocol messages just to carry trace context.

PDCP is undecided. It is not treated as a first target because it is lower in
the RAN stack and is less naturally visible to a sidecar proxy. If we later find
control-relevant PDCP events in the OAI implementation, they should likely be
instrumented inside CU/DU code rather than intercepted as standalone network
messages.

## Folder Layout

```text
control-plane-tracing/
  README.md
  docs/
    architecture.md
    protocol-scope.md
    experiment-environment.md
  notes/
    f1-proxy-background.md
  src/
    README.md
    correlator/
    protocols/
      ngap/
      f1ap/
      e1ap/
      pfcp/
    proxies/
      sctp/
      udp/
  experiments/
    README.md
```

## Current Prototype

The first runnable prototype is:

```text
src/proxies/f1ap-sctp-proxy/
```

It is an experimental F1-C SCTP proxy. In this repository's RAN deployment it
listens on SCTP port `501`, forwards messages unchanged to the real CU, and
exports spans to the OpenTelemetry collector when
`OTEL_EXPORTER_OTLP_ENDPOINT` is configured.

## Environment Reminder

Run control-plane experiments in an environment that supports the required
networking features, especially SCTP, Kubernetes networking, and packet capture.
