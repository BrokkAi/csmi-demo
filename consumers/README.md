# Consumers

This directory contains independent CSMI consumers. Consumer-specific analyzer
inputs and results belong here; shared fixtures, labels, and semantic packs do
not.

Each consumer gets its own directory so that its inputs, configuration, and
eventual evidence can be reviewed independently. A consumer directory may use
the analyzer's own query language and configuration, but it must keep those
details local and apply them to the shared analyzer-neutral scenario contract.

## Consumers

- [`codeql/`](codeql/) — a fail-closed CSMI adapter and CodeQL query integration.
- [`flowdroid/`](flowdroid/) — a pinned FlowDroid/Soot adapter with retained
  shared-scenario pack-off and pack-on interoperability results.
- [`minimal-dataflow/`](minimal-dataflow/) — a small graph consumer with
  complete diagnostic semantics coverage and retained shared-scenario pack-off
  and pack-on interoperability results.

Additional consumers may be added as separate directories once their scope and
evidence contract are defined.

Do not add an empty consumer placeholder. A directory should appear only when
work begins on a reproducible implementation; in particular, no CodeQL support
is implied until a runnable CodeQL consumer is present.

## Evidence boundary

The consumer documentation will eventually point at shared scenarios under
[`../scenarios/`](../scenarios/). A consumer may interpret those scenarios, but
the scenario remains the source of truth for expected flow labels. Any future
results must identify the exact fixture and configuration, distinguish pack-off
from pack-on, and preserve incomplete or unavailable evidence rather than
turning it into a clean result.

An unavailable shared pack remains a typed failure, not a clean or successful
consumer result.
