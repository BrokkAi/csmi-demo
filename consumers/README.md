# Consumers (planned)

This directory is a scaffold for independent CSMI consumers. It is intentionally
documentation-only: no analyzer implementation, SDK, generated output, or
semantic pack belongs here yet.

Each consumer gets its own directory so that its inputs, configuration, and
eventual evidence can be reviewed independently. A consumer directory may use
the analyzer's own query language and configuration, but it must keep those
details local and apply them to the shared analyzer-neutral scenario contract.

## Planned consumers

- [`minimal-dataflow/`](minimal-dataflow/) — a small consumer that will check
  the meaning of procedure-summary transfers and report the planned
  pack-off/pack-on comparison.

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

Everything in this subtree is scaffolding and planned. There is no runnable
consumer in this repository yet.
