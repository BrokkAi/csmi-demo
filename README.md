# CSMI interoperability demos

This repository demonstrates that a consumer can use a
[Code Semantic Model Interchange (CSMI)](https://github.com/BrokkAi/code-semantic-model-interchange/blob/main/spec/0.1/specification.md) pack without
depending on the producer's internal representation.

> **Status:** the first deterministic fixture, labels, exact Bifrost-generated
> CSMI pack, and independently reproduced minimal-dataflow, FlowDroid, CodeQL,
> and Joern 4.0.592 consumer interoperability results are materialized. Small
> independent consumers additionally exercise the normative Rust and Java/JVM
> interoperability profiles.

This is not the CSMI standard and it is not a CSMI SDK. The normative
specification and schema live in the
[CSMI repository](https://github.com/BrokkAi/code-semantic-model-interchange).
This repository exists to exercise that contract independently, beginning with
the portability proof described by
[CSMI issue #11](https://github.com/BrokkAi/code-semantic-model-interchange/issues/11).

## The experiment

Each demo analyzes application code that calls a library whose implementation
is deliberately outside the analyzer's scope and is not internally indexed.
Each demo performs the same analysis twice and compares the results:

1. run the query with the CSMI semantic pack disabled;
2. run it again with the same pack enabled; and
3. compare both runs against labeled expected flows to expose false positives
   and false negatives.

The initial scenario pairs a genuine parameter-to-return transfer with a near
miss that has no such transfer. This makes both positive and negative flow
labels available. A consumer may recover recall, improve precision, or both;
its documentation and retained results must claim only the changes the evidence
actually supports.

Source and sink definitions belong to each consumer's query. The shared CSMI
pack carries only portable semantic facts such as transfers and completeness.

## Repository layout

```text
consumers/
  <consumer>/
scenarios/
  <scenario>/
```

- [`consumers/`](consumers/) contains one directory per analyzer or adapter.
  The deliberately small [`minimal-dataflow`](consumers/minimal-dataflow/)
  implementation is runnable and retains independent pack-off and pack-on
  results against the shared scenario. [`codeql`](consumers/codeql/) contains
  the CodeQL adapter and query integration. The
  [`flowdroid`](consumers/flowdroid/) consumer provides a pinned FlowDroid/Soot
  adapter and retained paired results. The [`joern`](consumers/joern/) consumer
  runs the same CPG with custom CSMI-derived semantics toggled off and on; its
  retained evidence shows the complete-empty summary removes one false positive
  while preserving the positive flow. The
  [`java-jvm-profile`](consumers/java-jvm-profile/) and
  [`rust-profile`](consumers/rust-profile/) consumers independently interpret
  the corresponding normative profile fixtures without Bifrost libraries or
  producer-local identity fallbacks.
- [`scenarios/`](scenarios/) contains analyzer-neutral application inputs,
  opaque dependency fixtures, labels, expected outcomes, and retained CSMI
  packs.
- [`external-normalize`](scenarios/external-normalize/) contains the first
  controlled Java fixture and exact Bifrost-generated CSMI pack.

Scenarios are shared deliberately. Every consumer must use the same pinned
library artifact, CSMI pack, and labels rather than maintaining a private copy.
That keeps comparisons meaningful and demonstrates that the artifact—not
consumer-specific glue—crosses the interoperability boundary.

## Consumer evidence contract

Once implemented, every consumer must provide reproducible commands for the
pack-off and pack-on runs. Each run must emit machine-readable JSON that records:

- the consumer name and exact version;
- the scenario and CSMI artifact identity;
- whether the pack was enabled;
- every labeled flow's expected and observed outcome;
- true-positive, false-positive, false-negative, and true-negative counts; and
- precision and recall when their respective denominators are nonzero.

The pack-on result must match the scenario labels. The pack-off result must
differ by at least one false positive or false negative for the scenario to
motivate a semantic pack. Undefined metrics must remain undefined rather than
being reported as zero, and a result must not claim that both precision and
recall improved unless both changes are present in the retained evidence.

See [`consumers/README.md`](consumers/README.md) and
[`scenarios/README.md`](scenarios/README.md) for the directory contracts.

## Adding work

Add a consumer only when implementation begins. Give it one directory under
`consumers/`, document the exact tool version and commands, and consume shared
scenario assets in place. In particular, this repository does not claim a
  completed CodeQL interoperability result until both modes run against a
  valid producer-generated pack. The retained CodeQL results now satisfy that
  requirement for the deliberately narrow static-call scenario.

Add a scenario under `scenarios/` only when it has a deterministic, pinned
opaque dependency, auditable labels, a CSMI artifact shared by all consumers,
and enough positive and negative cases to interpret the results honestly.

## License

This repository is licensed under the [Apache License 2.0](LICENSE).
