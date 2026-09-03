# Consumers

This directory contains independent CSMI consumers. Consumer-specific analyzer
inputs and results belong here; shared fixtures, labels, and semantic packs do
not.

Each consumer gets its own directory so that its inputs, configuration, and
eventual evidence can be reviewed independently. A consumer directory may use
the analyzer's own query language and configuration, but it must keep those
details local and apply them to the shared analyzer-neutral scenario contract.

## Consumers

- [`java-jvm-profile/`](java-jvm-profile/) — a dependency-free independent
  consumer for the normative Java/JVM 0.1 profile family. It keeps Java source
  and JVM binary identities distinct, validates evidence-bearing mappings and
  compatibility, and fails closed on name or descriptor resemblance.
- [`codeql/`](codeql/) — a fail-closed CSMI adapter with retained shared-scenario
  pack-off and pack-on CodeQL results.
- [`flowdroid/`](flowdroid/) — a pinned FlowDroid/Soot adapter with retained
  shared-scenario pack-off and pack-on interoperability results.
- [`minimal-dataflow/`](minimal-dataflow/) — a small graph consumer with
  complete diagnostic semantics coverage and retained shared-scenario pack-off
  and pack-on interoperability results.
- [`joern/`](joern/) — a pinned Joern 4.0.592 CPG consumer that projects the
  shared JVM structural identities and complete procedure summaries into exact,
  non-regex `FlowSemantic` entries. Its retained pack-off result has one false
  positive; pack-on matches both labels with precision and recall of 1.0.
- [`rust-profile/`](rust-profile/) — a dependency-free independent consumer for
  the normative `csmi.rust` 0.1.0 profile. It validates Cargo-resolved source
  identity, inherent generic functions, trait implementations, generated items,
  and explicit native mappings, with fail-closed near-miss tests.

Additional consumers may be added as separate directories once their scope and
evidence contract are defined.

Do not add an empty consumer placeholder. A directory should appear only when
work begins on a reproducible implementation; in particular, no CodeQL support
is implied until a runnable CodeQL consumer is present.

## Evidence boundary

The consumer documentation points at shared scenarios under
[`../scenarios/`](../scenarios/). A consumer may interpret those scenarios, but
the scenario remains the source of truth for expected flow labels. Any future
results must identify the exact fixture and configuration, distinguish pack-off
from pack-on, and preserve incomplete or unavailable evidence rather than
turning it into a clean result.

An unavailable, invalid, or unsupported shared pack remains a typed failure,
not a clean or successful consumer result.
