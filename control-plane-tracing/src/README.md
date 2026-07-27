# Source Placeholder

This folder is reserved for future control-plane tracing prototype.

The expected package areas are:

- `correlator/`: maps protocol identifiers to trace/span relationships;
- `protocols/`: protocol-specific classifiers and parsers;
- `proxies/`: transport-level SCTP and UDP proxy code.

No production code has been added yet. The first likely prototype should be an
F1-C SCTP tracing proxy based on the previously proven F1 proxy approach.
