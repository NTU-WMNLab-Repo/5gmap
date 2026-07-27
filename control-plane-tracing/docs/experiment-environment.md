# Experiment Environment

Use an environment that supports the required 5G control-plane networking
features before running experiments.

The expected requirements are:

- SCTP support;
- Kubernetes networking compatible with the OAI deployment;
- permission to run packet capture or protocol proxy components;
- access to Jaeger or an OpenTelemetry collector;
- reproducible deployment manifests and topology notes.

Before running any experiment, record:

- target environment;
- OAI version or deployment identifier;
- interfaces being intercepted;
- expected control procedure;
- packet/protocol logs captured;
- Jaeger/OpenTelemetry output observed.
